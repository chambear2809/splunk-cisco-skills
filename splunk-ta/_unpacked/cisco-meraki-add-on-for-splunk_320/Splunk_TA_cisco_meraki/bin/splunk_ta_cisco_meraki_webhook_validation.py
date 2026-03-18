from splunktaucclib.rest_handler.endpoint.validator import Validator
import traceback
import cisco_meraki_utils as utils
import splunk.admin as admin
import cisco_meraki_webhook_helper as webhook_helper
import cisco_meraki_exceptions as cme
from copy import deepcopy


class SessionKeyProvider(admin.MConfigHandler):
    """Class to get session key."""

    def __init__(self):
        """Initialize the class."""
        self.session_key = self.getSessionKey()


class HECTokenValidator(Validator):
    """Validator class for HEC token and establish connection to meraki."""

    def __init__(self, *args, **kwargs):
        """Initialize the class."""
        super(HECTokenValidator, self).__init__(*args, **kwargs)

    def validate(self, value, data):
        """Validate HEC token Configured."""
        try:
            session_key = SessionKeyProvider().session_key
            logger = utils.set_logger(session_key, "splunk_ta_cisco_meraki_webhook")
            if not utils.get_hec_token_by_name(session_key, value):
                self.put_msg("Select a valid HEC input stanza.")
                return False

            # logic of create payload and webhook
            data["HEC_webhook_url"] = data["HEC_webhook_url"].strip()
            config = deepcopy(data)
            organization_details = utils.get_organization_details(
                logger, session_key, config["organization_name"]
            )
            config.update(organization_details)
            update_config = {
                "input_name": config["webhook_name"],
                "sourcetype": "meraki:webhook",
                "start_from_days_ago": 0,
                "index": "main",
                "logger": logger,
                "proxies": utils.get_proxy_settings(logger, session_key),
                "top_count": 0,
                "session_key": session_key
            }
            config.update(update_config)
            webhook_object = webhook_helper.HandleWebHook(config)
            payload_template = webhook_object.create_template()
            logger.info("Payload template {} created successfully.".format(payload_template["name"]))
            payload_id = payload_template.get("payloadTemplateId")
            data["payload_id"] = payload_id
            webhook = webhook_object.create_webhook(payload_id)
            if webhook and webhook["id"]:
                data["httpServerId"] = webhook["id"]
                test_webhook = webhook_object.test_webhook(payload_id)
                if test_webhook:
                    logger.info("Webhook connection validated successfully.")
                    return True
                else:
                    webhook_object.delete_webhook(data["httpServerId"])
                    webhook_object.delete_template(payload_id)
            logger.error(
                "Error while validating webhook connection."
                " Please make sure that The URL should be using https and have verified SSL"
                " certificate to receive data from Cisco Meraki."
            )
            self.put_msg(
                "Error while validating webhook connection."
                " Please make sure that The URL should be using https and have verified SSL"
                " certificate to receive data from Cisco Meraki."
            )
            return False
        except cme.TemplateCreationException as e:
            logger.error(
                f"Error occured while creating payload template for the input. {e}."
                f" {traceback.format_exc()}"
            )
            self.put_msg("Error occured while creating payload template for the input.")
            return False
        except cme.WebhookCreationException as e:
            logger.error(
                f"Error occured while creating webhook connection for the input. {e}."
                f" {traceback.format_exc()}"
            )
            self.put_msg("Error occured while creating webhook connection for the input.")
            return False
        except cme.TemplateDeletionException as e:
            logger.error(
                f"Error occured while deleting payload template for the input. {e}."
                f" {traceback.format_exc()}"
            )
            self.put_msg("Error occured while deleting payload template for the input.")
            return False
        except Exception as e:
            logger.error(
                f"Error occured while configuring the input. {e}."
                f" {traceback.format_exc()}"
            )
            self.put_msg("Error occured while configuring the input. Please check the logs.")
            return False
