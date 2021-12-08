

$(function() {

    var container = $("div#ace-container");
    var editor = new codeEditorClass(container);

    if ($(container).hasClass("uneditable")) {
        // Set the editor to be read-only
        editor.editor.setReadOnly(true);
    }

    var root_autocomplete = JSON.parse(document.getElementById("root_autocomplete").innerHTML);

    var autocomplete_paths = {};

    // Add custom completion rules
    var staticWordCompleter = {
        getCompletions: function(editor, session, pos, prefix, callback) {

            // Get the current line
            var line = session.getLine(pos["row"]);

            // Trim anything after the cursor
            trimmed = line.substr(0, pos["column"]);

            // Find the final space (if any) and trim anything before it
            trimmed = trimmed.split(" ").pop();

            if ((trimmed.length > 0) && (trimmed.slice(-1) == ".")) {
                var path = trimmed.slice(0, -1);

                if (path in autocomplete_paths) {
                    // We already did an ajax call for this path
                    callback(null, autocomplete_paths[path]);
                    return;
                }

                AJAX(
                    "/proof/ajax/autocomplete/",
                    {
                        "proof_id": proof_id,
                        "path": path
                    },
                    function(response) {
                        autocomplete_paths[path] = response.suggestions;
                        callback(null, response.suggestions);
                    }
                )
            } else {
                callback(null, root_autocomplete);
            }

        }
    }

    editor.editor.completers = [staticWordCompleter];

    // Get the proof and system ids
    var proof_id = $("#proof_id").text();
    var system_id = $("#system_id").text();

    // Get the output div and build a table class in it
    var output_parent = $("#output");
    var output = new proofDisplayClass(output_parent);

    function setHeight() {
        // Set the editor height
        var y = $(container).offset().top;
        var height = $(window).height() - y;
        $(container).css("height", String(height) + "px");
        $(output_parent).css("height", String(height) + "px");
        editor.editor.resize();
    }

    setHeight();

    // Also resize on window change
    $(window).on("resize", setHeight);

    // Get the validation data script
    var proof_data = JSON.parse(document.getElementById("proof_data").innerHTML);
    output.populate(proof_data, false);

    // Add the compile button
    var compile_button = $("#compile-button");
    $(output_parent).append(compile_button);

    var save_button = $("#save > div.button");


    function validate_proof() {
        // Validate the proof

        var compile_button = $("#compile-button");

        // Grey out the output
        $(output_parent).addClass("updating");
        $(compile_button).addClass("hidden");

        AJAX(
            "/proof/ajax/validate/",
            {
                "proof_id": proof_id,
                "code": editor.editor.getValue()
            },
            function(response) {
                // Populate the output with the validation data
                output.populate(response.data, true);

                // Remove the updating styles
                $(output_parent).removeClass("updating");

                // Add the compile button
                $(output_parent).append(compile_button);

                // Update previous_code
                previous_code = editor.editor.getValue();
            }
        )
    }

    var previous_code = editor.editor.getValue();
    var previous_saved_code = previous_code;
    var unsaved = false;

    editor.editor.session.on("change", function(e) {

        var current_code = editor.editor.getValue();
        var compile_button = $("#compile-button");

        // Look for changes and show the compile button if necessary
        if (previous_code == current_code) {
            // Code unchanged
            $(compile_button).addClass("hidden");
        } else {
            $(compile_button).removeClass("hidden");
        }

        if (previous_saved_code == current_code) {
            // Code the same as previously saved
            $(save_button).addClass("disabled");
            unsaved = false;
        } else {
            $(save_button).removeClass("disabled");
            unsaved = true;
        }

    });

    // Re-compile on compile button click
    $(document.body).on("click", "#compile-button", validate_proof);

    // Save the file
    $(save_button).on("click", function() {

        var compile_button = $("#compile-button");

        // Grey out the output
        $(output_parent).addClass("updating");
        $(compile_button).addClass("hidden");
        $(save_button).addClass("disabled");

        AJAX(
            "/proof/ajax/save/",
            {
                "proof_id": proof_id,
                "code": editor.editor.getValue()
            },
            function(response) {
                // Populate the output with the validation data
                output.populate(response.data, true);

                // Remove the updating styles
                $(output_parent).removeClass("updating");

                // Add the compile button
                $(output_parent).append(compile_button);

                // Now saved
                unsaved = false;

                // Update previous_codes
                previous_code = editor.editor.getValue();
                previous_saved_code = previous_code;
            }
        )
    });


    // Look out for unsaved changes
    const unloadPage = () => {
        if (unsaved) {
            return "Careful! You have unsaved changes.";
        }
    };

    window.onbeforeunload = unloadPage;


});