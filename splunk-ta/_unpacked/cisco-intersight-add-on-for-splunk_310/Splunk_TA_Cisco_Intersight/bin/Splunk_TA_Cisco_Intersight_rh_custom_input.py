"""REST handler for Splunk_TA_Cisco_Intersight custom_input."""

import import_declare_test  # noqa: F401  # pylint: disable=unused-import # needed to resolve paths

from splunktaucclib.rest_handler.endpoint import (
    field,
    validator,
    RestModel,
    DataInputModel,
)
from splunktaucclib.rest_handler import admin_external, util
from splunktaucclib.rest_handler.admin_external import AdminExternalHandler
from splunk import admin
import logging
from intersight_helpers.constants import (
    MAX_CUSTOM_INPUTS
)
from intersight_helpers.logger_manager import setup_logging
from intersight_helpers.conf_helper import get_conf_file, delete_checkpoint
import traceback

util.remove_http_proxy_env_vars()


class IntersightCustomInputHandler(AdminExternalHandler):
    """Custom Input Handler class."""

    def __init__(self, *args, **kwargs):
        """Initialize the IntersightCustomInputHandler class."""
        AdminExternalHandler.__init__(self, *args, **kwargs)

    def validate_fields(self, params, logger):
        """
        Custom validation logic for input fields based on api_type.
        """
        api_type = params.get("api_type", [None])[0] if isinstance(
            params.get("api_type"), list
        ) else params.get("api_type")

        # For example: if user selected "normal_inventory"
        if api_type == "normal_inventory":
            required_fields = ["api_endpoint"]
            for f in required_fields:
                val = params.get(f, [None])[0] if isinstance(params.get(f), list) else params.get(f)
                if not val:
                    logger.info(f"Field '{f}' is required.")
                    raise admin.ArgValidationException(f"Field '{f}' is required.")

        elif api_type == "telemetry":
            required_fields = ["api_endpoint", "metrics_name", "metrics_type"]
            for f in required_fields:
                val = params.get(f, [None])[0] if isinstance(params.get(f), list) else params.get(f)
                if not val:
                    logger.info(f"Field '{f}' is required.")
                    raise admin.ArgValidationException(f"Field '{f}' is required.")

    def check_input_count_limit(self, logger):
        """
        Custom input validation to check limit 10 custom inputs.
        """
        try:
            stanzas = get_conf_file(
                file='inputs'
            )
            custom_inputs_count = 0
            input_stanzas = stanzas.get_all(only_current_app=True)
            for stanza_name, _ in input_stanzas.items():
                if stanza_name.strip().startswith("custom_input"):
                    custom_inputs_count += 1
            # Get the MAX_INPUT_LIMIT stanza for Custom input
            conf_stanza = get_conf_file(
                file="splunk_ta_cisco_intersight_settings",
                stanza="custom_input"
            )
            max_input_limit = int(conf_stanza.get("MAX_INPUT_LIMIT", MAX_CUSTOM_INPUTS))
            if custom_inputs_count >= max_input_limit:
                logger.info(
                    f"Reached the maximum of {max_input_limit} custom inputs in the add-on. "
                    "To add another, delete at least one existing custom input."
                )
                raise Exception(
                    f"Reached the maximum of {max_input_limit} custom inputs in the add-on. "
                    "To add another, delete at least one existing custom input."
                )
        except admin.ArgValidationException:
            raise
        except Exception as e:
            raise admin.ArgValidationException(f"Failed to verify existing inputs count: {str(e)}")

    def handleCreate(self, confInfo):  # pylint: disable=invalid-name, arguments-renamed  # this is UCCs default function hence can't modify it
        """
        Runs when a new custom input is created.
        """
        logger = setup_logging('ta_intersight_custom_input_creation')
        self.validate_fields(self.callerArgs.data, logger)
        self.check_input_count_limit(logger)
        super().handleCreate(confInfo)

    def handleEdit(self, confInfo):  # pylint: disable=invalid-name, arguments-renamed  # this is UCCs default function hence can't modify it
        """
        Runs when an existing input is edited.
        """
        logger = setup_logging('ta_intersight_custom_input_creation')
        self.validate_fields(self.callerArgs.data, logger)
        super().handleEdit(confInfo)

    def handleRemove(self, confInfo) -> None:  # pylint: disable=invalid-name, arguments-renamed  # this is UCCs default function hence can't modify it
        """Delete the custom input and cleanup checkpoints and mappings."""
        try:
            input_name = self.callerArgs.id
            logger = setup_logging("ta_intersight_custom_input", input_name=input_name)
            logger.info("message=custom_input_deletion_start | Custom Input deletion started.")

            session_key = self.getSessionKey()

            # Step 1: Delete the input configuration
            super().handleRemove(confInfo)
            logger.info("message=input_deletion_success | Input configuration deleted successfully.")

            # Step 2: Delete checkpoint
            try:
                checkpoint_key = f"Cisco_Intersight_{input_name}_custom_input_checkpoint"
                delete_checkpoint(checkpoint_key, session_key)
                logger.info(
                    "message=custom_input_checkpoint_cleanup | Deleted checkpoint: %s", checkpoint_key
                )
            except Exception as e:
                logger.debug(
                    "message=custom_input_checkpoint_cleanup_error | "
                    "Failed to delete checkpoint: %s. Continuing...", e
                )

            logger.info("message=custom_input_deletion_success | Custom Input deleted successfully.")

        except Exception as e:
            logger.error(f"message=custom_input_deletion_error | Error: {traceback.format_exc()}")
            raise admin.ArgValidationException(e)


