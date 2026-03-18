require([
  "jquery",
  "splunkjs/mvc",
  "splunkjs/mvc/tokenutils",
  "splunkjs/mvc/simplexml/ready!"
], function($, mvc, TokenUtils) {

  var defaultTokens = mvc.Components.get("default");
  var submittedTokens = mvc.Components.get("submitted");

  function setToken(name, value) {
    defaultTokens.set(name, value);
    submittedTokens.set(name, value);
  }

  function unsetTokens(tokens) {
    tokens.forEach(token => {
      defaultTokens.unset(token);
      submittedTokens.unset(token);
    });
  }

  function applyConditions(tab_type) {
    // Reset all * tokens
    const allTokens = [
      "physical_disks", "ports", "cpus", "memory", "fanmodules", "psus", "alarms", "metrics", "audit_logs", "advisory", "timerange_tok"
    ];
    unsetTokens(allTokens);

    // Apply tab-level conditions
    setToken(tab_type, "true");
    if (tab_type == "alarms" || tab_type == "metrics" || tab_type == "audit_logs") {
        setToken("timerange_tok", "true");
    }

    handleMetricsTab();

  }

  function setDeviceTypeToken() {
    devtokToken = defaultTokens.get("devtok")
    devtokname = defaultTokens.get("tv_label_token")
    if (devtokToken !== undefined && devtokname !== undefined) {
      if (devtokToken.startsWith("FFI")) {
        setToken("devtyptok", "Fabric Interconnect");
      } else if (devtokToken.startsWith("CChassis")) {
        setToken("devtyptok", "Chassis");
      } else if (devtokToken.startsWith("SServer")) {
        setToken("devtyptok", "Server");
      } else {
        unsetTokens(["devtyptok"]);
      }
      setToken("devname", devtokname)

    }
  }

  $('#treeviewpanel').on('click', function(e) {
    e.preventDefault();
    e.stopPropagation();
    setDeviceTypeToken();
    handleMetricsTab();
  });

  function handleMetricsTab() {
    standtoken = defaultTokens.get("standtok")
    if (standtoken != undefined && standtoken == "True") {
      unsetTokens(["metrics"]);
      $('[data-elements="metrics"]').hide();
    }
  }
  

  // Initial default values
  applyConditions("physical_disks");

  // Tab click handler
  $(document).on('click', '#tabs .toggle-tab', function(e) {
    e.preventDefault();
    e.stopPropagation();
    $('#tabs li').removeClass('active');
    $(this).parent().addClass('active');
    tab_type = $(this).data('elements');
    applyConditions(tab_type);
  });

});