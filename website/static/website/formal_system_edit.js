
$(function() {

    var container = $("div#ace-container");
    var editor = new codeEditorClass(container);
    editor.editor.session.setMode("ace/mode/python");

    // Set the editor height
    var y = $(container).offset().top;
    var height = $(window).height() - y;
    $(container).css("height", String(height) + "px");

    // Get the formal system id
    var system_id = $("#system_id").text();

    $("#save").on("click", function() {
        AJAX(
            "/system/ajax/save/",
            {
                "system_id": system_id,
                "code": editor.editor.getValue()
            },
            function(response) {

                console.log(response);

            }
        )
    });
})