"""
Custom Input Mapping Manager.

This module manages the dynamic mapping between custom API endpoints and the ObjectTypes
they collect. It provides functionality to store and retrieve mappings for use by both
custom_input and lifecycle_tracker.
"""

from datetime import datetime, timezone
from typing import Dict, List, Set, Optional
from intersight_helpers.logger_manager import setup_logging
from intersight_helpers import kvstore, constants

logger = setup_logging("custom_input_mapping")


class CustomInputMappingManager:
    """Manages mappings between custom API endpoints and collected ObjectTypes using KVStore."""

    def __init__(self, session_key: str, account_name: Optional[str] = None):
        """
        Initialize the mapping manager.

        Args:
            session_key (str): Splunk session key for KVStore access
            account_name (str): Optional account name for filtering mappings
        """
        self.session_key = session_key
        self.account_name = account_name
        self.kvstore_manager = kvstore.KVStoreManager(session_key=session_key)
        self.collection_name = constants.CollectionConstants.CUSTOM_INPUT_MAPPINGS

    def load_mappings(self) -> List[Dict]:
        """
        Load existing mappings from KVStore.

        Returns:
            List[Dict]: List of mapping records from KVStore:
            [
                {
                    "_key": "endpoint_path",
                    "input_name": "custom_input_name",
                    "api_endpoint": "compute/Blades",
                    "object_types": "compute.Blade,equipment.Fru",
                    "collections": "cisco_intersight_custom_compute_blade,cisco_intersight_custom_equipment_fru",
                    "last_updated": "2025-01-01T12:00:00Z",
                    "account_name": "account1"
                }
            ]
        """
        try:
            query = {}
            if self.account_name:
                query[constants.CollectionConstants.ACCOUNT_NAME] = self.account_name

            mappings = self.kvstore_manager.get(
                self.collection_name,
                fields=None,
                query=query
            )
            logger.info(
                "message=mapping_load | Loaded %d mapping records from KVStore",
                len(mappings)
            )
            return mappings
        except kvstore.CollectionNotFoundError:
            logger.warning(
                "message=mapping_load_error | KVStore collection %s not found. "
                "Ensure collection is defined in collections.conf",
                self.collection_name
            )
            return []
        except Exception as e:
            logger.error(
                "message=mapping_load_error | Error loading mappings from KVStore: %s",
                e, exc_info=True
            )
            return []

    def save_mapping(self, mapping_record: Dict) -> bool:
        """
        Save a single mapping record to KVStore.

        Args:
            mapping_record (Dict): Mapping record to save with _key field

        Returns:
            bool: True if successful, False otherwise
        """
        try:
            self.kvstore_manager.upsert([mapping_record], self.collection_name)
            logger.info(
                "message=mapping_save | Saved mapping for endpoint %s to KVStore",
                mapping_record.get('api_endpoint')
            )
            return True
        except Exception as e:
            logger.error(
                "message=mapping_save_error | Error saving mapping to KVStore: %s",
                e, exc_info=True
            )
            return False

    def update_endpoint_mapping(self, input_name: str, api_endpoint: str,
                                collected_object_types: List[str]) -> None:
        """
        Update mappings after a custom input run.

        Args:
            input_name (str): Name of the custom input
            api_endpoint (str): API endpoint that was called
            collected_object_types (List[str]): ObjectTypes that were collected
        """
        # Remove duplicates and sort
        unique_object_types = sorted(list(set(collected_object_types)))

        # Generate collection names for each ObjectType
        collections = []
        for obj_type in unique_object_types:
            collection_name = ("cisco_intersight_custom_" + "_".join(obj_type.split("."))).lower()
            collections.append(collection_name)

        unique_collections = sorted(list(set(collections)))
        current_time = self._get_current_timestamp()

        # Create mapping record for KVStore
        # Use api_endpoint as _key for easy lookup and updates
        mapping_record = {
            "_key": input_name + api_endpoint.replace("/", "_"),  # KVStore keys can't have slashes
            "input_name": input_name,
            "api_endpoint": api_endpoint,
            "object_types": ",".join(unique_object_types),  # Store as comma-separated string
            "collections": ",".join(unique_collections),
            "last_updated": current_time,
            "account_name": self.account_name or "default"
        }

        # Save to KVStore
        self.save_mapping(mapping_record)

        logger.info(
            "message=mapping_update | Updated mapping for endpoint %s: "
            "%d ObjectTypes -> %d collections",
            api_endpoint, len(unique_object_types), len(unique_collections)
        )

    def get_custom_input_collections(self) -> Dict[str, Dict]:
        """
        Get all collections created by custom inputs for lifecycle tracking.

        Returns:
            Dict[str, Dict]: Dictionary compatible with lifecycle tracker format:
            {
                "object_type": {
                    "collection": "collection_name",
                    "api_endpoint": "endpoint_path",
                    "input_name": "input_name"
                }
            }
        """
        mappings = self.load_mappings()
        custom_collections = {}

        for mapping in mappings:
            object_types_str = mapping.get("object_types", "")
            collections_str = mapping.get("collections", "")
            api_endpoint = mapping.get("api_endpoint", "")
            input_name = mapping.get("input_name", "")

            if object_types_str and collections_str:
                object_types = [ot.strip() for ot in object_types_str.split(",") if ot.strip()]
                collections = [c.strip() for c in collections_str.split(",") if c.strip()]

                # Map each object_type to its collection
                for i, obj_type in enumerate(object_types):
                    collection_name = collections[i] if i < len(collections) else collections[0]
                    custom_collections[obj_type] = {
                        "collection": collection_name,
                        "api_endpoint": api_endpoint,
                        "input_name": input_name
                    }

        logger.info(
            "message=mapping_get_collections | Retrieved %d custom input collections",
            len(custom_collections)
        )
        return custom_collections

    def get_endpoint_stats(self) -> List[Dict]:
        """
        Get statistics about custom input endpoints.

        Returns:
            List[Dict]: List of endpoint mapping records
        """
        return self.load_mappings()

    def cleanup_stale_mappings(self, active_inputs: Set[str]) -> None:
        """
        Remove mappings for custom inputs that no longer exist.

        Args:
            active_inputs (Set[str]): Set of currently active custom input names
        """
        mappings = self.load_mappings()

        # Find stale mappings
        stale_keys = []
        for mapping in mappings:
            if mapping.get("input_name") not in active_inputs:
                stale_keys.append(mapping.get("_key"))

        # Remove stale mappings from KVStore
        if stale_keys:
            try:
                # Build query to delete stale records
                for key in stale_keys:
                    query = {"_key": key}
                    self.kvstore_manager.delete_batch(query, self.collection_name)

                logger.info(
                    "message=mapping_cleanup | Removed %d stale endpoint mappings",
                    len(stale_keys)
                )
            except Exception as e:
                logger.error(
                    "message=mapping_cleanup_error | Error cleaning up stale mappings: %s",
                    e, exc_info=True
                )

    def _get_current_timestamp(self) -> str:
        """Get current timestamp in ISO format."""
        return datetime.now(timezone.utc).isoformat()


def get_mapping_manager(session_key: str, account_name: Optional[str] = None) -> CustomInputMappingManager:
    """
    Get or create the global mapping manager instance.

    Args:
        session_key (str): Splunk session key for KVStore access
        account_name (str): Optional account name for filtering mappings

    Returns:
        CustomInputMappingManager: The mapping manager instance
    """
    return CustomInputMappingManager(session_key, account_name)
