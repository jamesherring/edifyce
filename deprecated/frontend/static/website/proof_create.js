
$(function() {

    // Get the formal system id
    var system_id = $("#system_id").text();
    var folder_id = $("#folder_id").text();

    $("#save").on("click", function() {

        data = {
            "name": $("input[name='name']").val(),
            "description": $("textarea").val(),
            "system_id": system_id
        }

        if (folder_id.length > 0) {
            data["folder_id"] = folder_id;
        }

        AJAX(
            "/proof/ajax/create/",
            data,
            function(response) {
                // Success - redirect to view the page
                window.location.href = response.url;
            }
        );

    })
})