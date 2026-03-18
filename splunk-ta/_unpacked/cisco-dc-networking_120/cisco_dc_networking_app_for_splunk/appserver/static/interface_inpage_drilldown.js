require(['jquery','underscore','splunkjs/mvc','splunkjs/mvc/simplexml/ready!'], function($, _, mvc, console){    
    // Get a reference to the dashboard panels
    var masterView = mvc.Components.get('master_interface');
    var detailView1 = mvc.Components.get('detail1');
    var detailView2 = mvc.Components.get('detail2');

    var unsubmittedTokens = mvc.Components.get('default');
    var submittedTokens = mvc.Components.get('submitted');

    if(!submittedTokens.has('Interface')) {
        // if there's no value for the $sourcetype$ token yet, hide the dashboard panel of the detail view
        detailView1.$el.parents('.dashboard-panel').hide();
        detailView2.$el.parents('.dashboard-panel').hide();
	
    }
     $("#dashboard").on("change", "input", function() {
        detailView1.$el.parents('.dashboard-panel').hide();
        detailView2.$el.parents('.dashboard-panel').hide();


     });
    
    submittedTokens.on('change:Interface', function(){
        // When the token changes...
        if(!submittedTokens.get('Interface')) {
            // ... hide the panel if the token is not defined
            detailView1.$el.parents('.dashboard-panel').hide();
            detailView2.$el.parents('.dashboard-panel').hide();
           
        } else {
            // ... show the panel if the token has a value
            detailView1.$el.parents('.dashboard-panel').show();
            detailView2.$el.parents('.dashboard-panel').show();
        }
    });

    masterView.on('click', function(e) {
        e.preventDefault();
        if (e.field == "Interface") {
            var newValue = e.data['click.value'];
            var newValue1 = e.data['click.value2'];  
            var final = newValue+"::"+newValue1;      
            // Set the value for the  token
            unsubmittedTokens.set('Interface', final);
            submittedTokens.set('Interface', final);
        }   
    });
});
