/*
require.config({
    paths: {
        'text': './contrib/text',
        'cisco_dc_networking_app_for_splunk': '../app/cisco_dc_networking_app_for_splunk',
        'prettify': '../app/cisco_dc_networking_app_for_splunk/contrib/prettify'
    },
    shim: {
        'prettify': {
            exports: 'prettyPrint'
        }
    }
});
require([
    'splunkjs/ready!',
    'splunkjs/mvc/utils',
//    'splunkjs/mvc/headerview',
//    'splunkjs/mvc/footerview', 
    'prettify'],
    function(mvc, splunkUtils, HeaderView, FooterView, prettyPrint){
       
        // Initialize common UI - Splunk header and footer
      
        new HeaderView({
            id: 'header',
            el: $('.header'),
        }, {tokens: true}).render();

        new FooterView({
            id: 'footer',
            el: $('.footer')
        }, {tokens: true}).render();

        // Pretty print source code examples on the page
        prettyPrint();
});
*/
