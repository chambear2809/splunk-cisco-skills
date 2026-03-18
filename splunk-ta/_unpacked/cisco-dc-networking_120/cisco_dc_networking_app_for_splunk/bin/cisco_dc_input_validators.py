from common.utils import to_seconds


def is_empty(value):
    """
    Check if the given value is empty.

    :param value: The value to check. Can be None, str, or any other type.
    :return: True if the value is empty, False otherwise.
    """
    return value is None or (isinstance(value, str) and not value.strip())


def check_for_advisories_category(input_data, logger):
    """
    Validate if the input data has a valid Advisories Category.

    Args:
        input_data (dict): A dictionary containing the input data to be validated.
        logger: A logger instance used to log error messages and validation results.

    Returns:
        bool: True if the field is valid, False otherwise.
    """
    valid_advisories_categories = [
        "category:PSIRT",
        "category:Field\ Notice",  # noqa: W605
        "category:HWEOL",
        "category:SWEOL",
        "category:Compliance",
        "*",
    ]
    nd_advisories_category = input_data.get("nd_advisories_category")
    if is_empty(nd_advisories_category):
        logger.error(
            "Missing mandatory field 'Advisories Category'. Exiting data collection."
        )
        return False
    categories = [c.strip() for c in nd_advisories_category.split("~")]
    for category in categories:
        if category not in valid_advisories_categories:
            logger.error(
                f"Invalid advisories category '{category}'. Exiting data collection."
            )
            return False
    return True


def check_for_anomalies_category(input_data, logger):
    """
    Validate if the input data has a valid Anomalies Category.

    Args:
        input_data (dict): A dictionary containing the input data to be validated.
        logger: A logger instance used to log error messages and validation results.

    Returns:
        bool: True if the field is valid, False otherwise.
    """
    valid_anomalies_categories = [
        "category:forwarding",
        "category:changeAnalysis",
        "category:endpoint",
        "category:system",
        "category:statistics",
        "category:security",
        "category:Compliance",
        "category:environmental",
        "category:flows",
        "category:utilization",
        "category:staticAnalysis",
        "category:infrastructure",
        "category:adc",
        "category:operator",
        "category:vmm",
        "category:unknown",
        "category:bug",
        "*",
    ]
    nd_anomalies_category = input_data.get("nd_anomalies_category")
    if is_empty(nd_anomalies_category):
        logger.error(
            "Missing mandatory field 'Anomalies Category'. Exiting data collection."
        )
        return False
    categories = [c.strip() for c in nd_anomalies_category.split("~")]
    for category in categories:
        if category not in valid_anomalies_categories:
            logger.error(
                f"Invalid anomalies category '{category}'. Exiting data collection."
            )
            return False
    return True


def check_for_timerange(input_data, logger):
    """
    Validate if the input data has a valid Time Range.

    Args:
        input_data (dict): A dictionary containing the input data to be validated.
        logger: A logger instance used to log error messages and validation results.

    Returns:
        bool: True if the field is valid, False otherwise.
    """
    nd_time_range = input_data.get("nd_time_range")
    if is_empty(nd_time_range):
        logger.error("Missing mandatory field 'Time Range'. Exiting data collection.")
        return False


def check_for_severity(input_data, logger):
    """
    Validate if the input data has a valid Severity.

    Args:
        input_data (dict): A dictionary containing the input data to be validated.
        logger: A logger instance used to log error messages and validation results.

    Returns:
        bool: True if the field is valid, False otherwise.
    """
    nd_severity = input_data.get("nd_severity")
    valid_severities = [
        "severity:warning",
        "severity:major",
        "severity:critical",
        "severity:minor",
        "severity:info",
        "*",
    ]
    if is_empty(nd_severity):
        logger.error("Missing mandatory field 'Severity'. Exiting data collection.")
        return False
    severities = [s.strip() for s in nd_severity.split("~")]
    for severity in severities:
        if severity not in valid_severities:
            logger.error(f"Invalid severity '{severity}'. Exiting data collection.")
            return False
    return True


