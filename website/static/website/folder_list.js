
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
})