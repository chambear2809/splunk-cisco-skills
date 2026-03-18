require(['jquery','underscore','splunkjs/mvc','splunkjs/mvc/simplexml/ready!'], function($, _, mvc){    
    //change the token values

    var tokens = mvc.Components.getInstance("default");
    tokens.on("change:mso_host", function(model, value) {
        tokens.set("form.apic_host","all")
    });

    // Get a reference to the dashboard panels
    var masterView = mvc.Components.get('master');
    var detailView2 = mvc.Components.get('detail2');

    var unsubmittedTokens = mvc.Components.get('default');
    var submittedTokens = mvc.Components.get('submitted');

    $('input[type=text]').change(function(){
        try {
           detailView2.$el.parents('.dashboard-panel').hide();

        } catch(e) { ; }
    });

    if(!submittedTokens.has('tenant')) {
        // if there's no value for the $sourcetype$ token yet, hide the dashboard panel of the detail view
        detailView2.$el.parents('.dashboard-panel').hide();
    }
    
    submittedTokens.on('change:tenant', function(){
        // When the token changes...
        if(!submittedTokens.get('tenant')) {
            // ... hide the panel if the token is not defined
            detailView2.$el.parents('.dashboard-panel').hide();
           
        } else {
            // ... show the panel if the token has a value
            detailView2.$el.parents('.dashboard-panel').show();
        }
    });

    masterView.on('click', function(e) {
        e.preventDefault();
        var newValue = e.data['click.value'];
        
        // Set the value for the $sourcetype$ token
        unsubmittedTokens.set('tenant', newValue);
        submittedTokens.set('tenant', newValue);
    });
});
