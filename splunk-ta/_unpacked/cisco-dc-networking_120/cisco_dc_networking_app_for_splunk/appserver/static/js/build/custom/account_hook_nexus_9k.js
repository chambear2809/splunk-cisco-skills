class AccountsHook {
    constructor(globalConfig, serviceName, state, mode, util) {
        this.globalConfig = globalConfig;
        this.serviceName = serviceName;
        this.state = state;
        this.mode = mode;
        this.util = util;
    }

    isEmpty(value) {
        /* Returns true if value is not set else false */
        return value === null || value.trim().length === 0;
    }

    isTrue(val) {
        var value = String(val).trim().toUpperCase();
        if (value === "1" || value === "TRUE") {
            return true;
        }
        return false;
    }

    onCreate() {
        this.onChange(null, null, this.state);
    }

    onChange(event, value, newState) {
        const enableProxy = this.isTrue(newState.data.nexus_9k_enable_proxy.value);
        this.util.setState((prevState) => {
            const data = {
                ...prevState.data
            };
            if (data.nexus_9k_proxy_type) data.nexus_9k_proxy_type.display = enableProxy;
            if (data.nexus_9k_proxy_url) data.nexus_9k_proxy_url.display = enableProxy;
            if (data.nexus_9k_proxy_port) data.nexus_9k_proxy_port.display = enableProxy;
            if (data.nexus_9k_proxy_username) data.nexus_9k_proxy_username.display = enableProxy;
            if (data.nexus_9k_proxy_password) data.nexus_9k_proxy_password.display = enableProxy;
            if (!enableProxy) {
                if (data.nexus_9k_proxy_type) data.nexus_9k_proxy_type.value = "";
                if (data.nexus_9k_proxy_url) data.nexus_9k_proxy_url.value = "";
                if (data.nexus_9k_proxy_port) data.nexus_9k_proxy_port.value = "";
                if (data.nexus_9k_proxy_username) data.nexus_9k_proxy_username.value = "";
                if (data.nexus_9k_proxy_password) data.nexus_9k_proxy_password.value = "";
            }
            return {
                data
            }
        });
    }

    onSave(dataDict) {
        const enableProxy = this.isTrue(dataDict.nexus_9k_enable_proxy);
        const proxyType = dataDict.nexus_9k_proxy_type;
        const proxyUrl = dataDict.nexus_9k_proxy_url;
        const proxyPort = dataDict.nexus_9k_proxy_port;
        const proxyUsername = dataDict.nexus_9k_proxy_username;
        const proxyPassword = dataDict.nexus_9k_proxy_password;

        if (enableProxy) {

            if (this.isEmpty(proxyType)) {
                this.util.setErrorMsg("Field Proxy Type is required");
                return false;
            }

            if (this.isEmpty(proxyUrl)) {
                this.util.setErrorMsg("Field Proxy URL is required");
                return false;
            }

            if (this.isEmpty(proxyPort)) {
                this.util.setErrorMsg("Field Proxy Port is required");
                return false;
            }

            if (this.isEmpty(proxyUsername) !== this.isEmpty(proxyPassword)) {
                this.util.setErrorMsg(
                    "Fields Proxy Username and Proxy Password must be both set or unset"
                );
                return false;
            }
        }

        return true;
    }
}

export default AccountsHook;