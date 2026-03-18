require(['jquery','underscore','splunkjs/mvc','splunkjs/mvc/simplexml/ready!'], function($, _, mvc){    
    // Get a reference to the dashboard panels
    var masterView1 = mvc.Components.get('master1');
    var masterView2 = mvc.Components.get('master2');
    var detailView1 = mvc.Components.get('detail1');
    var detailView2 = mvc.Components.get('detail2');
    var detailView3 = mvc.Components.get('detail3');
    var detailView4 = mvc.Components.get('detail4');


    var unsubmittedTokens = mvc.Components.get('default');
    var submittedTokens = mvc.Components.get('submitted');

    $('input[type=text]').change(function(){
        try {
           detailView1.$el.parents('.dashboard-panel').hide();
           detailView2.$el.parents('.dashboard-panel').hide();
           detailView3.$el.parents('.dashboard-panel').hide();
           detailView4.$el.parents('.dashboard-panel').hide();

        } catch(e) { ; }
    });

    if(!submittedTokens.has('tenant')) {
        // if there's no value for the $sourcetype$ token yet, hide the dashboard panel of the detail view
        detailView1.$el.parents('.dashboard-panel').hide();
        detailView2.$el.parents('.dashboard-panel').hide();
        detailView3.$el.parents('.dashboard-panel').hide();
        detailView4.$el.parents('.dashboard-panel').hide();
    }
    
    submittedTokens.on('change:tenant', function(){
        // When the token changes...
        if(!submittedTokens.get('tenant')) {
            // ... hide the panel if the token is not defined
            detailView1.$el.parents('.dashboard-panel').hide();
            detailView2.$el.parents('.dashboard-panel').hide();
            detailView3.$el.parents('.dashboard-panel').hide();
            detailView4.$el.parents('.dashboard-panel').hide();
           
        } else {
            // ... show the panel if the token has a value
            detailView1.$el.parents('.dashboard-panel').show();
            detailView2.$el.parents('.dashboard-panel').show();
            detailView3.$el.parents('.dashboard-panel').show();
            detailView4.$el.parents('.dashboard-panel').show();
        }
    });

    masterView1.on('click', function(e) {
        e.preventDefault();
        var newValue = e.data['click.value'];
        
        // Set the value for the $sourcetype$ token
        unsubmittedTokens.set('tenant', newValue);
        submittedTokens.set('tenant', newValue);
    });

   masterView2.on('click', function(e) {
        e.preventDefault();
        var newValue = e.data['click.value'];

        // Set the value for the $sourcetype$ token
        unsubmittedTokens.set('tenant', newValue);
        submittedTokens.set('tenant', newValue);
    });

});