def aci_input_validator(input_data, logger):
    """
    Validate the input data for ACI configuration.

    Args:
        input_data (dict): A dictionary containing the input data to be validated.
        logger: A logger instance used to log error messages and validation results.

    Raises:
        Exception: Catches any exception that occurs during the validation and logs the error message.
    """
    try:
        # Check for Interval
        interval = input_data.get("interval")
        if is_empty(interval):
            logger.error("Missing mandatory field 'Interval'. Exiting data collection.")
            return False
        interval = int(interval)
        if interval < 60:
            logger.error(
                "Interval must be greater than or equal to 60. Exiting data collection."
            )
            return False

        # Check for Index
        index = input_data.get("index")
        if is_empty(index):
            logger.error("Missing mandatory field 'Index'. Exiting data collection.")
            return False

        # Check for Account
        account = input_data.get("apic_account")
        if is_empty(account):
            logger.error(
                "Missing mandatory field 'APIC account'. Exiting data collection."
            )
            return False

        # Check for Input Type
        apic_input_type = input_data.get("apic_input_type")
        if is_empty(apic_input_type):
            logger.error(
                "Missing mandatory field 'Input Type'. Exiting data collection."
            )
            return False
        if apic_input_type == "managed_objects":
            if not input_data.get("mo_support_object", "").strip():
                logger.error(
                    "Missing mandatory field 'Distinguished Name(s)'. Exiting data collection."
                )
                return False
        else:
            # Check for Class Name(s)
            class_names = input_data.get("apic_arguments")
            if is_empty(class_names):
                logger.error(
                    "Missing mandatory field 'Class Name(s)'. Exiting data collection."
                )
                return False
        return True
    except Exception as err:
        logger.error(
            f"Error in validating input fields. Exiting data collection. Error: {str(err)}"
        )
        return False


def nd_input_validator(input_data, logger):
    """
    Validate the input data for ACI configuration.

    Args:
        input_data (dict): A dictionary containing the input data to be validated.
        logger: A logger instance used to log error messages and validation results.

    Raises:
        Exception: Catches any exception that occurs during the validation and logs the error message.
    """
    try:
        # Check for Interval
        interval = input_data.get("interval")
        if is_empty(interval):
            logger.error("Missing mandatory field 'Interval'. Exiting data collection.")
            return False
        interval = int(interval)
        if interval < 60:
            logger.error(
                "Interval must be greater than or equal to 60. Exiting data collection."
            )
            return False

        # Check for Index
        index = input_data.get("index")
        if is_empty(index):
            logger.error("Missing mandatory field 'Index'. Exiting data collection.")
            return False

        # Check for Account
        account = input_data.get("nd_account")
        if is_empty(account):
            logger.error(
                "Missing mandatory field 'ND account'. Exiting data collection."
            )
            return False

        # Check for Alert Type
        nd_alert_type = input_data.get("nd_alert_type")
        if is_empty(nd_alert_type):
            logger.error(
                "Missing mandatory field 'Alert Type'. Exiting data collection."
            )
            return False

        if nd_alert_type == "anomalies":
            # Check for Anomalies Category
            if check_for_anomalies_category(input_data, logger) is False:
                return False

            # Check for Time Range
            if check_for_timerange(input_data, logger) is False:
                return False

            # Check for Severity
            if check_for_severity(input_data, logger) is False:
                return False

        elif nd_alert_type == "advisories":
            # Check for Advisories Category
            if check_for_advisories_category(input_data, logger) is False:
                return False

            # Check for Time Range
            if check_for_timerange(input_data, logger) is False:
                return False

            # Check for Severity
            if check_for_severity(input_data, logger) is False:
                return False

        elif nd_alert_type == "congestion":
            nd_protocol_site_name = input_data.get("nd_protocol_site_name")
            nd_node_name = input_data.get("nd_node_name")
            nd_interface_name = input_data.get("nd_interface_name")
            interval = input_data.get("interval")
            nd_granularity = input_data.get("nd_granularity")

            if is_empty(nd_protocol_site_name):
                logger.error("Missing mandatory field 'Fabric Name'. Exiting data collection.")
                return False
            if is_empty(nd_node_name):
                logger.error("Missing mandatory field 'Node Name'. Exiting data collection.")
                return False
            if is_empty(nd_interface_name):
                logger.error("Missing mandatory field 'Interface Name'. Exiting data collection.")
                return False
            if nd_granularity and to_seconds(nd_granularity) > int(interval):
                logger.error("'Granularity' should be less than or equal to 'Interval'.")
                return False

        elif nd_alert_type == "endpoints":
            nd_protocol_site_name = input_data.get("nd_protocol_site_name")
            nd_start_date = input_data.get("nd_start_date")
            if is_empty(nd_protocol_site_name):
                logger.error("Missing mandatory field 'Fabric Name'. Exiting data collection.")
                return False
            if is_empty(nd_start_date):
                logger.error("Missing mandatory field 'Time Range'. Exiting data collection.")
                return False

        elif nd_alert_type == "flows":
            nd_protocol_site_name = input_data.get("nd_protocol_site_name")
            nd_start_date = input_data.get("nd_flow_start_date")
            if is_empty(nd_protocol_site_name):
                logger.error("Missing mandatory field 'Fabric Name'. Exiting data collection.")
                return False
            if is_empty(nd_start_date):
                logger.error("Missing mandatory field 'Time Range'. Exiting data collection.")
                return False

            nd_time_interval = input_data.get("interval")
            nd_time_slice = input_data.get("nd_time_slice")
            if nd_time_slice is not None and int(nd_time_interval) / int(nd_time_slice) > 500:
                logger.error(
                    "Too many threads would be created. Limiting to 500."
                )
                return False

        elif nd_alert_type == "protocols":
            nd_start_date = input_data.get("nd_start_date")
            if is_empty(nd_start_date):
                logger.error("Missing mandatory field 'Time Range'. Exiting data collection.")
                return False

        elif nd_alert_type == "fabrics":
            nd_start_date = input_data.get("nd_start_date")
            if is_empty(nd_start_date):
                logger.error("Missing mandatory field 'Time Range'. Exiting data collection.")
                return False

        elif nd_alert_type == "switches":
            nd_start_date = input_data.get("nd_start_date")
            if is_empty(nd_start_date):
                logger.error("Missing mandatory field 'Time Range'. Exiting data collection.")
                return False

        elif nd_alert_type == "custom":
            custom_endpoint = input_data.get("custom_endpoint")
            custom_srctype = input_data.get("custom_sourcetype")
            if custom_endpoint is None or not custom_endpoint.strip():
                logger.error(
                    "Missing mandatory field 'Custom Endpoint'. Exiting data collection."
                )
                return False

            if custom_srctype is None or not custom_srctype.strip():
                logger.error(
                    "Missing mandatory field 'Sourcetype'. Exiting data collection."
                )
                return False

        else:
            # Check for Orchestrator Arguments
            orchestrator_arguments = input_data.get("orchestrator_arguments")
            if is_empty(orchestrator_arguments):
                logger.error(
                    "Missing mandatory field 'Orchestrator Arguments'. Exiting data collection."
                )
                return False

        return True
    except Exception as err:
        logger.error(
            f"Error in validating input fields. Exiting data collection. Error: {str(err)}"
        )
        return False


