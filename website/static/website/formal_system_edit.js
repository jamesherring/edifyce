
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

    var save_button = $("#save > div.button");
    var previous_saved_code = editor.editor.getValue();
    var unsaved = false;

    // Get the formal system id
    var system_id = $("#system_id").text();

    $(save_button).on("click", function() {

        if (!unsaved) {
            // Nothing to save
            return;
        }

        // Disable the save button
        $(save_button).addClass("disabled");
        unsaved = false;

        AJAX(
            "/system/ajax/save/",
            {
                "system_id": system_id,
                "code": editor.editor.getValue()
            },
            function(response) {
                previous_saved_code = editor.editor.getValue();
            }
        );
    });

    editor.editor.session.on("change", function(e) {

        var current_code = editor.editor.getValue();

        // Look for changes and enable the save button if necessary
        if (previous_saved_code == current_code) {
            // Code the same as previously saved
            $(save_button).addClass("disabled");
            unsaved = false;
        } else {
            $(save_button).removeClass("disabled");
            unsaved = true;
        }

    });


    // Look out for unsaved changes
    const unloadPage = () => {
        if (unsaved) {
            return "Careful! You have unsaved changes.";
        }
    };

    window.onbeforeunload = unloadPage;

})