
$(function() {

    var system_id = $("#system_id").text();
    var entry_id = $("#entry_id").text();

    var parent_id = null;
    var e = $("#folder_id");
    if (e.length) {
        parent_id = e.text();
    }

    var create_folder_modal = $("#create-folder-modal");

    // Modal click
    $(create_folder_modal).on("click", function(e) {
        if (e.target == this) {
            // Hide the modal
            $(this).toggleClass("hidden");
        }
    });

    // Show the modal
    $("#create-folder").on("click", function() {
        $(create_folder_modal).toggleClass("hidden");
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


    // Publish buttons
     var confirm_publish_modal = $("#confirm-publish-modal");

     $(".publish-button").on("click", function() {
         // Show the modal
         $(confirm_publish_modal).removeClass("hidden");
     });

     $(confirm_publish_modal).on("click", function(e) {
         if ($(e.target).hasClass("modal-outer")) {
             // Click outside of the modal
             $(confirm_publish_modal).addClass("hidden");
         }
     });

     $(confirm_publish_modal).on("click", ".grey-button", function() {
         // Hide the modal
         $(confirm_publish_modal).addClass("hidden");
     });

     $(confirm_publish_modal).on("click", ".confirm-publish-button", function() {
        // confirm publish
        AJAX(
            "/folderentry/ajax/publish/",
            {
                "entry_id": entry_id
            },
            function(response) {
                console.log(response);

                // Refresh the page

            }
        );
     });

});