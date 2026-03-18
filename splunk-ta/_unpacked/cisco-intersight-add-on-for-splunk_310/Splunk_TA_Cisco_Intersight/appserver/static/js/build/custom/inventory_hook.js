class InventoryHook {
    constructor(globalConfig, serviceName, state, mode, util) {
        this.globalConfig = globalConfig;
        this.serviceName = serviceName;
        this.state = state;
        this.mode = mode;
        this.util = util;
    }

    onCreate() {
        this.onChange(null, null, this.state);
    }

    onRender() {
        this.onChange(null, null, this.state);
    }

    onChange(event, value, newState) {
        if (!this.isEmpty(newState.data.inventory.value)) {
            this.updateEndpointDisplay(newState);
            this.util.setState((oldState) => {
                return { updatedState: { ...newState.data } };
            });
        }

        if (event === "compute_endpoints" || event === "fabric_endpoints" || event === "license_endpoints" || event === "ports_endpoints" || event === "pools_endpoints") {
            this.updateEndpointValues(event, newState);
            this.util.setState((oldState) => {
                return { updatedState: { ...newState.data } };
            });
        }
    }

    updateEndpointDisplay(newState) {
        const newFields = newState.data.inventory.value.split(",");
        newState.data.compute_endpoints.display = newFields.includes("compute");
        newState.data.fabric_endpoints.display = newFields.includes("fabric");
        newState.data.license_endpoints.display = newFields.includes("license");
        newState.data.ports_endpoints.display = newFields.includes("ports");
        newState.data.pools_endpoints.display = newFields.includes("pools");
    }

    updateEndpointValues(event, newState) {
        let endpointType;

        if (event === "compute_endpoints") {
            endpointType = "compute_endpoints";
        } else if (event === "license_endpoints") {
            endpointType = "license_endpoints";
        } else if (event === "ports_endpoints") {
            endpointType = "ports_endpoints";
        } else if (event === "pools_endpoints") {
            endpointType = "pools_endpoints";
        } else {
            endpointType = "fabric_endpoints";
        }
        let newFields = newState.data[endpointType].value.split(",");
        const lastNewField = newFields[newFields.length - 1];
        const firstNewField = newFields[0];

        if (newFields.length > 1 && firstNewField === "All") {
            newFields.shift();
            newState.data[endpointType].value = newFields.toString();
        } else if (lastNewField === "All" && newFields.length > 1) {
            newState.data[endpointType].value = "All";
        }
    }

    onSave(datadict) {
        if (!this.isEmpty(datadict.inventory)) {
            let newFields = datadict.inventory.split(",");
            if (newFields.includes("compute") && this.isEmpty(datadict.compute_endpoints)) {
                this.util.setErrorMsg("Field Compute Objects is required");
                return false;
            }
            else {
                datadict.compute_endpoints = "";
            }
            if (newFields.includes("fabric") && this.isEmpty(datadict.fabric_endpoints)) {
                this.util.setErrorMsg("Field Fabric Objects is required");
                return false;
            }
            else {
                datadict.fabric_endpoints = "";
            }
            if (newFields.includes("license") && this.isEmpty(datadict.license_endpoints)) {
                this.util.setErrorMsg("Field License Objects is required");
                return false;
            }
            else {
                datadict.license_endpoints = "";
            }
            if (newFields.includes("ports") && this.isEmpty(datadict.ports_endpoints)) {
                this.util.setErrorMsg("Field Ports is required");
                return false;
            }
            else {
                datadict.ports_endpoints = "";
            }
            if (newFields.includes("pools") && this.isEmpty(datadict.pools_endpoints)) {
                this.util.setErrorMsg("Field Pools is required");
                return false;
            }
            else {
                datadict.pools_endpoints = "";
            }
            return true;
        }
        return true;
    }

    isEmpty(value) {
        /* Returns true if value is not set else false */
        return value === null || value.trim().length === 0;
    }

}

export default InventoryHook;