require([
    'underscore',
    'jquery',
    'splunkjs/mvc',
    'splunkjs/mvc/tableview',
    'splunkjs/mvc/simplexml/ready!'
], function(_, $, mvc, TableView) {

    var warningvalue;
    var criticalvalue;
     // Row Coloring Example with custom, client-side range interpretation

    var CustomRangeRenderer = TableView.BaseCellRenderer.extend({
        canRender: function(cell) {
            // Enable this custom cell renderer for both the active_hist_searches and the active_realtime_searches field
            return _(['Health', 'Warning Threshold', 'Critical Threshold']).contains(cell.field);
        },
        render: function($td, cell) {
            // Add a class to the cell based on the returned value
            var value = cell.value;
            // Apply interpretation for number of historical searches
            if (cell.field === 'Health') {
                $td.text(value).addClass('numeric');
                if (value < 80 && value >= 60 ) {
                    $td.addClass('range-cell').addClass('range-elevated');
                }
                if (value <  60 ) { 
                    $td.addClass('range-cell').addClass('range-severe');
                }
	    }


            if (cell.field === 'Warning Threshold') {
		warningvalue = cell.value;
                $td.text(warningvalue).addClass('numeric');
            }

            if (cell.field === 'Critical Threshold') {
	 	criticalvalue = cell.value;
                $td.text(criticalvalue).addClass('numeric');
	    } 
        }
    });

    var CustomRangeRendererUtil = TableView.BaseCellRenderer.extend({
        canRender: function(cell) {
            // Enable this custom cell renderer for both the active_hist_searches and the active_realtime_searches field
            return _(['Egress port utilization', 'Ingress port utilization']).contains(cell.field);
        },
        render: function($td1, cell) {
            // Add a class to the cell based on the returned value
            var value = cell.value;
            // Apply interpretation for number of historical searches

            if (cell.field === 'Egress port utilization') {
        	var UtilValue = cell.value;
                $td1.text(UtilValue).addClass('numeric');

                if (UtilValue >= warningvalue && UtilValue < criticalvalue) {
                    $td1.addClass('range-cell').addClass('range-elevated');
                }
                if (UtilValue >=  criticalvalue ) { 
                    $td1.addClass('range-cell').addClass('range-severe');
                }
	    }

            if (cell.field === 'Ingress port utilization') {
        	var IngressUtilValue = cell.value;
                $td1.text(IngressUtilValue).addClass('numeric');

                if (IngressUtilValue >= warningvalue && IngressUtilValue < criticalvalue) {
                    $td1.addClass('range-cell').addClass('range-elevated');
                }
                if (IngressUtilValue >=  criticalvalue ) { 
                    $td1.addClass('range-cell').addClass('range-severe');
                }
	    }
            
        }
    });


    var elements=['master1','master2','master99','detail1','detail2','detail3','detail4','detail5','detail6','detail7','master3','master4','detail8', 'detail9'];
    
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


   var elements1=['master3','master4','detail8','detail9'];
    
    for (var i=0; i<elements1.length;i++)
    {
         mvc.Components.get(elements1[i]).getVisualization(function(tableView) {
        // Add custom cell renderer
        tableView.table.addCellRenderer(new CustomRangeRendererUtil());
        tableView.on('rendered', function() {
            // Apply class of the cells to the parent row in order to color the whole row
            tableView.$el.find('td1.range-cell').each(function() {
                $(this).parents('tr').addClass(this.className);
            });
        });
        // Force the table to re-render
        tableView.table.render();
      });
   }

});                 

