import import_declare_test  # noqa: F401
import splunk.admin as admin
import common.log as log
from common.utils import GetSessionKey, read_conf_file

logger = log.get_logger("cisco_dc_aci_account_fetching_for_ui")


class AciAccounts(admin.MConfigHandler):
    """List ACI accounts."""

    def setup(self):
        """Set up the modular input."""
        pass

    def handleList(self, conf_info):
        """
        Handle the list operation for ACI accounts.

        Called when the user clicks the "List" button on the modular input page.
        This method is overridden from the superclass, and should not be called directly.

        :param conf_info: A dictionary containing the configuration information for the input
        :type conf_info: dict
        """
        logger.info("Fetching ACI accounts for Input page UI")
        session_key = GetSessionKey().session_key

        try:
            logger.info("Reading configuration file for ACI accounts")
            conf_files = read_conf_file(
                session_key, "cisco_dc_networking_app_for_splunk_aci_account"
            )
            created_accounts = list(conf_files.keys())

            logger.info(f"Found {len(created_accounts)} ACI accounts")
            logger.debug(f"ACI accounts: {created_accounts}")

            logger.debug("Adding 'Select All' option to conf_info")
            conf_info[" Select All"]

            for account in created_accounts:
                logger.debug(f"Adding account to conf_info: {account}")
                conf_info[account]

            logger.info("Successfully fetched ACI accounts for Input page UI")

        except Exception as e:
            logger.error(f"{str(e)}")


if __name__ == "__main__":
    """Driving function."""
    admin.init(AciAccounts, admin.CONTEXT_NONE)
