import { defaultFieldsMapND } from "./nd_default_fields.js";
import FieldEnum from "./nd_field_enum.js";

const isEmpty = (value) => {
  return (
    value === null ||
    value === undefined ||
    (typeof value === "string" && value.trim().length === 0)
  );
};

// Resets values of specified fields
export const resetFieldValues = (data, fields) => {
  fields.forEach((field) => {
    if (data[field]) {
      data[field].value = "";
    }
  });
};

// Returns the list of fields to reset for each alert type
export const getDefaultFields = (alertType) => {
  // Get default fields list based on alert type
  const defaultFields = defaultFieldsMapND[alertType];

  // Return the list if found, otherwise return an empty array
  return defaultFields || [];
};

export const validateRequiredFields = (fields, data, util) => {
  for (const field of fields) {
    if (isEmpty(data[field])) {
      util.setErrorMsg(`Field ${getFieldLabel(field)} is required`);
      return false;
    }
  }
  return true;
};

export const getFieldLabel = (field) => {
  const fieldLabels = {
    nd_anomalies_category: "Anomalies Category",
    nd_advisories_category: "Advisories Category",
    nd_time_range: "Time Range",
    nd_severity: "Severity",
    nd_node_name: "Node Name",
    nd_interface_name: "Interface Name",
    nd_additional_filter: "Filter",
    nd_scope: "Scope",
    nd_time_slice: "Time Slice",
    orchestrator_arguments: "Class Name(s)",
    nd_protocol_site_name: "Fabric Name",
    custom_endpoint: "Custom Endpoint",
    nd_additional_parameters: "Additional Query Parameters",
    custom_sourcetype: "Sourcetype",
    custom_resp_key: "Ingestion Key",
    nd_start_date: "Time Range",
    nd_granularity: "Granularity",
    nd_flow_start_date: "Time Range",
  };
  return fieldLabels[field] || field;
};

export const getRequiredFields = (alertType) => {
  switch (alertType) {
    case "anomalies":
      return [
        FieldEnum.ND_ANOMALIES_CATEGORY,
        FieldEnum.ND_TIME_RANGE,
        FieldEnum.ND_SEVERITY,
      ];
    case "advisories":
      return [
        FieldEnum.ND_ADVISORIES_CATEGORY,
        FieldEnum.ND_TIME_RANGE,
        FieldEnum.ND_SEVERITY,
      ];
    case "congestion":
      return [
        FieldEnum.ND_PROTOCOL_SITE_NAME,
        FieldEnum.ND_NODE_NAME,
        FieldEnum.ND_INTERFACE_NAME,
      ];
    case "endpoints":
      return [
        FieldEnum.ND_PROTOCOL_SITE_NAME,
        FieldEnum.ND_START_DATE,
      ];
    case "flows":
      return [
        FieldEnum.ND_PROTOCOL_SITE_NAME,
        FieldEnum.ND_FLOW_START_DATE,
      ];
    case "protocols":
      return [FieldEnum.ND_START_DATE];
    case "Orchestrator":
      return [FieldEnum.ORCHESTRATOR_ARGUMENTS];
    case "fabrics":
      return [FieldEnum.ND_START_DATE];
    case "switches":
      return [FieldEnum.ND_START_DATE];
    case "custom":
      return [
        FieldEnum.CUSTOM_ENDPOINT,
        FieldEnum.CUSTOM_SOURCETYPE
      ];
    default:
      return [];
  }
};

export const validateAlertTypeFields = (nd_alert_type, data, util) => {
  const requiredFields = getRequiredFields(nd_alert_type);
  return validateRequiredFields(requiredFields, data, util);
};
