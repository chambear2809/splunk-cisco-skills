require(['jquery','underscore','splunkjs/mvc','splunkjs/mvc/simplexml/ready!'], function($, _, mvc, console){    
    // Get a reference to the dashboard panels
    var masterView = mvc.Components.get('master');
    var detailView = mvc.Components.get('detail');
    var detailView1 = mvc.Components.get('detail1');
    var detailView2 = mvc.Components.get('detail2');
    var detailView3 = mvc.Components.get('detail3');
    var detailView4 = mvc.Components.get('detail4');
    var detailView5 = mvc.Components.get('detail5');
   
    var unsubmittedTokens = mvc.Components.get('default');
    var submittedTokens = mvc.Components.get('submitted');
    
    $("#dashboard").on("change", "input:hidden", function() {
        detailView.$el.parents('.dashboard-panel').hide();
        detailView1.$el.parents('.dashboard-panel').hide();
        detailView2.$el.parents('.dashboard-panel').hide();
        detailView3.$el.parents('.dashboard-panel').hide();
        detailView4.$el.parents('.dashboard-panel').hide();
        detailView5.$el.parents('.dashboard-panel').hide();


     });

    if(!submittedTokens.has('hostnametoken')) {
        // if there's no value for the token yet, hide the dashboard panel of the detail view
        detailView.$el.parents('.dashboard-panel').hide();
	detailView1.$el.parents('.dashboard-panel').hide();
        detailView2.$el.parents('.dashboard-panel').hide();
        detailView3.$el.parents('.dashboard-panel').hide();
        detailView4.$el.parents('.dashboard-panel').hide();
        detailView5.$el.parents('.dashboard-panel').hide();
    }
    
    submittedTokens.on('change:hostnametoken', function(){
        // When the token changes...
        if(!submittedTokens.get('hostnametoken')) {
            // ... hide the panel if the token is not defined
            detailView.$el.parents('.dashboard-panel').hide();
            detailView1.$el.parents('.dashboard-panel').hide();
        detailView2.$el.parents('.dashboard-panel').hide();
        detailView3.$el.parents('.dashboard-panel').hide();
        detailView4.$el.parents('.dashboard-panel').hide();
        detailView5.$el.parents('.dashboard-panel').hide();
        } else {
            // ... show the panel if the token has a value
            detailView.$el.parents('.dashboard-panel').show();
	detailView1.$el.parents('.dashboard-panel').show();
        detailView2.$el.parents('.dashboard-panel').show();
        detailView3.$el.parents('.dashboard-panel').show();
        detailView4.$el.parents('.dashboard-panel').show();
        detailView5.$el.parents('.dashboard-panel').show();
        }
    });

    masterView.on('click', function(e) {
        e.preventDefault();
        var newValue = e.data['click.value'];
        // Set the value for the token
        unsubmittedTokens.set('hostnametoken', newValue);
        submittedTokens.set('hostnametoken', newValue);
    });
});
