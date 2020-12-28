
$(function() {

    var editor = new codeEditorClass($("div#ace-container"));
    editor.editor.session.setMode("ace/mode/python");

    // Get the formal system slug
    var system_id = $("#system_id").text();

    $("#save").on("click", function() {
        AJAX(
            "system/ajax/create/",
            {
                "name": $("input[name='name']").val(),
                "code": editor.editor.getValue()
            },
            function(response) {
                // Success - redirect to view the page
                window.location.href = response.url;
            }
        )
    })
})