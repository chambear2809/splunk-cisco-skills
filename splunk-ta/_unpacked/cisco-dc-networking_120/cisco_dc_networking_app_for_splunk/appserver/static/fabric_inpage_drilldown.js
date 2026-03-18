require(['jquery','underscore','splunkjs/mvc','splunkjs/mvc/simplexml/ready!'], function($, _, mvc){    
    // Get a reference to the dashboard panels
    var masterView1 = mvc.Components.get('master1');
    var masterView2 = mvc.Components.get('master2');
    var detailView1 = mvc.Components.get('detail1');
    var detailView2 = mvc.Components.get('detail2');
    var detailView3 = mvc.Components.get('detail3');
    var detailView4 = mvc.Components.get('detail4');
    var detailView5 = mvc.Components.get('detail5');
    var detailView6 = mvc.Components.get('detail6');
    var detailView7 = mvc.Components.get('detail7');
    var masterView3 = mvc.Components.get('master3');
    var masterView4 = mvc.Components.get('master4');
    var detailView8 = mvc.Components.get('detail8');
    var detailView9 = mvc.Components.get('detail9');
    var unsubmittedTokens = mvc.Components.get('default');
    var submittedTokens = mvc.Components.get('submitted');

$('input[type=text]').change(function(){
try {
  detailView1.$el.parents('.dashboard-panel').hide();
  detailView2.$el.parents('.dashboard-panel').hide();
  detailView3.$el.parents('.dashboard-panel').hide();
  detailView4.$el.parents('.dashboard-panel').hide();
  detailView5.$el.parents('.dashboard-panel').hide();
  detailView6.$el.parents('.dashboard-panel').hide();
  detailView7.$el.parents('.dashboard-panel').hide();
  detailView8.$el.parents('.dashboard-panel').hide();
  detailView9.$el.parents('.dashboard-panel').hide();

} catch(e) { ; } 
});

    if(!submittedTokens.has('nodeName')) {
        // if there's no value for the $sourcetype$ token yet, hide the dashboard panel of the detail view
        detailView1.$el.parents('.dashboard-panel').hide();
        detailView2.$el.parents('.dashboard-panel').hide();
        detailView3.$el.parents('.dashboard-panel').hide();
        detailView4.$el.parents('.dashboard-panel').hide();
        detailView5.$el.parents('.dashboard-panel').hide();
        detailView6.$el.parents('.dashboard-panel').hide();
        detailView7.$el.parents('.dashboard-panel').hide();
    }

    if(!submittedTokens.has('Name')) {
        // if there's no value for the $sourcetype$ token yet, hide the dashboard panel of the detail view
        detailView8.$el.parents('.dashboard-panel').hide();
        detailView9.$el.parents('.dashboard-panel').hide();
    }
    
    submittedTokens.on('change:nodeName', function(){
        // When the token changes...
        if(!submittedTokens.get('nodeName')) {
            // ... hide the panel if the token is not defined
            detailView1.$el.parents('.dashboard-panel').hide();
            detailView2.$el.parents('.dashboard-panel').hide();
            detailView3.$el.parents('.dashboard-panel').hide();
            detailView4.$el.parents('.dashboard-panel').hide();
            detailView5.$el.parents('.dashboard-panel').hide();
            detailView6.$el.parents('.dashboard-panel').hide();
            detailView7.$el.parents('.dashboard-panel').hide();
        } else {
            // ... show the panel if the token has a value
            detailView1.$el.parents('.dashboard-panel').show();
            detailView2.$el.parents('.dashboard-panel').show();
            detailView3.$el.parents('.dashboard-panel').show();
            detailView4.$el.parents('.dashboard-panel').show();
            detailView5.$el.parents('.dashboard-panel').show();
            detailView6.$el.parents('.dashboard-panel').show();
            detailView7.$el.parents('.dashboard-panel').show();
        }
    });

    submittedTokens.on('change:Name', function(){
        // When the token changes...
        if(!submittedTokens.get('Name')) {
            // ... hide the panel if the token is not defined
            detailView8.$el.parents('.dashboard-panel').hide();
            detailView9.$el.parents('.dashboard-panel').hide();
        } else {
            // ... show the panel if the token has a value
            detailView8.$el.parents('.dashboard-panel').show();
            detailView9.$el.parents('.dashboard-panel').show();
        }
    });

    masterView1.on('click', function(e) {
        e.preventDefault();
        var newValue = e.data['row.nodeName'];
        
        // Set the value for the $sourcetype$ token
        unsubmittedTokens.set('nodeName', newValue);
        submittedTokens.set('nodeName', newValue);


    });
     masterView2.on('click', function(e) {
        e.preventDefault();
        var newValue = e.data['row.nodeName'];

        // Set the value for the $sourcetype$ token
        unsubmittedTokens.set('nodeName', newValue);
        submittedTokens.set('nodeName', newValue);
    });

    masterView3.on('click', function(e) {
        e.preventDefault();
        var newValue = e.data['row.Name'];
        
        // Set the value for the $sourcetype$ token
        unsubmittedTokens.set('Name', newValue);
        submittedTokens.set('Name', newValue);


    });

     masterView4.on('click', function(e) {
        e.preventDefault();
        var newValue = e.data['row.Name'];

        // Set the value for the $sourcetype$ token
        unsubmittedTokens.set('Name', newValue);
        submittedTokens.set('Name', newValue);
    });
});
