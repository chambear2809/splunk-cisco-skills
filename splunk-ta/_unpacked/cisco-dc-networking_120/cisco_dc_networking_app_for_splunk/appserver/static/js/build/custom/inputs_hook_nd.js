var nd_account_list = []

require([
    'splunkjs/mvc',
    'splunkjs/mvc/utils',
    'splunkjs/mvc/tokenutils',
    'underscore',
    'jquery',
], function(mvc) {
    mvc.createService().get("/servicesNS/nobody/cisco_dc_networking_app_for_splunk/configs/conf-cisco_dc_networking_app_for_splunk_nd_account", {}, function(err, response) {
        if (response && response.data && response.data.entry && Array.isArray(response.data.entry)) {
            let nameList = response.data.entry.map(entry => entry.name);
            nd_account_list = nameList;
        }
    });
});

import {
  resetFieldValues,
  getDefaultFields,
  validateAlertTypeFields,
} from "./nd_input_field_utils.js";
import { fieldDisplayConfigND, fieldDefaultValueND } from "./nd_default_fields.js";
import FieldEnum from "./nd_field_enum.js";

// Always show specific fields regardless of alertType
const alwaysVisibleFields = [
  FieldEnum.NAME,
  FieldEnum.ND_ACCOUNT,
  FieldEnum.INTERVAL,
  FieldEnum.INDEX,
  FieldEnum.ND_ALERT_TYPE,
];

class InputsHook {
  constructor(globalConfig, serviceName, state, mode, util) {
    this.globalConfig = globalConfig;
    this.serviceName = serviceName;
    this.state = state;
    this.mode = mode;
    this.util = util;
  }

  isEmpty(value) {
    return (
      value === null ||
      value === undefined ||
      (typeof value === "string" && value.trim().length === 0)
    );
  }

  isTrue(val) {
    if (val === null || val === undefined) {
      return false;
    }
    let value = String(val).trim().toUpperCase();
    if (value === "1" || value === "TRUE") {
      return true;
    }
    return false;
  }

  updateStateBasedOnAlertType(alertType, data) {
    const fieldConfig = fieldDisplayConfigND[alertType];
    const newData = { ...data };

    // Reset all fields to default first
    Object.keys(newData).forEach((key) => {
      if (newData[key]) {
        newData[key].display = false;
      }
    });

    alwaysVisibleFields.forEach((field) => {
      if (newData[field]) {
        newData[field].display = true;
      }
    });

    // Iterate through the field config and update display & value
    fieldConfig.forEach(({ field, display, value }) => {
      if (newData[field]) {
        if (display) {
          newData[field].display = display;
        }
        if (
          newData[field].value === undefined ||
          newData[field].value === null ||
          (newData[field].value === "" && !newData[field]?.modified)
        ) {
          if (value) {
            newData[field].value = value;
          }
        }
      }
    });

    return newData;
  }

  onCreate() {
    this.onChange(null, null, this.state);
  }

  onChange(field, value, newState) {
    if (newState.data && newState.data.nd_alert_type) {
      this.util.setState((prevState) => {
        let data = this.updateStateBasedOnAlertType(
          newState.data.nd_alert_type.value,
          prevState.data
        );

        data = {
          ...data,
          ...newState.data,
        };

        if (!data[field]) {
          data[field] = {};
        }
        data[field].value = value;
        data[field].modified = true;

        return { data };
      });
    }

    if (field === FieldEnum.ND_ANOMALIES_CATEGORY) {
      this.util.setState((prevState) => {
        let data = {
          ...prevState.data,
        };
        var newValue =
          newState.data && newState.data[FieldEnum.ND_ANOMALIES_CATEGORY]
            ? newState.data[FieldEnum.ND_ANOMALIES_CATEGORY].value
            : "";
        if (newValue.startsWith("*~")) {
          newValue = newValue.substr(2);
        }
        if (newValue.endsWith("~*")) {
          newValue = "*";
        }
        if (data.nd_anomalies_category)
          data.nd_anomalies_category.value = newValue;
        return {
          data,
        };
      });
    } else if (field === FieldEnum.ND_ADVISORIES_CATEGORY) {
      this.util.setState((prevState) => {
        let data = {
          ...prevState.data,
        };
        var newValue =
          newState.data && newState.data[FieldEnum.ND_ADVISORIES_CATEGORY]
            ? newState.data[FieldEnum.ND_ADVISORIES_CATEGORY].value
            : "";
        if (newValue.startsWith("*~")) {
          newValue = newValue.substr(2);
        }
        if (newValue.endsWith("~*")) {
          newValue = "*";
        }
        if (data.nd_advisories_category)
          data.nd_advisories_category.value = newValue;
        return {
          data,
        };
      });
    }

    if (field === FieldEnum.ND_SEVERITY) {
      this.util.setState((prevState) => {
        let data = {
          ...prevState.data,
        };
        var newValue =
          newState.data && newState.data[FieldEnum.ND_SEVERITY]
            ? newState.data[FieldEnum.ND_SEVERITY].value
            : "";
        if (newValue.startsWith("*~")) {
          newValue = newValue.substr(2);
        }
        if (newValue.endsWith("~*")) {
          newValue = "*";
        }
        if (data.nd_severity) data.nd_severity.value = newValue;
        return {
          data,
        };
      });
    }
    if (field === FieldEnum.ND_ALERT_TYPE) {
      this.util.setState((prevState) => {
        let data = { ...prevState.data };
        
        fieldDefaultValueND.defaultvalue.forEach((fieldDefault) => {
          if (data[fieldDefault.field]) 
            data[fieldDefault.field].value = fieldDefault.value;
        });
        
        return { data };
      });
    }
    if (newState.data && newState.data.nd_account && newState.data.nd_account.value) {
      let accountValues = [];
      if (newState.data.nd_account.value) {
          if (typeof newState.data.nd_account.value === 'string') {
              accountValues = newState.data.nd_account.value.split(',');
          } else if (Array.isArray(newState.data.nd_account.value)) {
              accountValues = newState.data.nd_account.value;
          } else if (typeof newState.data.nd_account.value === 'object') {
              accountValues = Object.keys(newState.data.nd_account.value);
          }
      }
      const isSelectAll = accountValues.includes(" Select All");
      this.util.setState((prevState) => {
          let data = {
              ...prevState.data
          };
          if (data.nd_account) {
              if (isSelectAll) {
                  data.nd_account.value = nd_account_list.filter(account => account !== " Select All");
              } else {
                  data.nd_account.value = accountValues;
              }
          }
          return {
              data
          }
      });
  }
  }
  onSave(dataDict) {
    const nd_alert_type = dataDict.nd_alert_type;

    this.util.setState((prevState) => {
      let data = { ...prevState.data };

      // Get default fields and reset them
      const fieldsToReset = getDefaultFields(nd_alert_type);
      resetFieldValues(data, fieldsToReset);

      return { data };
    });
    return validateAlertTypeFields(nd_alert_type, dataDict, this.util);
  }
}

export default InputsHook;
