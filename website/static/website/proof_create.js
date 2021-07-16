
$(function() {

    // Get the formal system id
    var system_id = $("#system_id").text();

    $("#save").on("click", function() {
        AJAX(
            "/proof/ajax/create/",
            {
                "name": $("input[name='name']").val(),
                "description": $("textarea").val(),
                "system_id": system_id
            },
            function(response) {
                // Success - redirect to view the page
                window.location.href = response.url;
            }
        )
    })
})