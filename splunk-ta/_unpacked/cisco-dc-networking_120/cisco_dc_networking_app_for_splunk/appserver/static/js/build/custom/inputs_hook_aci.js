var aci_account_list = [];

require([
    'splunkjs/mvc',
    'splunkjs/mvc/utils',
    'splunkjs/mvc/tokenutils',
    'underscore',
    'jquery',
], function(mvc) {
    mvc.createService().get("/servicesNS/nobody/cisco_dc_networking_app_for_splunk/configs/conf-cisco_dc_networking_app_for_splunk_aci_account", {}, function(err, response) {
        if (response && response.data && response.data.entry && Array.isArray(response.data.entry)) {
            let nameList = response.data.entry.map(entry => entry.name);
            aci_account_list = nameList;
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

    onCreate() {
        this.onChange(null, null, this.state);
    }

    onChange(field, value, newState) {
        if (newState.data && newState.data.apic_input_type && newState.data.apic_input_type.value === "classInfo") {
            this.util.setState((prevState) => {
                let data = {
                    ...prevState.data
                };
                if (data.aci_additional_parameters) data.aci_additional_parameters.display = true;
                if (data.mo_support_object) data.mo_support_object.display = false;
                if (data.apic_arguments) data.apic_arguments.display = true;
                return {
                    data
                }
            });
        }
        else if (newState.data && newState.data.apic_input_type && newState.data.apic_input_type.value === "managed_objects") {
            this.util.setState((prevState) => {
                let data = {
                    ...prevState.data
                };
                if (data.aci_additional_parameters) data.aci_additional_parameters.display = true;
                if (data.mo_support_object) data.mo_support_object.display = true;
                if (data.apic_arguments) data.apic_arguments.display = false;
                return {
                    data
                }
            });
        }
        else {
            this.util.setState((prevState) => {
                let data = {
                    ...prevState.data
                };
                if (data.aci_additional_parameters) data.aci_additional_parameters.display = false;
                if (data.mo_support_object) data.mo_support_object.display = false;
                if (data.apic_arguments) data.apic_arguments.display = true;
                return {
                    data
                }
            });
        }
        if (newState.data && newState.data.apic_account && newState.data.apic_account.value) {
            let accountValues = [];
            if (newState.data.apic_account.value) {
                if (typeof newState.data.apic_account.value === 'string') {
                    accountValues = newState.data.apic_account.value.split(',');
                } else if (Array.isArray(newState.data.apic_account.value)) {
                    accountValues = newState.data.apic_account.value;
                } else if (typeof newState.data.apic_account.value === 'object') {
                    accountValues = Object.keys(newState.data.apic_account.value);
                }
            }
            const isSelectAll = accountValues.includes(" Select All");
            this.util.setState((prevState) => {
                let data = {
                    ...prevState.data
                };
                if (data.apic_account) {
                    if (isSelectAll) {
                        data.apic_account.value = aci_account_list.filter(account => account !== " Select All");
                    } else {
                        data.apic_account.value = accountValues;
                    }
                }
                return {
                    data
                }
            });
        }
        if (field === "apic_input_type") {
            this.util.setState((prevState) => {
                let data = {
                    ...prevState.data
                };
                if (data.aci_additional_parameters) data.aci_additional_parameters.value = "";
                if (data.mo_support_object) data.mo_support_object.value = "";
                if (data.apic_arguments) data.apic_arguments.value = "";
                return {
                    data
                }
            });
        }
    }

    onSave(dataDict) {
        const apic_input_type = dataDict.apic_input_type;
        const apic_arguments = dataDict.apic_arguments;
        const mo_support_object = dataDict.mo_support_object;

        if (apic_input_type && apic_input_type === "managed_objects") {
            this.util.setState((prevState) => {
                let data = {
                    ...prevState.data
                };
                if (data.apic_arguments) data.apic_arguments.value = '';
                return {
                    data
                }
            });
        } else if (apic_input_type && apic_input_type === "classInfo") {
            this.util.setState((prevState) => {
                let data = {
                    ...prevState.data
                };
                if (data.mo_support_object) data.mo_support_object.value = '';
                return {
                    data
                }
            });
        } else {
            this.util.setState((prevState) => {
                let data = {
                    ...prevState.data
                };
                if (data.mo_support_object) data.mo_support_object.value = '';
                if (data.aci_additional_parameters) data.aci_additional_parameters.value = '';
                return {
                    data
                }
            });
        }

        if (apic_input_type && apic_input_type === "managed_objects") {
            if (this.isEmpty(mo_support_object)) {
                this.util.setErrorMsg("Field Distinguished Name(s) is required");
                return false;
            }
        } else {
            if (this.isEmpty(apic_arguments)) {
                this.util.setErrorMsg("Field Class Name(s) is required");
                return false;
            }
        }
        return true;
    }
}

export default InputsHook;