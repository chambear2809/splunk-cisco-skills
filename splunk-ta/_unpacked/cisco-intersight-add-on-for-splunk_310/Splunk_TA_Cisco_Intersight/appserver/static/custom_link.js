require([
    'splunkjs/mvc',
    'splunkjs/mvc/tableview',
    'splunkjs/mvc/simplexml/ready!'
], function(mvc, TableView) {
    function safeExternalUrl(rawUrl) {
        try {
            var parsed = new URL(rawUrl, window.location.origin);
            if (parsed.protocol !== 'https:') {
                return null;
            }
            return parsed.toString();
        } catch (e) {
            return null;
        }
    }

    // Get the table component by ID
    var advisory_link_table = mvc.Components.get("advisory_link_table");

    addViewButton = TableView.BaseCellRenderer.extend({
        canRender: function (cell) {
            return true
        },
        render: function ($td, cell) {
            // creating cell with View button.
            if(cell.field == "Name"){
                var name = cell.value.split("_-_")[0];
                var link_to_redirect = cell.value.split("_-_")[1];
                $td.empty();
                var button = $("<button type='button' class='click_button'></button>").text(name);
                button.on('click', function () {
                    var redirect_url = safeExternalUrl(link_to_redirect);
                    if (redirect_url) {
                        window.open(redirect_url, '_blank', 'noopener,noreferrer');
                    }
                });
                $td.append(button);
            }
            else{
                $td.text(cell.value || "");
            }
        }
    });

    if (advisory_link_table !== undefined) {
        advisory_link_table.getVisualization(function (tableView) {
            console.log("advisory_link_table:", tableView)
            // Add custom cell renderer and force re-render.
            tableView.table.addCellRenderer(new addViewButton());
            tableView.table.render();
        });
    }
});