def nexus9k_input_validator(input_data, logger):
    """
    Validate the input data for Nexus 9k configuration.

    Args:
        input_data (dict): A dictionary containing the input data to be validated.
        logger: A logger instance used to log error messages and validation results.

    Raises:
        Exception: Catches any exception that occurs during the validation and logs the error message.
    """
    try:
        # Check for Interval
        interval = input_data.get("interval")
        if is_empty(interval):
            logger.error("Missing mandatory field 'Interval'. Exiting data collection.")
            return False
        interval = int(interval)
        if interval < 60:
            logger.error(
                "Interval must be greater than or equal to 60. Exiting data collection."
            )
            return False

        # Check for Index
        index = input_data.get("index")
        if is_empty(index):
            logger.error("Missing mandatory field 'Index'. Exiting data collection.")
            return False

        # Check for Account
        account = input_data.get("nexus_9k_account")
        if is_empty(account):
            logger.error(
                "Missing mandatory field 'Nexus 9K account'. Exiting data collection."
            )
            return False

        nexus_9k_input_type = input_data.get("nexus_9k_input_type")
        if is_empty(nexus_9k_input_type):
            logger.error(
                "Missing mandatory field 'Input Type'. Exiting data collection."
            )
            return False

        if nexus_9k_input_type == "nexus_9k_cli":
            # Check for Component and command
            nexus_9k_component = input_data.get("nexus_9k_component")
            if is_empty(nexus_9k_component):
                logger.error(
                    "Missing mandatory field 'Component'. Exiting data collection."
                )
                return False

            nexus_9k_cmd = input_data.get("nexus_9k_cmd")
            if is_empty(nexus_9k_cmd):
                logger.error(
                    "Missing mandatory field 'Command'. Exiting data collection."
                )
                return False

        else:
            nexus_9k_dme_query_type = input_data.get("nexus_9k_dme_query_type")
            if is_empty(nexus_9k_dme_query_type):
                logger.error(
                    "Missing mandatory field 'DME Query Type'. Exiting data collection."
                )
                return False
            if nexus_9k_dme_query_type == "nexus_9k_class":
                nexus_9k_class_names = input_data.get("nexus_9k_class_names")
                if is_empty(nexus_9k_class_names):
                    logger.error(
                        "Missing mandatory field 'Class Name(s)'. Exiting data collection."
                    )
                    return False
            else:
                nexus_9k_distinguished_names = input_data.get(
                    "nexus_9k_distinguished_names"
                )
                if (
                    nexus_9k_distinguished_names is None
                    or not nexus_9k_distinguished_names.strip()
                ):
                    logger.error(
                        "Missing mandatory field 'Distinguished Name(s)'. Exiting data collection."
                    )
                    return False

        return True
    except Exception as err:
        logger.error(
            f"Error in validating input fields. Exiting data collection. Error: {str(err)}"
        )
        return False
