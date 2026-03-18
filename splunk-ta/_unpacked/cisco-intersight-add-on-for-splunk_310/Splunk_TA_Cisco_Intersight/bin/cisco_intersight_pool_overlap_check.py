#!/usr/bin/env python
"""
Cisco Intersight Pool Overlap Check Command.

This custom Splunk command detects overlapping pool ranges across multiple events.
Supports MAC pools, IPv4 pools, and IPv6 pools.
"""

# This import is required to resolve the absolute paths of supportive modules
import import_declare_test  # pylint: disable=unused-import

from splunklib.searchcommands import EventingCommand, Configuration, dispatch, Option
import sys
from typing import Iterator, Dict, Any, List, Set, Tuple, Optional
from intersight_helpers.logger_manager import setup_logging
import ipaddress

# Set up logging for this command
logger = setup_logging("ta_intersight_pool_overlap_check")


@Configuration()
class CiscoIntersightPoolOverlapCheck(EventingCommand):
    """
    Custom command to detect overlapping pool ranges across multiple events.

    Adds overlap fields to each event:
    - OverlappingMoids: Comma-separated list of Moids that overlap with this range
    - OverlappingRanges: Comma-separated list of overlapping ranges
    - OverlappingNames: Comma-separated list of overlapping pool names

    Example:
        | ciscointersightpooloverlapcheck pool_type="macpool"
        | ciscointersightpooloverlapcheck pool_type="ippool"
        | ciscointersightpooloverlapcheck pool_type="uuidpools"
        | ciscointersightpooloverlapcheck pool_type="iqnpool"
    """

    pool_type: str = Option(
        doc="Pool type to check for overlaps. Supported values: 'macpool', 'ippool', 'uuidpools', 'iqnpool'",
        require=True,
        validate=None
    )

    def transform(self, records: Iterator[Dict[str, Any]]) -> Iterator[Dict[str, Any]]:
        """
        Transform records by detecting overlapping pool ranges.

        Args:
            records: Iterator of event records from Splunk search

        Yields:
            Dict[str, Any]: Original events enhanced with overlap information
        """
        logger.info(
            "message=transform_start | Starting %s pool overlap detection",
            self.pool_type
        )

        # Validate pool type
        if self.pool_type not in ['macpool', 'ippool', 'uuidpools', 'iqnpool']:
            logger.error(
                "message=invalid_pool_type | Invalid pool_type: %s. "
                "Supported values: 'macpool', 'ippool', 'uuidpools', 'iqnpool'",
                self.pool_type
            )
            raise ValueError(f"Invalid pool_type: {self.pool_type}")

        # Convert generator to list to keep in memory
        events: List[Dict[str, Any]] = list(records)
        logger.info("message=events_loaded | Total events loaded for processing: %d", len(events))

        # Store all valid ranges with their details
        ranges: List[Dict[str, Any]] = []
        valid_events: List[Tuple[Dict[str, Any], Dict[str, Any]]] = []

        # First pass: collect all valid ranges based on pool type
        logger.info(
            "message=first_pass_start | Starting first pass: collecting valid %s ranges",
            self.pool_type
        )
        processed_count = 0
        error_count = 0
        skipped_count = 0

        for ev in events:
            processed_count += 1
            try:
                logger.debug("message=processing_event | Processing event with Moid=%s", ev.get('Moid', 'unknown'))

                if self.pool_type == 'macpool':
                    range_data = self._extract_mac_range(ev)
                elif self.pool_type == 'ippool':
                    range_data = self._extract_ip_range(ev)
                elif self.pool_type == 'uuidpools':
                    range_data = self._extract_uuid_range(ev)
                elif self.pool_type == 'iqnpool':
                    range_data = self._extract_iqn_range(ev)
                else:
                    logger.error("message=unsupported_pool_type | Unsupported pool_type: %s", self.pool_type)
                    continue

                if range_data is None:
                    skipped_count += 1
                    continue

                ranges.append(range_data)
                valid_events.append((ev, range_data))

                logger.debug(
                    "message=range_added | Added valid %s range: Moid=%s, Range=%s-%s",
                    self.pool_type, range_data['moid'], range_data['from_str'], range_data['to_str']
                )

                logger.debug(
                    "message=range_conversion | Converted addresses: Moid=%s, From=%s (%d), To=%s (%d)",
                    range_data['moid'], range_data['from_str'], range_data['from_num'],
                    range_data['to_str'], range_data['to_num']
                )

                if range_data['from_num'] > range_data['to_num']:
                    logger.warning(
                        "message=invalid_range | Invalid %s range detected: From %s (%d) > To %s (%d) for Moid %s",
                        self.pool_type, range_data['from_str'], range_data['from_num'],
                        range_data['to_str'], range_data['to_num'], range_data['moid']
                    )
                    skipped_count += 1
                    continue

                # Extract pool name with same logic as other fields
                name_raw = ev.get('Name', '')
                if isinstance(name_raw, list):
                    pool_name = name_raw[0].strip() if len(name_raw) > 0 else ''
                else:
                    pool_name = str(name_raw).strip() if name_raw else ''

                # Store the range data directly (it already has generic field names)
                # Update pool_name if it was extracted separately
                range_data['pool_name'] = pool_name or range_data.get('pool_name', 'Unknown')
                range_data['original_event'] = ev

                ranges.append(range_data)
                valid_events.append((ev, range_data))

            except Exception as e:
                logger.error(
                    "message=parse_error | Error parsing event: %s. Event data: %s",
                    str(e), ev
                )
                error_count += 1
                # Still yield the original event even if there was an error
                yield ev

        logger.info(
            "message=first_pass_complete | First pass completed: "
            "Processed=%d, Valid=%d, Skipped=%d, Errors=%d",
            processed_count, len(valid_events), skipped_count, error_count
        )

        # Second pass: find overlaps
        logger.info("message=second_pass_start | Starting second pass: detecting overlaps")
        overlap_detection_count = 0
        total_overlaps_found = 0

        for ev, current_range in valid_events:
            overlap_detection_count += 1
            overlapping_moids: Set[str] = set()
            overlapping_ranges: List[str] = []
            overlapping_names: List[str] = []
            overlapping_organization_names: List[str] = []
            overlapping_server_profile_names: List[str] = []
            overlapping_server_profile_moids: List[str] = []
            overlapping_server_moids: List[str] = []
            overlapping_server_names: List[str] = []
            seen_overlapping_moids: Set[str] = set()  # Track processed overlapping Moids

            logger.debug(
                "message=overlap_check_start | Checking overlaps for Moid=%s",
                current_range['moid']
            )

            for other_range in ranges:
                # Skip self-comparison
                if current_range['moid'] == other_range['moid']:
                    continue

                # Skip if we've already processed this overlapping Moid
                if other_range['moid'] in seen_overlapping_moids:
                    continue

                # For IQN pools, only compare with pools of the same prefix
                if (
                    self.pool_type == 'iqnpool' and current_range.get('iqn_prefix') != other_range.get('iqn_prefix')
                ):
                    logger.debug(
                        "message=iqn_prefix_mismatch | Skipping IQN pool comparison due to different prefix: "
                        "Current=%s (%s), Other=%s (%s)",
                        current_range['moid'], current_range.get('iqn_prefix'),
                        other_range['moid'], other_range.get('iqn_prefix')
                    )
                    continue

                # Check for overlap based on pool type
                has_overlap = self._check_overlap(current_range, other_range)

                if has_overlap:
                    overlapping_moids.add(other_range['moid'])
                    range_str = self._format_range_string(other_range)
                    overlapping_ranges.append(range_str)

                    # Add overlapping pool name
                    overlapping_pool_name = other_range.get('pool_name', 'Unknown')
                    if overlapping_pool_name and overlapping_pool_name not in overlapping_names:
                        overlapping_names.append(overlapping_pool_name)

                    # Find server information for this overlapping pool
                    overlapping_server_info = self._find_server_info_for_pool(other_range['moid'], valid_events)
                    if overlapping_server_info:
                        if overlapping_server_info['profile_name']:
                            overlapping_server_profile_names.append(overlapping_server_info['profile_name'])
                        if overlapping_server_info['profile_moid']:
                            overlapping_server_profile_moids.append(overlapping_server_info['profile_moid'])
                        if overlapping_server_info['server_moid']:
                            overlapping_server_moids.append(overlapping_server_info['server_moid'])
                        if overlapping_server_info['server_name']:
                            overlapping_server_names.append(overlapping_server_info['server_name'])
                        if overlapping_server_info['organization_name']:
                            overlapping_organization_names.append(overlapping_server_info['organization_name'])

                    # Mark this Moid as processed to avoid duplicates
                    seen_overlapping_moids.add(other_range['moid'])

                    logger.debug(
                        "message=overlap_detected | Overlap found: Current Moid=%s overlaps with "
                        "Moid=%s, Pool=%s",
                        current_range['moid'], other_range['moid'], overlapping_pool_name
                    )

            # Add the overlap information to the original event
            ev['OverlappingMoids'] = ', '.join(sorted(overlapping_moids)) if overlapping_moids else None
            ev['OverlappingRanges'] = '; '.join(overlapping_ranges) if overlapping_ranges else None
            ev['OverlappingNames'] = ', '.join(sorted(overlapping_names)) if overlapping_names else None
            ev['OverlappingOrganizationName'] = ', '.join(
                sorted(overlapping_organization_names)
            ) if overlapping_organization_names else None

            # Add server information fields
            ev['OverlappingServerProfileName'] = ', '.join(
                overlapping_server_profile_names
            ) if overlapping_server_profile_names else None
            ev['OverlappingServerProfileMoid'] = ', '.join(
                overlapping_server_profile_moids
            ) if overlapping_server_profile_moids else None
            ev['OverlappingServerMoid'] = ', '.join(overlapping_server_moids) if overlapping_server_moids else None
            ev['OverlappingServerName'] = ', '.join(overlapping_server_names) if overlapping_server_names else None

            if overlapping_moids:
                total_overlaps_found += len(overlapping_moids)
                logger.info(
                    "message=overlap_result | Moid=%s has %d overlapping ranges: %s",
                    current_range['moid'], len(overlapping_moids), ','.join(sorted(overlapping_moids))
                )
            else:
                logger.debug(
                    "message=no_overlap | Moid=%s has no overlapping ranges",
                    current_range['moid']
                )

            # Yield the modified event with original fields plus the new ones
            yield ev

        logger.info(
            "message=transform_complete | %s pool overlap detection completed: "
            "Events processed=%d, Total overlaps found=%d",
            self.pool_type, overlap_detection_count, total_overlaps_found
        )

    def _extract_mac_range(self, event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Extract MAC range information from an event.

        Args:
            event: Event dictionary

        Returns:
            Dictionary with range information or None if invalid
        """
        try:
            # Handle both single values and multi-value lists
            mac_from_raw = event.get('MacBlocks_From', '')
            mac_to_raw = event.get('MacBlocks_To', '')
            moid_raw = event.get('Moid', '')
            name_raw = event.get('Name', '')

            # Extract first value if it's a list, otherwise use as string
            mac_from = self._extract_field_value(mac_from_raw)
            mac_to = self._extract_field_value(mac_to_raw)
            moid = self._extract_field_value(moid_raw)
            pool_name = self._extract_field_value(name_raw)

            logger.debug(
                "message=mac_field_extraction | Extracted fields: Moid=%s, From=%s, To=%s, Name=%s",
                moid, mac_from, mac_to, pool_name
            )

            if not all([mac_from, mac_to, moid]):
                logger.warning(
                    "message=missing_mac_fields | Skipping record with missing required fields: "
                    "Moid=%s, MacBlocks_From=%s, MacBlocks_To=%s",
                    moid, mac_from, mac_to
                )
                return None

            mac_from_num = int(mac_from.replace(':', ''), 16)
            mac_to_num = int(mac_to.replace(':', ''), 16)

            return {
                'moid': moid,
                'pool_name': pool_name or 'Unknown',
                'range_type': 'mac',
                'from_str': mac_from,
                'to_str': mac_to,
                'from_num': mac_from_num,
                'to_num': mac_to_num
            }

        except Exception as e:
            logger.error(
                "message=mac_parse_error | Error parsing MAC event: %s. Event data: %s",
                str(e), event
            )
            return None

    def _extract_ip_range(self, event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Extract IP range information from an event (supports both IPv4 and IPv6).

        Args:
            event: Event dictionary

        Returns:
            Dictionary with range information or None if invalid
        """
        try:
            moid_raw = event.get('Moid', '')
            name_raw = event.get('Name', '')

            moid = self._extract_field_value(moid_raw)
            pool_name = self._extract_field_value(name_raw)

            if not moid:
                logger.warning(
                    "message=missing_ip_moid | Skipping record with missing Moid: %s",
                    moid
                )
                return None

            # Try IPv4 first
            ipv4_range = self._extract_ipv4_range(event, moid, pool_name)
            if ipv4_range:
                return ipv4_range

            # Try IPv6 if IPv4 failed
            ipv6_range = self._extract_ipv6_range(event, moid, pool_name)
            if ipv6_range:
                return ipv6_range

            logger.warning(
                "message=no_valid_ip_ranges | No valid IPv4 or IPv6 ranges found for Moid=%s",
                moid
            )
            return None

        except Exception as e:
            logger.error(
                "message=ip_parse_error | Error parsing IP event: %s. Event data: %s",
                str(e), event
            )
            return None

    def _extract_ipv4_range(self, event: Dict[str, Any], moid: str, pool_name: str) -> Optional[Dict[str, Any]]:
        """
        Extract IPv4 range information from an event.

        Args:
            event: Event dictionary
            moid: Pool Moid
            pool_name: Pool name

        Returns:
            Dictionary with IPv4 range information or None if invalid
        """
        try:
            ipv4_from_raw = event.get('ipv4blocks_from', '')
            ipv4_to_raw = event.get('ipv4blocks_to', '')
            ipv4_from_num_raw = event.get('ipv4blocks_from_num', '')
            ipv4_to_num_raw = event.get('ipv4blocks_to_num', '')

            ipv4_from = self._extract_field_value(ipv4_from_raw)
            ipv4_to = self._extract_field_value(ipv4_to_raw)
            ipv4_from_num = self._extract_field_value(ipv4_from_num_raw)
            ipv4_to_num = self._extract_field_value(ipv4_to_num_raw)

            # Check if we have either string or numeric representations
            if ipv4_from and ipv4_to:
                # Convert IP strings to numbers if numeric versions not available
                if not ipv4_from_num or not ipv4_to_num:
                    ipv4_from_num = self._ipv4_to_num(ipv4_from)
                    ipv4_to_num = self._ipv4_to_num(ipv4_to)
                else:
                    ipv4_from_num = int(ipv4_from_num)
                    ipv4_to_num = int(ipv4_to_num)

                logger.debug(
                    "message=ipv4_field_extraction | Extracted IPv4 fields: Moid=%s, "
                    "From=%s (%d), To=%s (%d), Name=%s",
                    moid, ipv4_from, ipv4_from_num, ipv4_to, ipv4_to_num, pool_name
                )

                return {
                    'moid': moid,
                    'pool_name': pool_name or 'Unknown',
                    'range_type': 'ipv4',
                    'from_str': ipv4_from,
                    'to_str': ipv4_to,
                    'from_num': ipv4_from_num,
                    'to_num': ipv4_to_num
                }
            elif ipv4_from_num and ipv4_to_num:
                # Only numeric versions available
                ipv4_from_num = int(ipv4_from_num)
                ipv4_to_num = int(ipv4_to_num)

                logger.debug(
                    "message=ipv4_numeric_extraction | Extracted IPv4 numeric fields: Moid=%s, "
                    "FromNum=%d, ToNum=%d, Name=%s",
                    moid, ipv4_from_num, ipv4_to_num, pool_name
                )

                return {
                    'moid': moid,
                    'pool_name': pool_name or 'Unknown',
                    'range_type': 'ipv4',
                    'from_str': self._num_to_ipv4(ipv4_from_num),
                    'to_str': self._num_to_ipv4(ipv4_to_num),
                    'from_num': ipv4_from_num,
                    'to_num': ipv4_to_num
                }

            return None

        except Exception as e:
            logger.error(
                "message=ipv4_parse_error | Error parsing IPv4 range: %s. Moid=%s",
                str(e), moid
            )
            return None

    def _extract_ipv6_range(self, event: Dict[str, Any], moid: str, pool_name: str) -> Optional[Dict[str, Any]]:
        """
        Extract IPv6 range information from an event.

        Args:
            event: Event dictionary
            moid: Pool Moid
            pool_name: Pool name

        Returns:
            Dictionary with IPv6 range information or None if invalid
        """
        try:
            ipv6_from_raw = event.get('ipv6blocks_from', '')
            ipv6_to_raw = event.get('ipv6blocks_to', '')
            ipv6_from_num_raw = event.get('ipv6blocks_from_num', '')
            ipv6_to_num_raw = event.get('ipv6blocks_to_num', '')

            ipv6_from = self._extract_field_value(ipv6_from_raw)
            ipv6_to = self._extract_field_value(ipv6_to_raw)
            ipv6_from_num = self._extract_field_value(ipv6_from_num_raw)
            ipv6_to_num = self._extract_field_value(ipv6_to_num_raw)

            # Check if we have either string or numeric representations
            if ipv6_from and ipv6_to:
                # Convert IP strings to numbers if numeric versions not available
                if not ipv6_from_num or not ipv6_to_num:
                    ipv6_from_num = self._ipv6_to_num(ipv6_from)
                    ipv6_to_num = self._ipv6_to_num(ipv6_to)
                else:
                    ipv6_from_num = int(ipv6_from_num)
                    ipv6_to_num = int(ipv6_to_num)

                logger.debug(
                    "message=ipv6_field_extraction | Extracted IPv6 fields: Moid=%s, "
                    "From=%s (%d), To=%s (%d), Name=%s",
                    moid, ipv6_from, ipv6_from_num, ipv6_to, ipv6_to_num, pool_name
                )

                return {
                    'moid': moid,
                    'pool_name': pool_name or 'Unknown',
                    'range_type': 'ipv6',
                    'from_str': ipv6_from,
                    'to_str': ipv6_to,
                    'from_num': ipv6_from_num,
                    'to_num': ipv6_to_num
                }
            elif ipv6_from_num and ipv6_to_num:
                # Only numeric versions available
                ipv6_from_num = int(ipv6_from_num)
                ipv6_to_num = int(ipv6_to_num)

                logger.debug(
                    "message=ipv6_numeric_extraction | Extracted IPv6 numeric fields: Moid=%s, "
                    "FromNum=%d, ToNum=%d, Name=%s",
                    moid, ipv6_from_num, ipv6_to_num, pool_name
                )

                return {
                    'moid': moid,
                    'pool_name': pool_name or 'Unknown',
                    'range_type': 'ipv6',
                    'from_str': str(ipv6_from_num),  # Simplified string representation
                    'to_str': str(ipv6_to_num),
                    'from_num': ipv6_from_num,
                    'to_num': ipv6_to_num
                }

            return None

        except Exception as e:
            logger.error(
                "message=ipv6_parse_error | Error parsing IPv6 range: %s. Moid=%s",
                str(e), moid
            )
            return None

    def _extract_uuid_range(self, event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Extract UUID range information from an event.

        Args:
            event: Event dictionary

        Returns:
            Dictionary with range information or None if invalid
        """
        try:
            # Handle both single values and multi-value lists
            uuid_start_raw = event.get('UUID_start', '')
            uuid_end_raw = event.get('UUID_end', '')
            moid_raw = event.get('Moid', '')
            name_raw = event.get('Name', '')

            # Extract first value if it's a list, otherwise use as string
            uuid_start = self._extract_field_value(uuid_start_raw)
            uuid_end = self._extract_field_value(uuid_end_raw)
            moid = self._extract_field_value(moid_raw)
            pool_name = self._extract_field_value(name_raw)

            logger.debug(
                "message=uuid_field_extraction | Extracted fields: Moid=%s, Start=%s, End=%s, Name=%s",
                moid, uuid_start, uuid_end, pool_name
            )

            if not all([uuid_start, uuid_end, moid]):
                logger.warning(
                    "message=missing_uuid_fields | Skipping record with missing required fields: "
                    "Moid=%s, UUID_start=%s, UUID_end=%s",
                    moid, uuid_start, uuid_end
                )
                return None

            # Convert UUID strings to numeric for comparison
            uuid_start_num = self._uuid_to_num(uuid_start)
            uuid_end_num = self._uuid_to_num(uuid_end)

            return {
                'moid': moid,
                'pool_name': pool_name or 'Unknown',
                'range_type': 'uuid',
                'from_str': uuid_start,
                'to_str': uuid_end,
                'from_num': uuid_start_num,
                'to_num': uuid_end_num
            }

        except Exception as e:
            logger.error(
                "message=uuid_parse_error | Error parsing UUID event: %s. Event data: %s",
                str(e), event
            )
            return None

    def _extract_iqn_range(self, event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Extract IQN range information from an event.

        Args:
            event: Event dictionary

        Returns:
            Dictionary with range information or None if invalid
        """
        try:
            # Handle both single values and multi-value lists
            iqn_start = event.get('IqnBlocks_start', '')
            iqn_end = event.get('IqnBlocks_end', '')
            moid = event.get('Moid', '')
            pool_name = event.get('Name', '')

            logger.info(
                "message=iqn_field_extraction | Extracted fields: Moid=%s, Start=%s, End=%s, Name=%s",
                moid, iqn_start, iqn_end, pool_name
            )

            if not all([iqn_start, iqn_end, moid]):
                logger.warning(
                    "message=missing_iqn_fields | Skipping record with missing required fields: "
                    "Moid=%s, IqnBlocks_start=%s, IqnBlocks_end=%s",
                    moid, iqn_start, iqn_end
                )
                return None

            # Parse IQN format: prefix|numeric_value
            start_prefix, start_num = self._parse_iqn(iqn_start)
            end_prefix, end_num = self._parse_iqn(iqn_end)

            # Validate that both IQNs have the same prefix
            if start_prefix != end_prefix:
                logger.warning(
                    "message=iqn_prefix_mismatch | IQN start and end have different prefixes: "
                    "Moid=%s, StartPrefix=%s, EndPrefix=%s",
                    moid, start_prefix, end_prefix
                )
                return None

            return {
                'moid': moid,
                'pool_name': pool_name or 'Unknown',
                'range_type': 'iqn',
                'from_str': iqn_start,
                'to_str': iqn_end,
                'from_num': start_num,
                'to_num': end_num,
                'iqn_prefix': start_prefix
            }

        except Exception as e:
            logger.error(
                "message=iqn_parse_error | Error parsing IQN event: %s. Event data: %s",
                str(e), event
            )
            return None

    def _parse_iqn(self, iqn_str: str) -> Tuple[str, int]:
        """
        Parse IQN string to extract prefix and numeric suffix.

        Args:
            iqn_str: IQN string (e.g., 'iqn.1995-07.naming-authority|0')

        Returns:
            Tuple of (prefix, numeric_value)
        """
        try:
            if '|' not in iqn_str:
                raise ValueError(f"Invalid IQN format - missing '|' separator: {iqn_str}")

            prefix, suffix = iqn_str.split('|', 1)
            numeric_value = int(suffix)

            logger.info(
                "message=iqn_parsing | Parsed IQN: %s -> Prefix=%s, Value=%d",
                iqn_str, prefix, numeric_value
            )

            return prefix, numeric_value

        except (ValueError, IndexError) as e:
            logger.error("message=iqn_parse_error | Error parsing IQN %s: %s", iqn_str, str(e))
            raise

    def _extract_field_value(self, field_value: Any) -> str:
        """
        Extract string value from field that might be a list or string.

        Args:
            field_value: Field value (string, list, or other)

        Returns:
            String value or empty string if invalid
        """
        if isinstance(field_value, list):
            return field_value[0].strip() if len(field_value) > 0 and field_value[0] else ''
        return str(field_value).strip() if field_value else ''

    def _find_server_info_for_pool(
        self, pool_moid: str, valid_events: List[Tuple[Dict[str, Any], Dict[str, Any]]]
    ) -> Optional[Dict[str, str]]:
        """
        Find server information for a given pool Moid by searching through valid events.

        Args:
            pool_moid: Pool Moid to find server info for
            valid_events: List of (event, range_data) tuples to search through

        Returns:
            Dictionary with server info or None if not found
        """
        for ev, range_data in valid_events:
            if range_data.get('moid') == pool_moid:
                # Extract server information from Current* fields
                profile_name = self._extract_field_value(ev.get('CurrentPoolServerProfileName', ''))
                profile_moid = self._extract_field_value(ev.get('CurrentPoolServerProfileMoid', ''))
                server_moid = self._extract_field_value(ev.get('CurrentPoolServerMoid', ''))
                server_name = self._extract_field_value(ev.get('CurrentPoolServerName', ''))
                organization_name = self._extract_field_value(ev.get('Organization.Name', ''))

                logger.debug(
                    "message=server_info_found | Pool Moid=%s, "
                    "ProfileName=%s, ProfileMoid=%s, ServerMoid=%s, ServerName=%s, OrganizationName=%s",
                    pool_moid, profile_name, profile_moid, server_moid, server_name, organization_name
                )

                return {
                    'profile_name': profile_name if profile_name else None,
                    'profile_moid': profile_moid if profile_moid else None,
                    'server_moid': server_moid if server_moid else None,
                    'server_name': server_name if server_name else None,
                    'organization_name': organization_name if organization_name else None
                }

        logger.debug("message=server_info_not_found | No server info found for Pool Moid=%s", pool_moid)
        return None

    def _check_overlap(self, range1: Dict[str, Any], range2: Dict[str, Any]) -> bool:
        """
        Check if two ranges overlap.

        Args:
            range1: First range dictionary
            range2: Second range dictionary

        Returns:
            True if ranges overlap, False otherwise
        """
        # Ranges overlap if: range1_start <= range2_end and range2_start <= range1_end
        return (range1['from_num'] <= range2['to_num']
                and range2['from_num'] <= range1['to_num'])

    def _format_range_string(self, range_data: Dict[str, Any]) -> str:
        """
        Format range data into a string representation.

        Args:
            range_data: Range dictionary

        Returns:
            Formatted range string
        """
        return f"{range_data['from_str']} - {range_data['to_str']}"

    def _ipv4_to_num(self, ipv4_str: str) -> int:
        """
        Convert IPv4 address string to numeric representation.

        Args:
            ipv4_str: IPv4 address string (e.g., "192.168.1.1")

        Returns:
            Numeric representation of IPv4 address
        """
        try:
            octets = ipv4_str.split('.')
            if len(octets) != 4:
                raise ValueError(f"Invalid IPv4 format: {ipv4_str}")

            result = 0
            for i, octet in enumerate(octets):
                result += int(octet) << (8 * (3 - i))
            return result
        except Exception as e:
            logger.error("message=ipv4_conversion_error | Error converting IPv4 %s to number: %s", ipv4_str, str(e))
            raise

    def _num_to_ipv4(self, num: int) -> str:
        """
        Convert numeric representation to IPv4 address string.

        Args:
            num: Numeric representation of IPv4 address

        Returns:
            IPv4 address string
        """
        try:
            return f"{(num >> 24) & 255}.{(num >> 16) & 255}.{(num >> 8) & 255}.{num & 255}"
        except Exception as e:
            logger.error("message=ipv4_num_conversion_error | Error converting number %d to IPv4: %s", num, str(e))
            return str(num)

    def _ipv6_to_num(self, ipv6_str: str) -> int:
        """
        Convert IPv6 address string to numeric representation.

        Args:
            ipv6_str: IPv6 address string

        Returns:
            Numeric representation of IPv6 address
        """
        try:
            return int(ipaddress.IPv6Address(ipv6_str))
        except Exception as e:
            logger.error("message=ipv6_conversion_error | Error converting IPv6 %s to number: %s", ipv6_str, str(e))
            raise

    def _uuid_to_num(self, uuid_str: str) -> int:
        """
        Convert UUID string to numeric representation for overlap comparison.

        Args:
            uuid_str: UUID string (e.g., 'A6FF9357-6C9A-43F6-0000-990000000000')

        Returns:
            Numeric representation of UUID
        """
        try:
            # Remove hyphens and convert to integer from hex
            hex_str = uuid_str.replace('-', '')

            # Validate UUID format (should be 32 hex characters after removing hyphens)
            if len(hex_str) != 32:
                raise ValueError(f"Invalid UUID format: {uuid_str}")

            # Convert hex string to integer
            return int(hex_str, 16)

        except Exception as e:
            logger.error("message=uuid_conversion_error | Error converting UUID %s to number: %s", uuid_str, str(e))
            raise


if __name__ == "__main__":
    dispatch(CiscoIntersightPoolOverlapCheck, sys.argv, sys.stdin, sys.stdout, __name__)
