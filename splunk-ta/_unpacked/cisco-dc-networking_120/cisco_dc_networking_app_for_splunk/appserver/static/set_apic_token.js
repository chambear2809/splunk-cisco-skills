require([
    'splunkjs/mvc',
    'splunkjs/mvc/simplexml/ready!'
], function(mvc) {

    //change the token values
    var tokens = mvc.Components.getInstance("default");
    tokens.on("change:mso_host", function(model, value) {
        tokens.set("form.apic_host","all")
    });

    //remove all from multiselect
    tokens.on("change:multiTokenQuery", function(model, value, options) {
        let arr = value.split(" OR user=")

        if (arr.length > 1 && arr.includes("*")) {
            if (arr[0] == "*") {
                // if all was selected first, and now selected other, then remove All
                tokens.set("form.multiTokenQuery", arr.slice(1))
            } else {
                // if All is selected later, then remove all the selected and put All
                tokens.set("form.multiTokenQuery", "*")
            }
        }
    })
});