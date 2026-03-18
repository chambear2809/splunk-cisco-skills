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
from cisco_nexus_aci_validation import (
    HostsValidator,
    AuthenticationValidator,
    CertificateValidator,
)

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
            input_type_list = ["cisco_nexus_aci"]

            for _input in created_inputs:
                aci_input = _input.split("://")
                if aci_input[0] in input_type_list:
                    configured_account = inputs_file.get(_input).get("apic_account")
                    if configured_account:
                        accounts = configured_account.split(",")
                        for acc in accounts:
                            if acc == self.callerArgs.id:
                                input_list.append(aci_input[1])
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
        'apic_hostname',
        required=True,
        encrypted=False,
        default=None,
        validator=HostsValidator()
    ),
    field.RestField(
        'apic_port',
        required=True,
        encrypted=False,
        default=None,
        validator=None
    ),
    field.RestField(
        'apic_authentication_type',
        required=True,
        encrypted=False,
        default='password_authentication',
        validator=AuthenticationValidator()
    ),
    field.RestField(
        'apic_login_domain',
        required=False,
        encrypted=False,
        default=None,
        validator=validator.String(
            max_len=200,
            min_len=1,
        )
    ),
    field.RestField(
        'apic_username',
        required=False,
        encrypted=False,
        default=None,
        validator=validator.String(
            max_len=200,
            min_len=1,
        )
    ),
    field.RestField(
        'apic_password',
        required=False,
        encrypted=True,
        default=None,
        validator=validator.String(
            max_len=8192,
            min_len=1,
        )
    ),
    field.RestField(
        'apic_certificate_name',
        required=False,
        encrypted=False,
        default=None,
        validator=validator.String(
            max_len=200,
            min_len=1,
        )
    ),
    field.RestField(
        'apic_certificate_path',
        required=False,
        encrypted=False,
        default=None,
        validator=CertificateValidator()
    ),
    field.RestField(
        'apic_proxy_enabled',
        required=False,
        encrypted=False,
        default=0,
        validator=None
    ),
    field.RestField(
        'apic_proxy_type',
        required=False,
        encrypted=False,
        default=False,
        validator=None
    ),
    field.RestField(
        'apic_proxy_url',
        required=False,
        encrypted=False,
        default=None,
        validator=validator.String(
            max_len=8192,
            min_len=0,
        )
    ),
    field.RestField(
        'apic_proxy_port',
        required=False,
        encrypted=False,
        default='',
        validator=validator.Number(
            max_val=65535,
            min_val=1,
        )
    ),
    field.RestField(
        'apic_proxy_username',
        required=False,
        encrypted=False,
        default=None,
        validator=validator.String(
            max_len=8192,
            min_len=0,
        )
    ),
    field.RestField(
        'apic_proxy_password',
        required=False,
        encrypted=True,
        default=None,
        validator=validator.String(
            max_len=8192,
            min_len=0,
        )
    )
]
model = RestModel(fields, name=None)

endpoint = SingleModel(
    "cisco_dc_networking_app_for_splunk_aci_account", model, config_name="aci_account"
)

if __name__ == "__main__":
    logging.getLogger().addHandler(logging.NullHandler())
    admin_external.handle(
        endpoint,
        handler=AccountHandler,
    )
