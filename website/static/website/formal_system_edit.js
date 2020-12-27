
$(function() {

    var editor = new codeEditorClass($("div#ace-container"));
    editor.editor.session.setMode("ace/mode/python");

    // Get the formal system slug
    var slug = $("#slug").text();

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