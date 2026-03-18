import import_declare_test  # noqa: F401 # isort: skip

import sys
from splunklib import modularinput as smi


class Webhook(smi.Script):
    """Webhook modular input class."""

    def __init__(self):
        """Initialize the class."""
        super().__init__()

    def get_scheme(self):
        """Overloaded splunklib modularinput method."""
        scheme = smi.Scheme("webhook")
        scheme.description = "webhook input"
        scheme.use_external_validation = True
        scheme.streaming_mode_xml = True
        scheme.use_single_instance = False
        scheme.add_argument(
            smi.Argument(
                "name", title="Name", description="Name", required_on_create=True
            )
        )
        scheme.add_argument(smi.Argument("webhook_name", title="Webhook Name",
                                         description="",
                                         required_on_create=True,
                                         required_on_edit=False))
        scheme.add_argument(smi.Argument("organization_name", title="Organization",
                                         description="",
                                         required_on_create=True,
                                         required_on_edit=False))
        scheme.add_argument(smi.Argument("network_id", title="Network Id",
                                         description="",
                                         required_on_create=True,
                                         required_on_edit=False))
        scheme.add_argument(smi.Argument("hec_token", title="HEC Input",
                                         description="",
                                         required_on_create=True,
                                         required_on_edit=False))
        scheme.add_argument(smi.Argument("HEC_webhook_url", title="Splunk URL with HEC port",
                                         description="",
                                         required_on_create=True,
                                         required_on_edit=False))
        return scheme

    def validate_input(self, definition: smi.ValidationDefinition):
        """Validate the input stanza."""
        pass

    def stream_events(self, inputs: smi.InputDefinition, event_writer: smi.EventWriter):
        """Write out the events."""
        pass


if __name__ == "__main__":
    exit_code = Webhook().run(sys.argv)
    sys.exit(exit_code)
