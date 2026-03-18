"""REST handler for Splunk_TA_Cisco_Intersight accounts."""
# This import is required to resolve the absolute paths of supportive modules
# implemented throughout the add-on. The relative imports used in other files
# of the add-on are resolved by importing this module.
import import_declare_test  # noqa: F401  # pylint: disable=unused-import # needed to resolve paths

from splunktaucclib.rest_handler.endpoint import (
    field,
    validator,
    RestModel,
    SingleModel,
)
from splunktaucclib.rest_handler import admin_external, util
from splunktaucclib.rest_handler.admin_external import AdminExternalHandler
from splunk import admin, rest
from solnlib.utils import is_true
from urllib.parse import quote_plus
from intersight_helpers.validators import FetchExpirationTime, SplunkKvStoreRest
from intersight_helpers.conf_helper import (
    get_conf_file,
    delete_checkpoint,
)
from intersight_helpers.kvstore import KVStoreManager
from intersight_helpers.logger_manager import setup_logging
import logging
import traceback
from intersight_helpers.constants import MetricsDimensions, CollectionConstants
from intersight_helpers.custom_input_mapping import get_mapping_manager


util.remove_http_proxy_env_vars()


class IntersightAccountHandler(AdminExternalHandler):
    """Intersight Account Handler class."""

    def __init__(self, *args, **kwargs):
        """Initialize the IntersightAccountHandler class."""
        AdminExternalHandler.__init__(self, *args, **kwargs)

    def handleCreate(  # pylint: disable=invalid-name, arguments-renamed  # this is UCCs default function hence can't modify it
        self, conf_info
    ):
        """
        Create the Intersight account.

        :param conf_info: admin.MConfInfo object containing the configuration information.
        :return: None
        """
        try:
            acc_name = self.callerArgs.id
            logger = setup_logging('ta_intersight_account_creation', account_name=acc_name)
            logger.info("message=account_creation_start | Account Creation started.")
            self.validate_kvstore_creds(logger)
            super().handleCreate(conf_info)

            # If the inputs_created option is selected by the user, defaults inputs would be created
            if is_true(self.payload.get('inputs_created')):
                self.create_inputs()
        except Exception as e:
            logger.error(
                "message=account_creation_error | "
                f"Intersight account creation Error: \"{traceback.format_exc()}\""
            )
            raise admin.ArgValidationException(e)

    def handleEdit(  # pylint: disable=invalid-name, arguments-renamed  # this is UCCs default function hence can't modify it
        self, conf_info
    ):
        """
        Edit the Intersight account.

        :param conf_info: admin.MConfInfo object containing the configuration information.
        :return: None
        """
        try:
            acc_name = self.callerArgs.id
            logger = setup_logging('ta_intersight_account_edit', account_name=acc_name)
            logger.info("message=account_edit_start | Account Updation started.")
            self.validate_kvstore_creds(logger)
            super().handleEdit(conf_info)
            
            # Read the current configuration
            conf_dict = self.readConf("splunk_ta_cisco_intersight_account")

            # Assuming you're editing a specific stanza
            stanza = self.callerArgs.id
            if stanza in conf_dict:
                current_settings = conf_dict[stanza]
                # Access specific fields
                input_already_created = current_settings.get("inputs_created", '0')
                # If the inputs_created option while updating is selected by the user, defaults inputs would be created
                if not is_true(input_already_created) and is_true(self.payload.get('inputs_created')):
                    self.create_inputs()
        except Exception as e:
            logger.error(
                "message=account_updation_error | "
                f"Intersight account updation Error: \"{traceback.format_exc()}\""
            )
            raise admin.ArgValidationException(e)

    def validate_kvstore_creds(self, logger: logging.Logger):
        """Validate the KVstore credentials stored in the splunk_ta_cisco_intersight_settings.conf file"""
        try:
            conf_obj = get_conf_file(file="splunk_ta_cisco_intersight_settings", session_key=self.getSessionKey())
            conf_dict = conf_obj.get_all(only_current_app=True)
            stanza_present = False
            for stanza in conf_dict:
                if stanza == "splunk_rest_host":
                    stanza_present = True
                    splunk_kvstore_rest = SplunkKvStoreRest()
                    splunk_kvstore_rest.validate_splunk_kvstore_rest_credentials(conf_dict.get(stanza))
                    break
            if not stanza_present:
                raise admin.ArgValidationException(
                    "Error while connecting to Splunk KVstore. "
                    "Please check the KVstore credentials under Configuration -> 'KV Lookup Rest' tab."
                )
        except Exception as e:
            logger.error(e)
            raise admin.ArgValidationException(
                "Error while connecting to Splunk KVstore. "
                "Please check the KVstore credentials under Configuration -> 'KV Lookup Rest' tab."
            )

    def create_inputs(self):
        """Create inputs into inputs.conf file if automatic_input_creation checkbox selected."""

        input_stanzas = [
            {
                "name": "audit_alarms://{}_audit_logs".format(self.callerArgs.id),
                "acknowledge": 1,
                "enable_aaa_audit_records": 1,
                "enable_alarms": 0,
                "global_account": "{}".format(self.callerArgs.id),
                "index": "main",
                "interval": 900,
                "interval_proxy": 1,
                "date_input": 7,
                "disabled": 1,
                "info_alarms": 1,
                "suppressed": 1
            },
            {
                "name": "audit_alarms://{}_alarms".format(self.callerArgs.id),
                "acknowledge": 1,
                "enable_aaa_audit_records": 0,
                "enable_alarms": 1,
                "global_account": "{}".format(self.callerArgs.id),
                "index": "main",
                "interval": 900,
                "interval_proxy": 1,
                "date_input": 7,
                "disabled": 1,
                "info_alarms": 1,
                "suppressed": 1
            },
            {
                "name": "inventory://{}_intersight_inventory".format(self.callerArgs.id),
                "compute_endpoints": "All",
                "fabric_endpoints": "All",
                "global_account": "{}".format(self.callerArgs.id),
                "index": "main",
                "interval": 1800,
                "inventory": "compute,license,contract,target,network,fabric,advisories",
                "license_endpoints": "All",
                "ports_endpoints": "All",
                "pools_endpoints": "All",
                "advisories_endpoints": "All",
                "disabled": 1
            },
            {
                "name": "inventory://{}_intersight_ports_and_interfaces_inventory".format(self.callerArgs.id),
                "compute_endpoints": "All",
                "fabric_endpoints": "All",
                "global_account": "{}".format(self.callerArgs.id),
                "index": "main",
                "interval": 1800,
                "inventory": "ports",
                "license_endpoints": "All",
                "ports_endpoints": "All",
                "pools_endpoints": "All",
                "advisories_endpoints": "All",
                "disabled": 1
            },
            {
                "name": "inventory://{}_intersight_pools_inventory".format(self.callerArgs.id),
                "compute_endpoints": "All",
                "fabric_endpoints": "All",
                "global_account": "{}".format(self.callerArgs.id),
                "index": "main",
                "interval": 1800,
                "inventory": "pools",
                "license_endpoints": "All",
                "ports_endpoints": "All",
                "pools_endpoints": "All",
                "advisories_endpoints": "All",
                "disabled": 1
            },
            {
                "name": "metrics://{}_network_metrics".format(self.callerArgs.id),
                "global_account": "{}".format(self.callerArgs.id),
                "host_power_energy_metrics": "All",
                "index": "main",
                "interval": 900,
                "memory_metrics": "All",
                "metrics": "network",
                "network_metrics": "All",
                "disabled": 1
            },
            {
                "name": "metrics://{}_device_metrics".format(self.callerArgs.id),
                "global_account": "{}".format(self.callerArgs.id),
                "index": "main",
                "disabled": 1,
                "host_power_energy_metrics": "All",
                "interval": 900,
                "memory_metrics": "All",
                "metrics": "temperature,cpu_utilization,memory,host,fan",
                "network_metrics": "All"
            }
        ]

        inputs_created = []

        for input_stanza in input_stanzas:

            # Using Splunk internal API to create default input
            try:
                rest.simpleRequest(
                    "/servicesNS/nobody/{}/configs/conf-inputs".format(
                        import_declare_test.ta_name
                    ),
                    self.getSessionKey(),
                    postargs=input_stanza,
                    method="POST",
                    raiseAllErrors=True,
                )
                inputs_created.append(input_stanza)

            except Exception as e:
                for input in inputs_created:
                    encoded_stanza = quote_plus(
                        input.get("name"),
                        safe="",
                    )
                    rest.simpleRequest(
                        "/servicesNS/nobody/{}/configs/conf-inputs/{}".format(
                            import_declare_test.ta_name, encoded_stanza
                        ),
                        sessionKey=self.getSessionKey(),
                        method="DELETE",
                        getargs={"output_mode": "json"},
                        raiseAllErrors=True,
                    )
                if "409" in str(e):
                    e = "Cannot create the account because one or more inputs with the same name\
                        are already present. Consider deleting those inputs or create the account\
                        without creating new inputs."
                raise admin.ArgValidationException(e)

    def handleRemove(  # pylint: disable=invalid-name, arguments-renamed  # this is UCCs default function hence can't modify it
        self, conf_info
    ) -> None:
        """
        Delete the Intersight account.

        :param conf_info: admin.MConfInfo object containing the configuration information.
        :return: None
        """
        try:
            acc_name = self.callerArgs.id
            logger = setup_logging('ta_intersight_account_deletion', account_name=acc_name)
            logger.info("message=account_deletion_start | Account Deletion started: %s", acc_name)

            # Read the account configuration to get intersight_account_moid before deletion
            acc_moid = None
            try:
                conf_dict = self.readConf("splunk_ta_cisco_intersight_account")
                if acc_name in conf_dict:
                    account_settings = conf_dict[acc_name]
                    acc_moid = account_settings.get("intersight_account_moid")
                    logger.info("message=account_moid_retrieved | Retrieved AccountMoid: %s", acc_moid)
                else:
                    logger.warning("message=account_moid_not_found | Account %s not found in configuration", acc_name)
            except Exception as e:
                logger.warning("message=account_moid_retrieval_error | Failed to retrieve AccountMoid: %s", e)

            # Validate if the account is in use
            if self._is_account_in_use(acc_name, logger):
                raise admin.ArgValidationException(
                    f'Account \"{acc_name}\" cannot be deleted because it is in use by configured inputs.'
                )

            # Proceed with account deletion
            super().handleRemove(conf_info)
            logger.info("message=account_deletion_success | Account Deleted Successfully.")

            # Cleanup KVStore and Checkpoints
            self._cleanup_kvstore_and_checkpoints(acc_name, acc_moid, logger)

        except Exception as e:
            logger.error(
                "message=account_deletion_error | "
                f"Intersight account deletion Error: \"{traceback.format_exc()}\""
            )
            raise admin.ArgValidationException(e)

    def _is_account_in_use(
        self, acc_name: str, logger: logging.Logger
    ) -> bool:
        """
        Check if the account is used by any configured inputs.

        :param acc_name: The name of the account to check.
        :param logger: Logger object for logging.
        :return: True if the account is in use, False otherwise.
        """
        conf_file = get_conf_file(file="inputs", session_key=self.getSessionKey())
        inputs_file = conf_file.get_all(only_current_app=True)

        input_type_list = {"audit_alarms", "inventory", "metrics"}
        input_list = [
            _input.split('://')[1]
            for _input in inputs_file
            if _input.split('://')[0] in input_type_list
            and inputs_file[_input].get('global_account') == acc_name
        ]

        if input_list:
            logger.info(
                f"message=account_in_use | Account '{acc_name}' is used by: {input_list}"
            )
            return True
        return False

    def _cleanup_kvstore_and_checkpoints(
        self, acc_name: str, acc_moid: str, logger: logging.Logger
    ) -> None:
        """
        Clean up KVStore and Checkpoints after account deletion.
        
        Deletes account-related data from:
        1. All inventory collections (static + custom input collections)
        2. Dimension collections (metrics)
        3. Alarm collections
        4. Custom input mapping entries
        5. All checkpoints

        :param acc_name: The name of the account to clean up.
        :param acc_moid: The MOID of the account to clean up.
        :param logger: Logger object for logging.
        :return: None
        """
        session_key = self.getSessionKey()
        kvstore_manager = KVStoreManager(session_key=session_key)

        # Step 1: Get all collection names from inventory mappings (static)
        inventory_collections = set()
        for _, mapping in CollectionConstants.INVENTORY_MAPPINGS.items():
            collection_name = mapping.get("collection")
            if collection_name:
                inventory_collections.add(collection_name)
        
        logger.info(f"Found {len(inventory_collections)} static inventory collections")

        # Step 2: Get custom input collections dynamically
        try:
            mapping_manager = get_mapping_manager(session_key)
            custom_mappings = mapping_manager.get_custom_input_collections()
            
            for _, mapping in custom_mappings.items():
                collection_name = mapping.get("collection")
                if collection_name:
                    inventory_collections.add(collection_name)
            
            logger.info(f"Found {len(custom_mappings)} custom input collections")
        except Exception as e:
            logger.warning(f"Could not load custom input mappings: {e}. Continuing with static collections only.")

        # Step 3: Delete account data from all inventory collections
        deleted_count = 0
        for collection_name in inventory_collections:
            try:
                kvstore_manager.delete_batch(
                    collection_name=collection_name,
                    query={"AccountMoid": acc_moid}
                )
                deleted_count += 1
                logger.debug(f"Deleted data from collection: {collection_name}")
            except Exception as e:
                logger.debug(f"Failed to delete from collection {collection_name}: {e}. Continuing...")

        logger.info(f"Deleted account data from {deleted_count} inventory collections")

        # Step 4: Delete Dimensions Data from KVStore (metrics)
        dimension_collections = []
        dimension_collections.extend(list(MetricsDimensions.inventory_checkpoint_key_24h_apis.keys()))
        dimension_collections.extend(list(MetricsDimensions.inventory_checkpoint_key_1h_apis.keys()))
        
        for collection in dimension_collections:
            try:
                kvstore_manager.delete_batch(
                    collection_name=f"Cisco_Intersight_{collection}",
                    query={"account_name": acc_name}
                )
                logger.debug(f"Deleted dimension data from: Cisco_Intersight_{collection}")
            except Exception as e:
                logger.debug(f"Failed to delete dimension data from {collection}: {e}. Continuing...")

        logger.info(f"Deleted dimension data from {len(dimension_collections)} collections")

        # Step 5: Delete alarm data
        try:
            kvstore_manager.delete_batch(
                collection_name=CollectionConstants.COND_ALARMS,
                query={"account_name": acc_name}
            )
            logger.info("Deleted alarm data from Cisco_Intersight_cond_alarms")
        except Exception as e:
            logger.debug(f"Failed to delete alarm data: {e}. Continuing...")

        logger.info(f"Account '{acc_name}' KVStore data cleaned successfully")

        # Step 6: Delete custom input mapping entries for this account
        try:
            kvstore_manager.delete_batch(
                collection_name=CollectionConstants.CUSTOM_INPUT_MAPPINGS,
                query={"account_name": acc_name}
            )
            logger.info(f"Deleted custom input mapping entries for account '{acc_name}'")
        except Exception as e:
            logger.debug(f"Failed to delete custom input mappings: {e}. Continuing...")

        # Step 7: Delete Checkpoints
        metrics = getattr(MetricsDimensions, "metrics_checkpoints", {}).keys()
        for key in metrics:
            try:
                if key == "fan":
                    checkpoint_key = f"Cisco_Intersight_{acc_name}_{key}_dimension_checkpoint_24h"
                    delete_checkpoint(checkpoint_key, session_key)
                else:
                    checkpoint_key = f"Cisco_Intersight_{acc_name}_{key}_dimension_checkpoint_1h"
                    delete_checkpoint(checkpoint_key, session_key)
            except Exception as e:
                logger.debug(f"Failed to delete checkpoint: {e}. Continuing...")

        logger.info(
            f"message=account_checkpoint_deletion_success | "
            f"Account '{acc_name}' checkpoints cleaned successfully."
        )


