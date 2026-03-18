class MetricsHook {
    constructor(globalConfig, serviceName, state, mode, util) {
        this.globalConfig = globalConfig;
        this.serviceName = serviceName;
        this.state = state;
        this.mode = mode;
        this.util = util;
    }

    onCreate(){
        this.onChange(null, null, this.state);
    }

    onRender() {
        this.onChange(null, null, this.state);
    }

    onChange(event, value, newState) {
        if (!this.isEmpty(newState.data.metrics.value)) {
            this.updateMetricDisplays(newState);
            this.util.setState((oldState) => {
                return { updatedState: { ...newState.data } };
            });
        }
    
        if (["host_power_energy_metrics", "memory_metrics", "network_metrics"].includes(event)) {
            this.updateMetricValues(event, newState);
            this.util.setState((oldState) => {
                return { updatedState: { ...newState.data } };
            });
        }
    }
    
    updateMetricDisplays(newState) {
        const newFields = newState.data.metrics.value.split(",");
        newState.data.host_power_energy_metrics.display = newFields.includes("host");
        newState.data.memory_metrics.display = newFields.includes("memory");
        newState.data.network_metrics.display = newFields.includes("network");
    }
    
    updateMetricValues(event, newState) {
        const metricType = this.getMetricType(event);
        let newFields = newState.data[metricType].value.split(",");
        const lastNewField = newFields[newFields.length - 1];
        const firstNewField = newFields[0];
    
        if (newFields.length > 1 && firstNewField === "All") {
            newFields.shift();
            newState.data[metricType].value = newFields.toString();
        } else if (lastNewField === "All" && newFields.length > 1) {
            newState.data[metricType].value = "All";
        }
    }
    
    getMetricType(event) {
        if (event === "host_power_energy_metrics" || event === "memory_metrics") {
            return event;
        } else {
            return "network_metrics";
        }
    }

    onSave(datadict){
        if (!this.isEmpty(datadict.metrics)) {
            let newFields = datadict.metrics.split(",");
            if (newFields.includes("host") && this.isEmpty(datadict.host_power_energy_metrics)) {
                this.util.setErrorMsg("Field Host Power And Energy Metrics is required");
                return false;
            }
            if (newFields.includes("memory") && this.isEmpty(datadict.memory_metrics)) {
                this.util.setErrorMsg("Field Memory Module Metrics is required");
                return false;
            }
            if (newFields.includes("network") && this.isEmpty(datadict.network_metrics)) {
                this.util.setErrorMsg("Field Network Interface Metrics is required");
                return false;
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

export default MetricsHook;