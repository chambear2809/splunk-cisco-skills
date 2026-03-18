var nexus_9k_account_list = []

require([
    'splunkjs/mvc',
    'splunkjs/mvc/utils',
    'splunkjs/mvc/tokenutils',
    'underscore',
    'jquery',
], function(mvc) {
    mvc.createService().get("/servicesNS/nobody/cisco_dc_networking_app_for_splunk/configs/conf-cisco_dc_networking_app_for_splunk_nexus_9k_account", {}, function(err, response) {
        if (response && response.data && response.data.entry && Array.isArray(response.data.entry)) {
            let nameList = response.data.entry.map(entry => entry.name);
            nexus_9k_account_list = nameList;
        }
    });
});

class InputsHook {
    constructor(globalConfig, serviceName, state, mode, util) {
        this.globalConfig = globalConfig;
        this.serviceName = serviceName;
        this.state = state;
        this.mode = mode;
        this.util = util;
    }

    isEmpty(value) {
        return value === null || value === undefined || (typeof value === "string" && value.trim().length === 0);
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

    onCreate() {
        this.onChange(null, null, this.state);
    }

    onChange(field, value, newState) {
        if (field === "nexus_9k_cmd") {
            this.util.setState((prevState) => {
                let data = {
                    ...prevState.data
                };
                var newValue = newState.data && newState.data["nexus_9k_cmd"] ? newState.data["nexus_9k_cmd"].value : "";
                if (newValue.startsWith("*|")) {
                    newValue = newValue.substr(2);
                }
                if (newValue.endsWith("|*")) {
                    newValue = "*";
                }
                if (data.nexus_9k_cmd) data.nexus_9k_cmd.value = newValue;
                return {
                    data
                };
            });
        }
        if (newState.data && newState.data.nexus_9k_input_type && newState.data.nexus_9k_input_type.value === "nexus_9k_cli") {
            this.util.setState((prevState) => {
                let data = {
                    ...prevState.data
                };
                if (data.nexus_9k_component) data.nexus_9k_component.display = true;
                if (data.nexus_9k_cmd) data.nexus_9k_cmd.display = true;
                if (data.nexus_9k_class_names) data.nexus_9k_class_names.display = false;
                if (data.nexus_9k_dme_query_type) data.nexus_9k_dme_query_type.display = false;
                if (data.nexus_9k_additional_parameters) data.nexus_9k_additional_parameters.display = false;
                if (data.nexus_9k_distinguished_names) data.nexus_9k_distinguished_names.display = false;
                return {
                    data
                }
            });
        } else {
            if(newState.data && newState.data.nexus_9k_dme_query_type && newState.data.nexus_9k_dme_query_type.value === "nexus_9k_class"){
                this.util.setState((prevState) => {
                    let data = {
                        ...prevState.data
                    };
                    if (data.nexus_9k_component) data.nexus_9k_component.display = false;
                    if (data.nexus_9k_cmd) data.nexus_9k_cmd.display = false;
                    if (data.nexus_9k_class_names) data.nexus_9k_class_names.display = true;
                    if (data.nexus_9k_dme_query_type) data.nexus_9k_dme_query_type.display = true;
                    if (data.nexus_9k_distinguished_names) data.nexus_9k_distinguished_names.display = false;
                    if (data.nexus_9k_additional_parameters) data.nexus_9k_additional_parameters.display = true;
                    return {
                        data
                    }
                });
            }
            else{
                this.util.setState((prevState) => {
                    let data = {
                        ...prevState.data
                    };
                    if (data.nexus_9k_component) data.nexus_9k_component.display = false;
                    if (data.nexus_9k_cmd) data.nexus_9k_cmd.display = false;
                    if (data.nexus_9k_distinguished_names) data.nexus_9k_distinguished_names.display = true;
                    if (data.nexus_9k_dme_query_type) data.nexus_9k_dme_query_type.display = true;
                    if (data.nexus_9k_class_names) data.nexus_9k_class_names.display = false;
                    if (data.nexus_9k_additional_parameters) data.nexus_9k_additional_parameters.display = true;
                    return {
                        data
                    }
                });
            }
        }
        if(field === "nexus_9k_input_type"){
            this.util.setState((prevState) => {
                let data = {
                    ...prevState.data
                };
                if (data.nexus_9k_component) data.nexus_9k_component.value = "";
                if (data.nexus_9k_cmd) data.nexus_9k_cmd.value = "";
                if (data.nexus_9k_class_names) data.nexus_9k_class_names.value = "";
                if (data.nexus_9k_dme_query_type) data.nexus_9k_dme_query_type.value = "nexus_9k_class";
                if (data.nexus_9k_additional_parameters) data.nexus_9k_additional_parameters.value = "";
                if (data.nexus_9k_distinguished_names) data.nexus_9k_distinguished_names.value = "";
                return {
                    data
                }
            });
        }
        if(field === "nexus_9k_dme_query_type"){
            this.util.setState((prevState) => {
                let data = {
                    ...prevState.data
                };
                if (data.nexus_9k_class_names) data.nexus_9k_class_names.value = "";
                if (data.nexus_9k_additional_parameters) data.nexus_9k_additional_parameters.value = "";
                if (data.nexus_9k_distinguished_names) data.nexus_9k_distinguished_names.value = "";
                return {
                    data
                }
            });
        }
        if (newState.data && newState.data.nexus_9k_account && newState.data.nexus_9k_account.value) {
            let accountValues = [];
            if (newState.data.nexus_9k_account.value) {
                if (typeof newState.data.nexus_9k_account.value === 'string') {
                    accountValues = newState.data.nexus_9k_account.value.split(',');
                } else if (Array.isArray(newState.data.nexus_9k_account.value)) {
                    accountValues = newState.data.nexus_9k_account.value;
                } else if (typeof newState.data.nexus_9k_account.value === 'object') {
                    accountValues = Object.keys(newState.data.nexus_9k_account.value);
                }
            }
            const isSelectAll = accountValues.includes(" Select All");
            this.util.setState((prevState) => {
                let data = {
                    ...prevState.data
                };
                if (data.nexus_9k_account) {
                    if (isSelectAll) {
                        data.nexus_9k_account.value = nexus_9k_account_list.filter(account => account !== " Select All");
                    } else {
                        data.nexus_9k_account.value = accountValues;
                    }
                }
                return {
                    data
                }
            });
        }
    }

    onSave(dataDict) {
        const nexus_9k_input_type = dataDict.nexus_9k_input_type;
        const nexus_9k_component = dataDict.nexus_9k_component;
        const nexus_9k_cmd = dataDict.nexus_9k_cmd;
        const nexus_9k_class_names = dataDict.nexus_9k_class_names;
        const nexus_9k_dme_query_type = dataDict.nexus_9k_dme_query_type;
        const nexus_9k_distinguished_names = dataDict.nexus_9k_distinguished_names;

        if (nexus_9k_input_type && nexus_9k_input_type === "nexus_9k_cli") {
            this.util.setState((prevState) => {
                let data = {
                    ...prevState.data
                };
                if (data.nexus_9k_class_names) data.nexus_9k_class_names.value = '';
                if (data.nexus_9k_dme_query_type) data.nexus_9k_dme_query_type.value = '';
                if (data.nexus_9k_additional_parameters) data.nexus_9k_additional_parameters.value = '';
                if (data.nexus_9k_distinguished_names) data.nexus_9k_distinguished_names.value = '';
                return {
                    data
                }
            });
        } else {
            if (nexus_9k_dme_query_type && nexus_9k_dme_query_type === "nexus_9k_class") {
                this.util.setState((prevState) => {
                    let data = {
                        ...prevState.data
                    };
                    if (data.nexus_9k_component) data.nexus_9k_component.value = '';
                    if (data.nexus_9k_cmd) data.nexus_9k_cmd.value = '';
                    if (data.nexus_9k_distinguished_names) data.nexus_9k_distinguished_names.value = '';
                    return {
                        data
                    }
                });
            }
            else{
                this.util.setState((prevState) => {
                    let data = {
                        ...prevState.data
                    };
                    if (data.nexus_9k_component) data.nexus_9k_component.value = '';
                    if (data.nexus_9k_cmd) data.nexus_9k_cmd.value = '';
                    if (data.nexus_9k_class_names) data.nexus_9k_class_names.value = '';
                    return {
                        data
                    }
                });
            }
        }

        if (nexus_9k_input_type && nexus_9k_input_type === "nexus_9k_cli") {
            if (this.isEmpty(nexus_9k_component)) {
                this.util.setErrorMsg("Field Component is required");
                return false;
            }
            if (this.isEmpty(nexus_9k_cmd)) {
                this.util.setErrorMsg("Field Command is required");
                return false;
            }
        } else {
            if (this.isEmpty(nexus_9k_dme_query_type)) {
                this.util.setErrorMsg("Field DME Query Type is required");
                return false;
            }
            if (nexus_9k_dme_query_type && nexus_9k_dme_query_type === "nexus_9k_class") {
                if (this.isEmpty(nexus_9k_class_names)) {
                    this.util.setErrorMsg("Field Class Name(s) is required");
                    return false;
                }
            }
            if (nexus_9k_dme_query_type && nexus_9k_dme_query_type === "nexus_9k_managed_object") {
                if (this.isEmpty(nexus_9k_distinguished_names)) {
                    this.util.setErrorMsg("Field Distinguished Name(s) is required");
                    return false;
                }
            }
        }
        return true;
    }
}

export default InputsHook;