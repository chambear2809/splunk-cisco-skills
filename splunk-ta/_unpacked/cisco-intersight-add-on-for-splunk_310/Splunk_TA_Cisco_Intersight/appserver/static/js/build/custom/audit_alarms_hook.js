class AuditAlarmsHook {
    constructor(globalConfig, serviceName, state, mode, util) {
        this.globalConfig = globalConfig;
        this.serviceName = serviceName;
        this.state = state;
        this.mode = mode;
        this.util = util;
    }

    onSave(datadict){

        this.util.setState((prevState) => {

            const newStatereturn = { data: { ...prevState.data } };
            if (datadict.date_input != this.state.data.date_input.value) {
                newStatereturn.data.interval_proxy.value = 1
            }
            else {
                newStatereturn.data.interval_proxy.value = 0
            }
        });

        if (this.isEmpty(datadict.enable_aaa_audit_records) && this.isEmpty(datadict.enable_alarms)) {
            this.util.setErrorMsg("At least enable one of the checkbox 'Enable AAA Audit Records' or 'Enable Alarms'.");
            return false;
        }
        return true;
    }

    onChange(event, value, newState) {
        this.util.setState((prevState) => {
            const newStatereturn = { data: { ...prevState.data } };
            if (newStatereturn.data.enable_alarms.value == "1") {
                newStatereturn.data.acknowledge.display = true
                newStatereturn.data.suppressed.display = true
                newStatereturn.data.info_alarms.display = true
            }
            else{
                newStatereturn.data.acknowledge.display = false
                newStatereturn.data.suppressed.display = false
                newStatereturn.data.info_alarms.display = false
            }
            return newStatereturn;
        }
        );
    }

    onRender(event, value, newState) {
        this.util.setState((prevState) => {
            const newStatereturn = { data: { ...prevState.data } };
            console.log(newStatereturn.data.enable_alarms.value);
            if (newStatereturn.data.enable_alarms.value == "1") {
                newStatereturn.data.acknowledge.display = true
                newStatereturn.data.suppressed.display = true
                newStatereturn.data.info_alarms.display = true
            }
            else{
                newStatereturn.data.acknowledge.display = false
                newStatereturn.data.suppressed.display = false
                newStatereturn.data.info_alarms.display = false
            }
            console.log(newStatereturn);
            return newStatereturn;
        });
    }

    isEmpty(value) {
		/* Returns true if value is not set else false */
		return value === null || value === "0" || value === 0;
	}
}

export default AuditAlarmsHook;