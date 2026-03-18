# logic of webhook creation and deltion

import cisco_meraki_connect as connect
import cisco_meraki_utils as utils
import time
import cisco_meraki_exceptions as cme


class HandleWebHook:
    """Helper class for webhook operations."""

    def __init__(self, config):
        """Initialize the webhook helper."""
        self.config = config
        logfile_prefix = "splunk_ta_cisco_meraki_webhook_"
        logfile_name = logfile_prefix + self.config["webhook_name"]
        self.logger = utils.set_logger(config["session_key"], logfile_name)

    def create_template(self):
        """Create webhook payload template."""
        try:
            api = connect.MerakiConnect(self.config)
            return api.create_payload_template()

        except Exception as e:
            raise cme.TemplateCreationException("Error while creating payload template. {}".format(e))

    def delete_template(self, payload_id):
        """Delete webhook payload template."""
        try:
            api = connect.MerakiConnect(self.config)
            return api.delete_payload_template(payload_id)

        except Exception as e:
            raise cme.TemplateDeletionException("Error while deleting payload template. {}".format(e))

    def create_webhook(self, payload_id):
        """Create webhook HTTP server."""
        try:
            api = connect.MerakiConnect(self.config)
            return api.create_webhook_http_server(payload_id)

        except Exception as e:
            self.delete_template(payload_id)
            self.logger.info("Deleted payload template.")
            raise cme.WebhookCreationException("Error while creating webhook connection. {}".format(e))

    def delete_webhook(self, webhook_id):
        """Delete webhook HTTP server."""
        try:
            api = connect.MerakiConnect(self.config)
            return api.delete_webhook_http_server(webhook_id)

        except Exception as e:
            raise cme.WebhookDeletionException("Error while deleting webhook connection. {}".format(e))

    def test_webhook(self, payload_id):
        """Test webhook connection."""
        try:
            api = connect.MerakiConnect(self.config)
            create_webhook = api.create_webhook_test(payload_id)
            test_id = create_webhook["id"]
            time.sleep(5)
            check_status = api.check_status_test(test_id)
            while check_status["status"] == "enqueued":
                time.sleep(5)
                check_status = api.check_status_test(test_id)
            if check_status["status"] == "delivered":
                return True
            else:
                self.logger.info(
                    "Validation of webhook connection failed."
                    " Status: {}".format(check_status["status"])
                )
                return False

        except Exception as e:
            raise cme.WebhookCreationException("Error while creating webhook connection. {}".format(e))
