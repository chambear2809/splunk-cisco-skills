import import_declare_test

from splunktaucclib.rest_handler.endpoint import (
    field,
    validator,
    RestModel,
    SingleModel,
)
from splunktaucclib.rest_handler import admin_external, util
from splunktaucclib.splunk_aoblib.rest_migration import ConfigMigrationHandler
from splunktaucclib.rest_handler.error import RestError
from common.utils import GetSessionKey, read_conf_file
import logging
from cisco_nexus_9k_validation import ValidateNexus9kCreds

util.remove_http_proxy_env_vars()


class AccountHandler(ConfigMigrationHandler):
    """Account Handler."""

    def handleRemove(self, confInfo):
        """Handle the delete operation."""
        try:
            session_key = GetSessionKey().session_key
            inputs_file = read_conf_file(session_key, "inputs")
            created_inputs = list(inputs_file.keys())
            input_list = []
            input_type_list = ["cisco_nexus_9k"]

            for _input in created_inputs:
                nexus_9k_input = _input.split("://")
                if nexus_9k_input[0] in input_type_list:
                    configured_account = inputs_file.get(_input).get("nexus_9k_account")
                    if configured_account:
                        accounts = configured_account.split(",")
                        for acc in accounts:
                            if acc == self.callerArgs.id:
                                input_list.append(nexus_9k_input[1])
                                break

            if input_list:
                raise RestError(
                    500,
                    f'"{self.callerArgs.id}" cannot be deleted because it is in use by the following inputs: {input_list}',
                )
            else:
                super(ConfigMigrationHandler, self).handleRemove(confInfo)
        except Exception as e:
            raise RestError(500, f"An error occurred while deleting account: {e}")


fields = [
    field.RestField(
        'nexus_9k_device_ip',
        required=True,
        encrypted=False,
        default=None,
        validator=None
    ), 
    field.RestField(
        'nexus_9k_port',
        required=True,
        encrypted=False,
        default=None,
        validator=validator.Number(
            max_val=65535,
            min_val=1,
        )
    ),
    field.RestField(
        'nexus_9k_username',
        required=True,
        encrypted=False,
        default=None,
        validator=None
    ),
    field.RestField(
        'nexus_9k_password',
        required=True,
        encrypted=True,
        default=None,
        validator=ValidateNexus9kCreds()
    ),
    field.RestField(
        'nexus_9k_enable_proxy',
        required=False,
        encrypted=False,
        default=0,
        validator=None
    ),
    field.RestField(
        'nexus_9k_proxy_type',
        required=False,
        encrypted=False,
        default=False,
        validator=None
    ),
    field.RestField(
        'nexus_9k_proxy_url',
        required=False,
        encrypted=False,
        default='',
        validator=validator.String(
            max_len=8192,
            min_len=0,
        )
    ),
    field.RestField(
        'nexus_9k_proxy_port',
        required=False,
        encrypted=False,
        default='',
        validator=validator.Number(
            max_val=65535,
            min_val=1,
        )
    ),
    field.RestField(
        'nexus_9k_proxy_username',
        required=False,
        encrypted=False,
        default='',
        validator=validator.String(
            max_len=8192,
            min_len=0,
        )
    ),
    field.RestField(
        'nexus_9k_proxy_password',
        required=False,
        encrypted=True,
        default='',
        validator=validator.String(
            max_len=8192,
            min_len=0,
        )
    )
]
model = RestModel(fields, name=None)


endpoint = SingleModel(
    "cisco_dc_networking_app_for_splunk_nexus_9k_account",
    model,
    config_name="nexus_9k_account",
)


if __name__ == "__main__":
    logging.getLogger().addHandler(logging.NullHandler())
    admin_external.handle(
        endpoint,
        handler=AccountHandler,
    )
