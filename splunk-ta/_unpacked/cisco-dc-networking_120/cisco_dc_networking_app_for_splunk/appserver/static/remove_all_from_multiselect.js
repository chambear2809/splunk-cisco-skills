require([
    "jquery",
    "splunkjs/mvc",
    "splunkjs/mvc/simplexml/ready!"
], function ($, mvc) {
    var defaultToken = mvc.Components.getInstance("default");
    defaultToken.on("change:form.related", function(model, value, options) {
        if (value.length > 1 && value.includes("*")) {
            if (value[0] == "*") {   
                // if all was selected first, and now selected other, then remove All
                defaultToken.set("form.related", value.slice(1))
            } else {
                // if All is selected later, then remove all the selected and put All
                defaultToken.set("form.related", "*")
            }
        }
    })
});