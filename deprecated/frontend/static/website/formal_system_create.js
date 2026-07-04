
$(function() {

    $("#save").on("click", function() {
        AJAX(
            "/system/ajax/create/",
            {
                "name": $("input[name='name']").val(),
                "description": $("textarea").val()
            },
            function(response) {
                // Success - redirect to view the page
                window.location.href = response.url;
            }
        )
    })
})