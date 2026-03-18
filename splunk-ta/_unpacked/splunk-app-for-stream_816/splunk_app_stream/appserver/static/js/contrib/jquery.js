define(["swc-stream/index", "app-js/contrib/jquery-3.5.1.min"], function(index) {
    // Update CSRF token value from the cookie with JQuery ajaxPrefilter for CSRF validation
    // Below block of code is required while using jQuery if the js code uses service.post() which requires CSRF validation with POST.
    var HEADER_NAME = 'X-Splunk-Form-Key';
    var FORM_KEY = index.SplunkUtils.getFormKey();
    if (!FORM_KEY) {
        return;
    }
    if ($) {
        $.ajaxPrefilter(function(options, originalOptions, jqXHR) {
            if (options['type'] && options['type'].toUpperCase() == 'GET') return;
            FORM_KEY = index.SplunkUtils.getFormKey();
            jqXHR.setRequestHeader(HEADER_NAME, FORM_KEY);
        });
    }
    // Raw jQuery does not return anything, so return it explicitly here.
    return jQuery;
})