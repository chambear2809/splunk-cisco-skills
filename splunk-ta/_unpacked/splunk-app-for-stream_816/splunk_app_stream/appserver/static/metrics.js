require([
    'jquery',
    'underscore',
    'splunkjs/mvc/searchmanager',
    'splunkjs/mvc',
    'splunkjs/mvc/simplexml/ready!'
],function($, _, SearchManager, mvc) {

    /** Get a reference to all the search managers on the dashboard page
     ** and set the auto_cancel and max_time properties
     */

    _(mvc.Components.toJSON()).chain().filter(function(el) {
        return el instanceof SearchManager;
    }).each(function(searchMgr){
        try {
            searchMgr.settings.set("auto_cancel", 8);
            searchMgr.settings.set("max_time", 4);
        } catch(e) {
            console.log("unable to set auto_cancel and max_time for dashboards.");
        }
    });

});
