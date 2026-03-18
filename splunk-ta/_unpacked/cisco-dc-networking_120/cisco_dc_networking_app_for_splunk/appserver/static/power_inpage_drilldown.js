require(['jquery','underscore','splunkjs/mvc','splunkjs/mvc/simplexml/ready!'], function($, _, mvc, console){    
    // Get a reference to the dashboard panels
    var masterView = mvc.Components.get('master_power');
    var detailView = mvc.Components.get('detail_power');

    var unsubmittedTokens = mvc.Components.get('default');
    var submittedTokens = mvc.Components.get('submitted');
    
    $("select").change( function() { 
   	detailView.$el.parents('.dashboard-panel').hide();
    });

    if(!submittedTokens.has('Device')) {
        // if there's no value for the $sourcetype$ token yet, hide the dashboard panel of the detail view
        detailView.$el.parents('.dashboard-panel').hide();
    }
     $("#dashboard").on("change", "input:hidden", function() {
        detailView.$el.parents('.dashboard-panel').hide();
        detailView1.$el.parents('.dashboard-panel').hide();
        detailView2.$el.parents('.dashboard-panel').hide();
        detailView3.$el.parents('.dashboard-panel').hide();
        detailView4.$el.parents('.dashboard-panel').hide();
        detailView5.$el.parents('.dashboard-panel').hide();


     });
    
    submittedTokens.on('change:Device', function(){
        // When the token changes...
        if(!submittedTokens.get('Device')) {
            // ... hide the panel if the token is not defined
            detailView.$el.parents('.dashboard-panel').hide();
           
        } else {
            // ... show the panel if the token has a value
            detailView.$el.parents('.dashboard-panel').show();
        }
    });

    masterView.on('click', function(e) {
        e.preventDefault();
        var newValue = e.data['click.value'];
        var newValue1 = e.data['click.value2'];
	var final = newValue+"::"+newValue1;        
        // Set the value for the $sourcetype$ token
        unsubmittedTokens.set('Device', final);
        submittedTokens.set('Device', final);
    });
});
