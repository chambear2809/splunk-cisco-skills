class AccountsHook {
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
  
    onChange(event, value, newState) {
      const enableProxy = this.isTrue(newState.data.nd_enable_proxy.value);
      this.util.setState((prevState) => {
        const data = { ...prevState.data };
        data.nd_proxy_type.display = enableProxy;
        data.nd_proxy_url.display = enableProxy;
        data.nd_proxy_port.display = enableProxy;
        data.nd_proxy_username.display = enableProxy;
        data.nd_proxy_password.display = enableProxy;
        if (!enableProxy) {
          data.nd_proxy_type.value = "";
          data.nd_proxy_url.value = "";
          data.nd_proxy_port.value = "";
          data.nd_proxy_username.value = "";
          data.nd_proxy_password.value = "";
        }
        return { data };
      });
  
      const authnditype = newState.data.nd_authentication_type.value;
      this.util.setState((prevState) => {
        const data = { ...prevState.data };
        if (authnditype === "remote_user_authentication") {
          data.nd_login_domain.display = true;
        } else if (authnditype === "local_user_authentication") {
          data.nd_login_domain.value = "";
          data.nd_login_domain.display = false;
        }
        return { data };
      });
    }
  
    onSave(dataDict) {
      const enableProxy = this.isTrue(dataDict.nd_enable_proxy);
      const proxyType = dataDict.nd_proxy_type;
      const proxyUrl = dataDict.nd_proxy_url;
      const proxyPort = dataDict.nd_proxy_port;
      const proxyUsername = dataDict.nd_proxy_username;
      const proxyPassword = dataDict.nd_proxy_password;
      const accountType = dataDict.nd_authentication_type;
      const loginDomain = dataDict.nd_login_domain;

      if (accountType === "remote_user_authentication") {
          if (this.isEmpty(loginDomain)) {
              this.util.setErrorMsg("Field Login Domain is required");
              return false;
          }
      }

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