special_fields = [
    field.RestField(
        "name",
        required=True,
        encrypted=False,
        default=None,
        validator=validator.AllOf(
            validator.Pattern(regex=r"""^[a-zA-Z]\w*$"""),
            validator.String(max_len=100, min_len=1),
        ),
    )
]

fields = [
    field.RestField("global_account", required=True, encrypted=False, default=None, validator=None),
    field.RestField("interval", required=True, encrypted=False, default=None, validator=None),
    field.RestField(
        "index",
        required=True,
        encrypted=False,
        default="default",
        validator=validator.String(max_len=80, min_len=1),
    ),
    field.RestField(
        "api_type",
        required=True,
        encrypted=False,
        default=None,
        validator=validator.String(max_len=50, min_len=3),
    ),
    field.RestField(
        "api_endpoint",
        required=True,
        encrypted=False,
        default=None,
        validator=validator.String(max_len=200, min_len=1),
    ),
    field.RestField("filter", required=False, encrypted=False, default=None, validator=None),
    field.RestField("expand", required=False, encrypted=False, default=None, validator=None),
    field.RestField("select", required=False, encrypted=False, default=None, validator=None),
    field.RestField("groupby", required=False, encrypted=False, default=None, validator=None),
    field.RestField("metrics_name", required=False, encrypted=False, default=None, validator=None),
    field.RestField("show_metrics_fields", required=False, encrypted=False, default=False, validator=None),
    field.RestField("metrics_type", required=False, encrypted=False, default=None, validator=None),
    # Field names for each metric type (auto-generated, user can edit)
    field.RestField("metrics_sum", required=False, encrypted=False, default=None, validator=None),
    field.RestField("metrics_min", required=False, encrypted=False, default=None, validator=None),
    field.RestField("metrics_max", required=False, encrypted=False, default=None, validator=None),
    field.RestField("metrics_avg", required=False, encrypted=False, default=None, validator=None),
    field.RestField("metrics_latest", required=False, encrypted=False, default=None, validator=None),
    field.RestField("disabled", required=False, validator=None),
]

model = RestModel(fields, name=None, special_fields=special_fields)

endpoint = DataInputModel("custom_input", model)

if __name__ == "__main__":
    logging.getLogger().addHandler(logging.NullHandler())
    admin_external.handle(endpoint, handler=IntersightCustomInputHandler)
