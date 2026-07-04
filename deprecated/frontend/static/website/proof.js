

$(function() {

    // Get the output div and build a table class in it
    var output_parent = $("#output");
    var output = new proofDisplayClass(output_parent);

     var data = JSON.parse(document.getElementById("proof_data").innerHTML);
     output.populate(data);

     var entry_id = $("#entry_id").text();

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
                window.location.reload();
            }
        );
     });


})


