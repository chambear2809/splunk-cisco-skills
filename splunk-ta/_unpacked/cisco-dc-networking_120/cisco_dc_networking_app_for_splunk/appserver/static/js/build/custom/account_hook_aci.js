class AccountHook {

    /**
     * Form hook
     * @constructor
     * @param {Object} globalConfig - Global configuration.
     * @param {string} serviceName - Service name
     * @param {object} state - Initial state of the form
     * @param {string} mode - Form mode. Can be edit, create or clone
     * @param {object} util - Object containing utility methods
     * {
     *    setState,
     *    setErrorMsg,
     *    setErrorFieldMsg,
     *    clearAllErrorMsg
     * }
     **/
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
        var value = String(val).trim().toUpperCase();
        if (value === "1" || value === "TRUE") {
            return true;
        }
        return false;
    }

    onChange(field, value, dataDict) {
        if (field === "aci_account_type") {
            this.manageFieldsForAccountType(value);
        } else if (field === "apic_authentication_type") {
            this.manageApicAuthType(value);
        } else if (field === "apic_proxy_enabled") {
            let apic_proxy = dataDict.data.apic_proxy_enabled.value;
            if (apic_proxy != undefined) {
                if (!apic_proxy || apic_proxy === '0') {
                    return this.toggleProxySettingsDisplay(false);
                } else {
                    return this.toggleProxySettingsDisplay(true);
                }
            } else {
                return this.toggleProxySettingsDisplay(false);
            }
        }
    }

    manageApicAuthType(valueAPICauth) {
        this.util.setState((prevState) => {
            let data = {
                ...prevState.data
            };
            const displayData = this.state.data;
            const value = valueAPICauth || displayData.apic_authentication_type.value;
            if (value === "certificate_authentication") {
                displayData.apic_username.display = true;
                displayData.apic_password.display = false;
                displayData.apic_certificate_name.display = true;
                displayData.apic_certificate_path.display = true;
                displayData.apic_login_domain.display = false;
                data.apic_login_domain.value = "";
                data.apic_password.value = "";
            } else if (value === "password_authentication") {
                displayData.apic_username.display = true;
                displayData.apic_password.display = true;
                displayData.apic_login_domain.display = false;
                displayData.apic_certificate_name.display = false;
                displayData.apic_certificate_path.display = false;
                data.apic_login_domain.value = "";
                data.apic_certificate_name.value = "";
                data.apic_certificate_path.value = "";
            } else if (value === "remote_user_authentication") {
                displayData.apic_username.display = true;
                displayData.apic_password.display = true;
                displayData.apic_login_domain.display = true;
                displayData.apic_certificate_name.display = false;
                displayData.apic_certificate_path.display = false;
                data.apic_certificate_name.value = "";
                data.apic_certificate_path.value = "";
            }
            return {
                data
            };
        });
    }

    manageFieldsForAccountType(onChangeSelectedAccountFieldValue) {
        const displayData = this.state.data;

        let flag = 0;
        let value = null;
        let isAccountType = false;

        if (onChangeSelectedAccountFieldValue) {
            value = onChangeSelectedAccountFieldValue;
            isAccountType = true;
        } else {
            isAccountType = displayData.account_type;
            value = displayData.account_type && displayData.account_type.value;
        }

        if (isAccountType) {
            flag = value === "apic" ? 0 : 2;
        }

        this.util.setState((prevState) => {
            let data = {
                ...prevState.data
            };
            data.apic_hostname.display = false;
            data.apic_port.display = false;
            data.apic_authentication_type.display = false;
            data.apic_login_domain.display = false;
            data.apic_certificate_name.display = false;
            data.apic_certificate_path.display = false;
            data.apic_username.display = false;
            data.apic_password.display = false;

            switch (flag) {
                case 0:
                    data.apic_hostname.display = true;
                    data.apic_port.display = true;
                    data.apic_authentication_type.display = true;
                    data.apic_login_domain.display = true;
                    data.apic_certificate_name.display = true;
                    data.apic_certificate_path.display = true;
                    data.apic_username.display = true;
                    data.apic_password.display = true;

                    let apic_apic_authentication_type = displayData.apic_authentication_type.value;

                    if (apic_apic_authentication_type === "certificate_authentication") {
                        data.apic_username.display = true;
                        data.apic_certificate_name.display = true;
                        data.apic_certificate_path.display = true;
                        data.apic_password.display = false;
                        data.apic_login_domain.display = false;
                    }

                    if (apic_apic_authentication_type === "password_authentication") {
                        data.apic_username.display = true;
                        data.apic_password.display = true;
                        data.apic_certificate_name.display = false;
                        data.apic_certificate_path.display = false;
                        data.apic_login_domain.display = false;
                    }

                    if (apic_apic_authentication_type === "remote_user_authentication") {
                        data.apic_login_domain.display = true;
                        data.apic_username.display = true;
                        data.apic_password.display = true;
                    }

                    break;
                case 1:
                    data.apic_certificate_name.display = false;
                    data.apic_certificate_path.display = false;
                    data.apic_username.display = false;
                    data.apic_password.display = false;
                    data.apic_hostname.display = false;
                    data.apic_port.display = false;
                    data.apic_authentication_type.display = false;
                    data.apic_login_domain.display = false;
                    break;
                default:
                    data.api_secret.display = true;
                    break;
            }
            return {
                data
            };
        });
    }

    onRender() {
        this.manageFieldsForAccountType(null);
        this.manageApicAuthType(null);
        let apic_proxy = this.state.data.apic_proxy_enabled.value;
        if (apic_proxy != undefined) {
            if (!apic_proxy || apic_proxy === '0') {
                return this.toggleProxySettingsDisplay(false);
            } else {
                return this.toggleProxySettingsDisplay(true);
            }
        } else {
            return this.toggleProxySettingsDisplay(false);
        }
    }

    toggleProxySettingsDisplay(flag) {
        this.util.setState((prevState) => {
            let data = {
                ...prevState.data
            };
            data.apic_proxy_type.display = flag;
            data.apic_proxy_url.display = flag;
            data.apic_proxy_port.display = flag;
            data.apic_proxy_username.display = flag;
            data.apic_proxy_password.display = flag;
            if (!flag) {
                if (data.apic_proxy_type) data.apic_proxy_type.value = "";
                if (data.apic_proxy_url) data.apic_proxy_url.value = "";
                if (data.apic_proxy_port) data.apic_proxy_port.value = "";
                if (data.apic_proxy_username) data.apic_proxy_username.value = "";
                if (data.apic_proxy_password) data.apic_proxy_password.value = "";
            }
            return {
                data
            }
        });
    }

    onSave(dataDict) {
        const enableProxy = this.isTrue(dataDict.apic_proxy_enabled);
        const proxyScheme = dataDict.apic_proxy_type;
        const proxyUrl = dataDict.apic_proxy_url;
        const proxyPort = dataDict.apic_proxy_port;
        const proxyUsername = dataDict.apic_proxy_username;
        const proxyPassword = dataDict.apic_proxy_password;
        const authType = dataDict.apic_authentication_type;

        if (authType === "password_authentication"){
            if (this.isEmpty(dataDict.apic_username)) {
               this.util.setErrorMsg(
                    "Field APIC Username is required."
                );
                return false; 
            }
            if (this.isEmpty(dataDict.apic_password)) {
               this.util.setErrorMsg(
                    "Field APIC Password is required."
                );
                return false; 
            }
        }

        else if (authType === "remote_user_authentication"){
            if (this.isEmpty(dataDict.apic_username)) {
               this.util.setErrorMsg(
                    "Field APIC Username is required."
                );
                return false; 
            }
            if (this.isEmpty(dataDict.apic_password)) {
               this.util.setErrorMsg(
                    "Field APIC Password is required."
                );
                return false; 
            }
            if (this.isEmpty(dataDict.apic_login_domain)) {
               this.util.setErrorMsg(
                    "Field APIC Login Domain is required."
                );
                return false; 
            }
        }

        else if (authType === "certificate_authentication"){
            if (this.isEmpty(dataDict.apic_username)) {
               this.util.setErrorMsg(
                    "Field APIC Username is required."
                );
                return false; 
            }
            if (this.isEmpty(dataDict.apic_certificate_name)) {
               this.util.setErrorMsg(
                    "Field Certificate Name is required."
                );
                return false; 
            }
            if (this.isEmpty(dataDict.apic_certificate_path)) {
               this.util.setErrorMsg(
                    "Field Path of Private Key is required."
                );
                return false; 
            }
        }

        if (enableProxy) {
            if (this.isEmpty(proxyScheme)) {
                this.util.setErrorMsg("Field Proxy Type is required.")
                return false;
            }

            if (this.isEmpty(proxyUrl)) {
                this.util.setErrorMsg("Field Proxy Host is required.");
                return false;
            }

            if (this.isEmpty(proxyPort)) {
                this.util.setErrorMsg("Field Proxy Port is required.");
                return false;
            }

            if (this.isEmpty(proxyUsername) !== this.isEmpty(proxyPassword)) {
                this.util.setErrorMsg(
                    "Fields Proxy Username and Proxy Password must be both set or unset."
                );
                return false;
            }
        }

        return true;
    }
}

export default AccountHook;