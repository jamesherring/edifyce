

$(function() {

    var container = $("div#ace-container");
    var editor = new codeEditorClass(container);
    editor.editor.session.setMode("ace/mode/latex");

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
    output.populate(proof_data);


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
                output.populate(response.data);

                // Parse mathjax
                MathJax.typeset();
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
                output.populate(response.data);

                // Parse mathjax
                MathJax.typeset();

            }
        )
    });




})