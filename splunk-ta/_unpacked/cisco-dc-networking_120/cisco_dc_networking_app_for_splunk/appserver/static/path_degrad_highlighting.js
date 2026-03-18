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

     // Row Coloring Example with custom, client-side range interpretation

    var CustomRangeRenderer = TableView.BaseCellRenderer.extend({
        canRender: function(cell) {
            // Enable this custom cell renderer for both the active_hist_searches and the active_realtime_searches field
            return _(['Total Excess Packets','Total Dropped Packets']).contains(cell.field);
        },
        render: function($td, cell) {
            // Add a class to the cell based on the returned value
            var value = cell.value;
            // Apply interpretation for number of historical searches
            if (cell.field === 'Total Excess Packets') {
                $td.text(value).addClass('numeric');
                if (value > 0 ) {
                    $td.addClass('range-cell').addClass('range-severe');
                }
            }
             if (cell.field === 'Total Dropped Packets') {
                $td.text(value).addClass('numeric');
                if (value > 0 ) {
                    $td.addClass('range-cell').addClass('range-severe');
                }
            }

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

