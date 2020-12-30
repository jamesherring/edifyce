

$(function() {

    var editor = new codeEditorClass($("div#ace-container"));
    editor.editor.session.setMode("ace/mode/latex");

    // Get the proof and system ids
    var proof_id = $("#proof_id").text();
    var system_id = $("#system_id").text();

    // Get the output div and build a table class in it
    var output_parent = $("#output");
    var output = new proofDisplayClass(output_parent);

    // Get the validation data script
    var validation = JSON.parse(document.getElementById("validation").innerHTML);
    output.populate(editor.editor.getValue(), validation);


    function validate_proof() {
        // Validate the proof
        AJAX(
            "/proof/ajax/validate/",
            {
                "system_id": system_id,
                "code": editor.editor.getValue()
            },
            function(response) {

                // Populate the output with the validation data
                output.populate(editor.editor.getValue(), response.validation);

                // Parse mathjax
                MathJax.typeset();
            }
        )
    }

    editor.editor.session.on("change", function() {
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

                console.log(response);

            }
        )
    });




})