
import import_declare_test

from splunktaucclib.rest_handler.endpoint import (
    field,
    validator,
    RestModel,
    DataInputModel,
)
from splunktaucclib.rest_handler import admin_external, util
from splunktaucclib.rest_handler.admin_external import AdminExternalHandler
import logging

from cisco_nexus_9k_validation import IntervalValidator


util.remove_http_proxy_env_vars()


fields = [
    field.RestField(
        'nexus_9k_account',
        required=True,
        encrypted=False,
        default=None,
        validator=None
    ), 
    field.RestField(
        'interval',
        required=True,
        encrypted=False,
        default='300',
        validator=IntervalValidator()
    ), 
    field.RestField(
        'index',
        required=True,
        encrypted=False,
        default='default',
        validator=validator.AllOf(
            validator.Pattern(
                regex=r"""^[a-zA-Z0-9][a-zA-Z0-9\\_\\-]*$""", 
            ), 
            validator.String(
                max_len=80, 
                min_len=1, 
            )
        )
    ), 
    field.RestField(
        'nexus_9k_input_type',
        required=True,
        encrypted=False,
        default='nexus_9k_cli',
        validator=None,
    ),
    field.RestField(
        'nexus_9k_dme_query_type',
        required=False,
        encrypted=False,
        default='nexus_9k_class',
        validator=None,
    ),
    field.RestField(
        'nexus_9k_cmd',
        required=False,
        encrypted=False,
        default=None,
        validator=None
    ), 
    field.RestField(
        'nexus_9k_component',
        required=False,
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
    ), 
    field.RestField(
        'nexus_9k_class_names',
        required=False,
        encrypted=False,
        default=None,
        validator=None,
    ),
    field.RestField(
        'nexus_9k_distinguished_names',
        required=False,
        encrypted=False,
        default=None,
        validator=None,
    ),
    field.RestField(
        'nexus_9k_additional_parameters',
        required=False,
        encrypted=False,
        default=None,
        validator=None,
    ),

    field.RestField(
        'disabled',
        required=False,
        validator=None
    )

]
model = RestModel(fields, name=None)



endpoint = DataInputModel(
    'cisco_nexus_9k',
    model,
)


if __name__ == '__main__':
    logging.getLogger().addHandler(logging.NullHandler())
    admin_external.handle(
        endpoint,
        handler=AdminExternalHandler,
    )
