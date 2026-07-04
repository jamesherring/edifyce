
$(function() {

    var system_id = $("#system_id").text();

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
            "/system/ajax/publish/",
            {
                "system_id": system_id
            },
            function(response) {
                window.location.reload();
            }
        );
     });
})