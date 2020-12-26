
$(function() {

    var editor = new codeEditorClass($("div#ace-container"));
    editor.editor.session.setMode("ace/mode/python");

    // Get the formal system slug
    var parts = window.location.pathname.split("/");
    var slug = parts[parts.length - 2];

    $("#save").on("click", function() {
        AJAX(
            "/ajax/save_system/",
            {
                "slug": slug,
                "code": editor.editor.getValue()
            },
            function(response) {

                console.log(response);

            }
        )
    })
})