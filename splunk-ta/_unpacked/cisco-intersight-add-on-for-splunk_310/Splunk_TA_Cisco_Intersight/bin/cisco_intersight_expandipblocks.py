#!/usr/bin/env python
"""
Cisco Intersight ExpandIpBlocks command.

This custom Splunk command expands array of IPBlock of the events which are passed to it.
"""

# This import is required to resolve the absolute paths of supportive modules
import import_declare_test  # pylint: disable=unused-import

import sys
from splunklib.searchcommands import dispatch, EventingCommand, Configuration


@Configuration()
class ExpandIPBlocksCommand(EventingCommand):
    """
    Expand multi-value IPv4/IPv6 block fields into multiple events.

    Usage:
        | inputlookup my_lookup
        | expandipblocks

    Behavior:
      - If ipv4blocks_from/to have multiple values (newline or comma separated),
        split them into separate events (zip style).
      - If ipv6blocks_from/to have multiple values, expand the same way.
      - If only single values exist → event is passed as-is.
      - Handles both IPv4 and IPv6 in same event (expands both together).
    """

    def transform(self, events):  # pylint: disable=arguments-renamed
        """
        Transform the events by expanding multi-value IPv4/IPv6 block fields into multiple events.

        :param events: List of dictionaries representing events.
        :type events: list
        :return: List of dictionaries representing transformed events.
        :rtype: list
        """
        for event in events:
            ipv4_from = self._split_lines(event.get("ipv4blocks_from"))
            ipv4_to = self._split_lines(event.get("ipv4blocks_to"))
            ipv6_from = self._split_lines(event.get("ipv6blocks_from"))
            ipv6_to = self._split_lines(event.get("ipv6blocks_to"))

            expanded = []

            # Expand IPv4 if multiple
            if ipv4_from and ipv4_to and len(ipv4_from) == len(ipv4_to) and len(ipv4_from) > 1:
                for f, t in zip(ipv4_from, ipv4_to):
                    new_event = event.copy()
                    new_event["ipv4blocks_from"] = f
                    new_event["ipv4blocks_to"] = t
                    expanded.append(new_event)

            # Expand IPv6 if multiple
            if ipv6_from and ipv6_to and len(ipv6_from) == len(ipv6_to) and len(ipv6_from) > 1:
                if expanded:  # if IPv4 expansion already happened
                    new_expanded = []
                    for e in expanded:
                        for f, t in zip(ipv6_from, ipv6_to):
                            new_event = e.copy()
                            new_event["ipv6blocks_from"] = f
                            new_event["ipv6blocks_to"] = t
                            new_expanded.append(new_event)
                    expanded = new_expanded
                else:  # only IPv6 expansion
                    for f, t in zip(ipv6_from, ipv6_to):
                        new_event = event.copy()
                        new_event["ipv6blocks_from"] = f
                        new_event["ipv6blocks_to"] = t
                        expanded.append(new_event)

            # Nothing expanded → yield as-is
            if expanded:
                for e in expanded:  # pylint: disable=use-yield-from
                    yield e
            else:
                yield event

    def _split_lines(self, value):
        """
        Convert newline or comma separated string into a list.

        Handles empty/None safely.
        """
        if not value:
            return None
        if isinstance(value, list):
            return [v.strip() for v in value if v.strip()]
        return [v.strip() for v in str(value).replace(",", "\n").splitlines() if v.strip()]


dispatch(ExpandIPBlocksCommand, sys.argv, sys.stdin, sys.stdout, __name__)
