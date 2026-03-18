"""REST handler for Splunk_TA_Cisco_Intersight metrics input."""
# This import is required to resolve the absolute paths of supportive modules
# implemented throughout the add-on. The relative imports used in other files
# of the add-on are resolved by importing this module.
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
from intersight_helpers.logger_manager import setup_logging
import logging
import traceback
from intersight_helpers.validators import MetricsIntervalValidation
from intersight_helpers.constants import (
    TA_INPUT_VALIDATION
)
from intersight_helpers.conf_helper import (
    delete_checkpoint,
)

util.remove_http_proxy_env_vars()


class IntersightInputMetricsHandler(AdminExternalHandler):
    """Intersight Account Handler class."""

    def __init__(self, *args, **kwargs):
        """Initialize the IntersightInputMetricsHandler class."""
        AdminExternalHandler.__init__(self, *args, **kwargs)

    def handleRemove(  # pylint: disable=invalid-name, arguments-renamed  # this is UCCs default function hence can't modify it
        self, conf_info
    ) -> None:
        """Delete the Intersight input.

        :param conf_info: admin.MConfInfo object containing the configuration information
        :return: None
        """
        try:
            input_name = self.callerArgs.id
            logger = setup_logging(TA_INPUT_VALIDATION, input_name=input_name)
            logger.info("message=input_deletion_start | Input Deletion started.")
            super().handleRemove(conf_info)
            logger.info("message=input_deletion_success | Input Deleted Successfully.")

            # Metric Checkpoint Deletion
            try:
                checkpoint_key = f"Cisco_Intersight_{input_name}_metric_checkpoint"
                delete_checkpoint(
                    checkpoint_key, self.getSessionKey()
                )
            except Exception as e:
                logger.debug("message=input_kvstore_deletion_success | Exception: {}, Continue...".format(e))

            logger.info(
                "message=input_kvstore_deletion_success | Metric Input: {}, Checkpoint Deleted.".format(input_name)
            )

        except Exception as e:
            logger.error(
                f"message=input_deletion_error | "
                f'Intersight input deletion Error occurred \"{traceback.format_exc()}\"'
            )
            raise admin.ArgValidationException(e)


special_fields = [
    field.RestField(
        'name',
        required=True,
        encrypted=False,
        default=None,
        validator=validator.AllOf(
            validator.Pattern(
                regex=r"""^[a-zA-Z]\w*$""",
            ), 
            validator.String(
                max_len=100, 
                min_len=1, 
            )
        )
    )
]

fields = [
    field.RestField(
        'global_account',
        required=True,
        encrypted=False,
        default=None,
        validator=None
    ), 
    field.RestField(
        'interval',
        required=True,
        encrypted=False,
        default=None,
        validator=MetricsIntervalValidation()
    ), 
    field.RestField(
        'index',
        required=True,
        encrypted=False,
        default='default',
        validator=validator.String(
            max_len=80, 
            min_len=1, 
        )
    ), 
    field.RestField(
        'metrics',
        required=True,
        encrypted=False,
        default=None,
        validator=None
    ), 
    field.RestField(
        'host_power_energy_metrics',
        required=False,
        encrypted=False,
        default=None,
        validator=None
    ), 
    field.RestField(
        'memory_metrics',
        required=False,
        encrypted=False,
        default=None,
        validator=None
    ), 
    field.RestField(
        'network_metrics',
        required=False,
        encrypted=False,
        default=None,
        validator=None
    ), 

    field.RestField(
        'disabled',
        required=False,
        validator=None
    )

]
model = RestModel(fields, name=None, special_fields=special_fields)



endpoint = DataInputModel(
    'metrics',
    model,
)


if __name__ == '__main__':
    logging.getLogger().addHandler(logging.NullHandler())
    admin_external.handle(
        endpoint,
        handler=IntersightInputMetricsHandler,
    )
