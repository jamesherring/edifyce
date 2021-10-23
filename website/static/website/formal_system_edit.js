
$(function() {

    var container = $("div#ace-container");
    var editor = new codeEditorClass(container);
    editor.editor.session.setMode("ace/mode/yaml");

    if ($(container).hasClass("uneditable")) {
        // Set the editor to be read-only
        editor.editor.setReadOnly(true);
    }

    function setHeight() {
        // Set the editor height
        var y = $(container).offset().top;
        var height = $(window).height() - y;
        $(container).css("height", String(height) + "px");
        editor.editor.resize();
    }

    setHeight();

    $(window).on("resize", setHeight);

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