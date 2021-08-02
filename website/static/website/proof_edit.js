

$(function() {

    var container = $("div#ace-container");
    var editor = new codeEditorClass(container);

    var root_autocomplete = JSON.parse(document.getElementById("root_autocomplete").innerHTML);

    // Add custom completion rules
    var staticWordCompleter = {
        getCompletions: function(editor, session, pos, prefix, callback) {

            // Get the current line
            var line = session.getLine(pos["row"]);

            // Trim anything after the cursor
            trimmed = line.substr(0, pos["column"]);

            // Find the final space (if any) and trim anything before it
            trimmed = trimmed.split(" ").pop();

            if (trimmed == "prop.") {
                wordList = ["axioms", "proof1"];

                callback(null, wordList.map(function(word) {
                    return {
                        caption: word,
                        value: word,
                        meta: "static"
                    };
                }));
            } else {
                callback(null, root_autocomplete);
            }

        }
    }

    editor.editor.completers = [staticWordCompleter];


    // Set the editor height
    var y = $(container).offset().top;
    var height = $(window).height() - y;
    $(container).css("height", String(height) + "px");

    // Get the proof and system ids
    var proof_id = $("#proof_id").text();
    var system_id = $("#system_id").text();

    // Get the output div and build a table class in it
    var output_parent = $("#output");
    var output = new proofDisplayClass(output_parent);

    $(output_parent).css("height", String(height) + "px");

    // Get the validation data script
    var proof_data = JSON.parse(document.getElementById("proof_data").innerHTML);
    output.populate(proof_data, false);


    function validate_proof() {
        // Validate the proof

        AJAX(
            "/proof/ajax/validate/",
            {
                "proof_id": proof_id,
                "code": editor.editor.getValue()
            },
            function(response) {
                // Populate the output with the validation data
                output.populate(response.data, true);
            }
        )
    }

    var previous_code = editor.editor.getValue();

    editor.editor.session.on("change", function(e) {
        // Validate the proof 500ms after any changes
        window.clearTimeout(window.timeout);
        window.timeout = setTimeout(validate_proof, 250);

    });


    // Save the file
    $("#save").on("click", function() {
        AJAX(
            "/proof/ajax/save/",
            {
                "proof_id": proof_id,
                "code": editor.editor.getValue()
            },
            function(response) {
                // Populate the output with the validation data
                output.populate(response.data, true);
            }
        )
    });




})