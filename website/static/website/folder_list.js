
$(function() {

    // Move folder entries
    $("div.table-row .move-arrow").on("click", function(e) {

        var row = $(this).parents(".table-row")[0];
        var entry_id = $(row).data("id");

        var direction = "down";
        if ($(this).hasClass("move-up")) {
            direction = "up";
        }

        AJAX(
            "/folderentry/ajax/move/",
            {
                "entry_id": entry_id,
                "direction": direction
            },
            function(response) {
                // Success - refresh the page
                window.location.reload();
            }
        )
    });

    // Expand/collapse folders
    $("div.table").on("click", "div.table-cell span.expand-folder", function(e) {

        var row = $(this).parents(".table-row")[0];
        var entry_id = $(row).data("id");

        // Check if the group already exists
        var group = $(this).parents(".table").find("div.table-row-group[data-parent='" + entry_id + "']");
        if (group.length > 0) {
            $(group).toggleClass("hidden");
            return;
        }

        var headers = $(this).parents(".table").find(".header-row .table-cell");
        var columns = $(headers).map(function() {
            return $(this).data("name");
        }).get();

        AJAX(
            "/folder/ajax/expand/",
            {
                "entry_id": entry_id
            },
            function(response) {
                // Append the rows

                // Create a row group
                var row_group = $("<div class='table-row-group' data-parent='" + entry_id + "'></div>");

                var sub_table = $(response.html);

                // Get the rows (ignoring header row)
                var rows = $(sub_table).find(".table-row").slice(1);

                // Remove cells with wrong name
                for (var i = 0; i < rows.length; i++) {
                    var new_row = rows[i];
                    var cells = $(new_row).find(".table-cell");
                    for (var j = 0; j < cells.length; j++) {
                        var cell = cells[j];
                        var name = $(cell).data("name");
                        if (!columns.includes(name)) {
                            // This cell is not included
                            $(cell).remove();
                        }

                        // Increase margin
                        if (name == "name") {
                            $(cell).css("padding-left", "+=2rem");
                        }
                    }

                    // Add the row
                    $(row_group).append(new_row);
                }

                // Add the row group
                $(row_group).insertAfter(row);

            }
        )

    });
})