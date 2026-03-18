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
            return _(['Health']).contains(cell.field);
        },
        render: function($td, cell) {
            // Add a class to the cell based on the returned value
            var value = cell.value;
            // Apply interpretation for number of historical searches
            if (cell.field === 'Health') {
                $td.text(value).addClass('numeric');
                if (value <= 80 && value > 60 ) {
                    $td.addClass('range-cell').addClass('range-elevated');
                }
                if (value <  60 ) {
                    $td.addClass('range-cell').addClass('range-severe');
                }
            }

        }
    });
    var elements=['detail2'];

    for (var i=0; i<elements.length;i++)
    {
         mvc.Components.get(elements[i]).getVisualization(function(tableView) {
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
   }

    var elements=['detail1'];
    
    for (var i=0; i<elements.length;i++)
    {
         mvc.Components.get(elements[i]).getVisualization(function(tableView) {
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
   }  

});


