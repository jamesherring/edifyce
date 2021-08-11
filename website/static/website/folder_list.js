
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

        // The folder depth of this row
        var depth = Number($(row).data("depth") || 0);

        // Check if the group of rows already exists
        var group = $(row).nextUntil("[data-depth=" + String(depth) + "]");
        if (group.length > 0) {
            if ($(group[0]).hasClass("hidden")) {
                // First entry is hidden so the folder must be collapsed. Need to expand to show the next level
                $(group).filter("[data-depth=" + String(depth + 1) + "]").removeClass("hidden");
            } else {
                // First entry is visible so the folder must be open. Need to collapse it.
                $(group).addClass("hidden");
            }
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

                var sub_table = $(response.html);

                // Get the rows (ignoring header row)
                var rows = $(sub_table).find(".table-row").slice(1);

                // Remove cells with wrong name
                var previousRow = row;
                for (var i = 0; i < rows.length; i++) {
                    var new_row = rows[i];

                    // Set the depth
                    $(new_row).attr("data-depth", depth + 1);

                    var cells = $(new_row).find(".table-cell");

                    for (var j = 0; j < cells.length; j++) {
                        var cell = cells[j];
                        var name = $(cell).data("name");

                        if (!columns.includes(name)) {
                            // This cell is not included
                            $(cell).remove();
                            continue;
                        }

                        if (name == "order") {
                            // Don't order sub-files
                            $(cell).remove();
                            continue;
                        }

                        // Increase margin
                        if (name == "name") {
                            $(cell).css("padding-left", String((depth + 1) * 2) + "rem");
                        }
                    }

                    // Add the row
                    $(new_row).insertAfter(previousRow);
                    previousRow = new_row;
                }

            }
        )

    });
})