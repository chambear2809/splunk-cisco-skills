class AccountHook {
    constructor(globalConfig, serviceName, state, mode, util) {
        this.globalConfig = globalConfig;
        this.serviceName = serviceName;
        this.state = state;
        this.mode = mode;
        this.util = util;
    }

    onRender() {
        if (this.mode === 'edit'){
            this.util.setState((prevState) => {
                const newState = { data: { ...prevState.data } };
                // disable the automatic_input_creation field in edit mode
                if (newState.data.inputs_created.value) {
                    newState.data.inputs_created.disabled = true;
                } else {
                    newState.data.inputs_created.disabled = false;
                }
                return newState;
            });
        }
    }

}

export default AccountHook;