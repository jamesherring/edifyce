
$(function() {

    var editor = new codeEditorClass($("div#ace-container"));
    editor.editor.session.setMode("ace/mode/python");

    // Get the formal system slug
    var system_id = $("#system_id").text();

    $("#save").on("click", function() {
        AJAX(
            "system/ajax/save/",
            {
                "system_id": system_id,
                "code": editor.editor.getValue()
            },
            function(response) {

                console.log(response);

            }
        )
    })
})