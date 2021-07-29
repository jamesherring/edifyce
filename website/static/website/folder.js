
$(function() {

    var system_id = $("#system_id").text();

    var parent_id = null;
    var e = $("#folder_id");
    if (e.length) {
        parent_id = e.text();
    }

    // Modal click
    $("div.modal-outer").on("click", function(e) {
        if (e.target == this) {
            // Hide the modal
            $(this).toggleClass("hidden");
        }
    });

    // Show the modal
    $("#create-folder").on("click", function() {
        var modal = $("div.modal-outer");
        $(modal).toggleClass("hidden");
    });

    $("#create-folder-button").on("click", function() {
        var name = $("#folder-name-input").val();

        if (name == "") {
            return;
        }

        var data = {
            "name": name,
            "system_id": system_id,
        }

        if (parent_id) {
            data["parent_id"] = parent_id;
        }

        AJAX(
            "/folder/ajax/create/",
            data,
            function(response) {
                // Success - redirect to view the folder
                window.location.href = response.folder_url;
            }
        )
    });
})