require([
    'underscore',
    'jquery',
    'splunkjs/mvc',
    'splunkjs/mvc/tableview',
    'splunkjs/mvc/simplexml/ready!'
], function(_, $, mvc, TableView) {

    //change the token values
    
    var tokens = mvc.Components.getInstance("default");
    tokens.on("change:mso_host", function(model, value) {
        tokens.set("form.apic_host","all")
    });

    //remove all from multiselect
    tokens.on("change:severity", function(model, value, options) {
        let arr = value.split(" OR severity=")
        if (arr.length > 1 && arr.includes("*")) {
            if (arr[0] == "*") {
                // if all was selected first, and now selected other, then remove All
                tokens.set("form.severity", arr.slice(1))
            } else {
                // if All is selected later, then remove all the selected and put All
                tokens.set("form.severity", "*")
            }
        }
    })

    //remove None from multiselect
    tokens.on("change:multiTokenQueryDn", function(model, value, options) {
        let arr = value.split(" OR dn=")
        if (arr.length > 1 && arr.includes("")) {
            if (arr[0] == "") {
                // if all was selected first, and now selected other, then remove None
                tokens.set("form.multiTokenQueryDn", arr.slice(1))
            } else {
                // if All is selected later, then remove all the selected and put None
                tokens.set("form.multiTokenQueryDn", "")
            }
        }
    })

    // Row Coloring Example with custom, client-side range interpretation

    var CustomRangeRenderer = TableView.BaseCellRenderer.extend({
        canRender: function(cell) {
            // Enable this custom cell renderer for both the active_hist_searches and the active_realtime_searches field
            return _(['severity']).contains(cell.field);
        },
        render: function($td, cell) {
            // Add a class to the cell based on the returned value
            var value = cell.value;
            // Apply interpretation for number of historical searches
            if (cell.field === 'severity') {
                if (value == 'major') {
                    $td.addClass('range-cell').addClass('range-elevated');
                }
                if (value == 'critical') {
                    $td.addClass('range-cell').addClass('range-severe');
                }
            }

            // Update the cell content
            $td.text(value).addClass('numeric');
        }
    });

    mvc.Components.get('highlight').getVisualization(function(tableView) {
        // Add custom cell renderer
        tableView.table.addCellRenderer(new CustomRangeRenderer());
        tableView.on('rendered', function() {
            // Apply class of the cells to the parent row in order to color the whole row
            tableView.$el.find('td.range-cell').each(function() {
                $(this).parents('tr').addClass(this.className);
            });
        });
        // Force the table to re-render
        tableView.table.render();
    }); 
});