special_fields = [
    field.RestField(
        'name',
        required=True,
        encrypted=False,
        default=None,
        validator=validator.AllOf(
            validator.String(
                max_len=50,
                min_len=1,
            ),
            validator.Pattern(
                regex=r"""^[a-zA-Z]\w*$""",
            )
        )
    )
]

fields = [
    field.RestField(
        'intersight_hostname',
        required=True,
        encrypted=False,
        default='intersight.com',
        validator=validator.AllOf(
            validator.String(
                max_len=8192,
                min_len=0,
            ),
            validator.Pattern(
                regex=r"^(?!:\/\/)(?=.{1,255}$)((.{1,63}\.){1,127}(?!\d*$)[a-z\d-]+\.?)$",
            )
        )
    ),
    field.RestField(
        'client_id',
        required=True,
        encrypted=False,
        default=None,
        validator=validator.String(
            max_len=8192,
            min_len=0,
        )
    ),
    field.RestField(
        'client_secret',
        required=True,
        encrypted=True,
        default=None,
        validator=FetchExpirationTime()
    ),
    field.RestField(
        'inputs_created',
        required=False,
        encrypted=False,
        default=None,
        validator=None
    ),
    field.RestField(
        'intersight_account_moid',
        required=False,
        encrypted=False,
        default=None,
        validator=None
    ),
    field.RestField(
        'intersight_account_name',
        required=False,
        encrypted=False,
        default=None,
        validator=None
    )
]
model = RestModel(fields, name=None, special_fields=special_fields)


endpoint = SingleModel(
    'splunk_ta_cisco_intersight_account',
    model,
    config_name='account'
)


if __name__ == '__main__':
    logging.getLogger().addHandler(logging.NullHandler())
    admin_external.handle(
        endpoint,
        handler=IntersightAccountHandler,
    )
