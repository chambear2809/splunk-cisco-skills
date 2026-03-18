class OrganizationHook {
    constructor(globalConfig, serviceName, state, mode, util) {
        this.globalConfig = globalConfig;
        this.serviceName = serviceName;
        this.state = state;
        this.mode = mode;
        this.util = util;
        this.regionMapping = {
            global: "https://api.meraki.com",
            india: "https://api.meraki.in",
            canada: "https://api.meraki.ca",
            china: "https://api.meraki.cn",
            fedramp: "https://api.gov-meraki.com",
            other: "https://api.meraki.com"
        }
    }

    isTrue(value) {
        if (["1", 1, true, "True"].includes(value)) {
            return true;
        }
        return false;
    }

    handleRegionSelection(state) {
        const newState = state;
        newState.data.base_url.disabled = true;
        if (newState.data.region.value === "india") {
            newState.data.base_url.value = this.regionMapping.india;
        } else if (newState.data.region.value === "canada") {
            newState.data.base_url.value = this.regionMapping.canada;
        } else if (newState.data.region.value === "china") {
            newState.data.base_url.value = this.regionMapping.china;
        } else if (newState.data.region.value === "fedramp") {
            newState.data.base_url.value = this.regionMapping.fedramp;
        } else if (newState.data.region.value === "other") {
            newState.data.base_url.value = this.regionMapping.other;
            newState.data.base_url.disabled = false;
        } else {
            newState.data.base_url.value = this.regionMapping.global
        }
        return newState;
    }

    onRender() {
        this.util.setState((prevState) => {
            const newState = { data: { ...prevState.data } };
    
            // disable base_url, automatic_input_creation, automatic_input_creation_index fields in edit mode
            if (this.mode === 'edit') {
                newState.data.automatic_input_creation.disabled = true;
                newState.data.automatic_input_creation_index.disabled = true;
                newState.data.region.disabled = true;
                newState.data.base_url.disabled = true;
                newState.data.auth_type.disabled = true;
                // set automatic_input_creation_index to "main" by default
                if (this.isTrue(newState.data.automatic_input_creation.value) && (newState.data.automatic_input_creation_index.value===null)) {
                    newState.data.automatic_input_creation_index.value = "main";
                }
            }

            if (this.mode === 'clone') {
                newState.data.endpoint.value = "as.meraki.com";
                newState.data.scope.value = "dashboard:general:config:read dashboard:general:telemetry:read wireless:config:read switch:telemetry:read sdwan:telemetry:read dashboard:licensing:config:read camera:config:read sensor:config:read sensor:telemetry:read camera:telemetry:read switch:config:read wireless:telemetry:read dashboard:general:telemetry:write";
            }
    
            // conditionally show/hide fields
            if (this.isTrue(newState.data.automatic_input_creation.value)) {
                newState.data.automatic_input_creation_index.display = true;
            } else {
                newState.data.automatic_input_creation_index.display = false;
            }

            // disable base_url field if region is not other
            if (newState.data.region.value !== "other") {
                newState.data.base_url.disabled = true;
            }
            newState.data.endpoint.display = false;
            newState.data.scope.display = false;
            if (!newState.data.base_url.value) {
                if (newState.data.region.value === "china") {
                    newState.data.base_url.value = this.regionMapping.china;
                } else {
                    newState.data.base_url.value = this.regionMapping.global;
                }
            }
            // Hide auth_type field as a part of CMKI-705
            newState.data.auth_type.value = "basic";
            newState.data.auth_type.display = false;
    
            return newState;
        });
    }

    onChange(field, value, dataDict) {
        if (field === "region") {
            this.util.setState((prevState) => {
                const newState = { data: { ...prevState.data } };
                const updatedState = this.handleRegionSelection(newState)
                return updatedState;
            });
        } else if (field === "automatic_input_creation") {
            this.util.setState((prevState) => {
                const newState = { data: { ...prevState.data } };
                if (this.isTrue(value)) {
                    newState.data.automatic_input_creation_index.display = true;
                } else {
                    newState.data.automatic_input_creation_index.display = false;
                }
                return newState;
            });
        } else if (field === "auth_type") {
            this.util.setState((prevState) => {
                const newState = { data: { ...prevState.data } };
                newState.data.endpoint.display = false;
                newState.data.scope.display = false;
                return newState;
            });
        }
    }

    onSave(dataDict) {
        this.util.setState((prevState) => {
            let new_state = this.util.clearAllErrorMsg(prevState);
            return new_state
        });

        const should_create_inputs = dataDict.automatic_input_creation;
        const index_name = dataDict.automatic_input_creation_index;

        if (this.isTrue(should_create_inputs) && !index_name) {
            const msg = "Field Index is required.";
            this.util.setErrorMsg(msg);
            return false;
        }
        if (dataDict.region !== "global" && dataDict.auth_type === "oauth") {
            const msg = "OAuth2 Authentication is supported only with 'Global' Service region. Consider using Basic Authentication for any non-global Service region.";
            this.util.setErrorMsg(msg);
            return false;
        }
        return true;
    }
}

export default OrganizationHook;