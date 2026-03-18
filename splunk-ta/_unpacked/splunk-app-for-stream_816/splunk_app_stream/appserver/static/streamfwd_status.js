require([
    'underscore',
    'jquery',
    'splunkjs/mvc',
    'splunkjs/mvc/tableview',
    'splunkjs/mvc/simplexml/ready!'
], function(_, $, mvc, TableView) {

    var CustomTimeRenderer = TableView.BaseCellRenderer.extend({
        canRender: function (cell) {
            return cell.field === 'Phone Home';
        },

        render: function ($td, cell) {
            var phoneHome = cell.value;

            if (phoneHome < 60) {
                phoneHome = String(Math.round(phoneHome));
                phoneHome += phoneHome === '1' ? ' second ago' : ' seconds ago';
            } else if (phoneHome < 3600) {
                phoneHome = String(Math.round(phoneHome / 60));
                phoneHome += phoneHome === '1' ? ' minute ago' : ' minutes ago';
            } else if (phoneHome < 86400) {
                phoneHome = String(Math.round(phoneHome / 3600));
                phoneHome += phoneHome === '1' ? ' hour ago' : ' hours ago';
            } else {
                phoneHome = String(Math.round(phoneHome / 86400));
                phoneHome += phoneHome === '1' ? ' day ago' : ' days ago';
            }

            $td.append(phoneHome);
        }
    });

    var CustomStatusRenderer = TableView.BaseCellRenderer.extend({
        canRender: function (cell) {
            return cell.field === 'Status';
        },

        render: function ($td, cell) {
            var status = cell.value;
            var icon = '';

            if (status === 'Error' || status === 'Inactive') {
                icon = 'alert-circle';
            } else if (status === 'Warning' || status === 'Idle') {
                icon = 'alert';
            } else if (status === 'Active') {
                icon = 'check';
            }

            $td.addClass('icon-inline numeric').html(_.template('<i class="icon-<%-icon%>"></i> <%- text %>', {
                icon: icon,
                text: cell.value
            }));
        }
    });

    mvc.Components.get('streamfwdTable').getVisualization(function (tableView) {
        tableView.addCellRenderer(new CustomTimeRenderer());
        tableView.addCellRenderer(new CustomStatusRenderer());
    });
});
