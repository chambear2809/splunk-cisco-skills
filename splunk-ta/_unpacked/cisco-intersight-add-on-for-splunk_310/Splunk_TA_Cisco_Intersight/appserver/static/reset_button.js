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

  // Tab click handler
  $('#resettokens').on('click', function(e) {
    e.preventDefault();
    e.stopPropagation();

    unsetTokens(["devtok","fitok","servertok","chassistok","physical_disks", "ports", "alarms", "metrics", "audit_logs", "advisory", "timerange_tok"]);
    setToken("server_typ", "*");
    setToken("server_mode", "*");
  });

});