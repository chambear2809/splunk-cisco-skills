require(["splunkjs/mvc", "splunkjs/mvc/simplexml/ready!"], function (mvc) {
  function setupMultiInput(instance_id) {
    // Get multiselect
    var multi = mvc.Components.get(instance_id);

    // On change, check selection
    multi.on("change", (selectedValues) => {
      if (selectedValues.length > 1 && selectedValues.includes("*")) {
        var indexOfAll = selectedValues.indexOf("*");

        // If "ALL" was selected before current (more specific) selection, remove it from list
        if (indexOfAll == 0) {
          selectedValues.splice(indexOfAll, 1);
          multi.val(selectedValues);
          multi.render();
        } else {
          // "ALL" was selected last, clear input and leave only "ALL" in it
          multi.val("*");
          multi.render();
        }
      }
    });
  }

  var all_multi_selects = document.getElementsByClassName("input-multiselect");
  for (const select of all_multi_selects) {
    setupMultiInput(select.id);
  }
});
