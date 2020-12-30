

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

    var previous_code = editor.editor.getValue();

    editor.editor.session.on("change", function(e) {

        // Validate the proof 500ms after any changes
        window.clearTimeout(window.timeout);
        window.timeout = setTimeout(validate_proof, 250);

        // Update any reference numberings
        var rows = editor.editor.getValue().split("\n");
        previous_rows = previous_code.split("\n");

        // Calculate the number of rows changed
        var row_delta = rows.length - previous_rows.length;

        if ((row_delta == 0) || (!(e.id))) {
            // No change in row count, or this is an undo action
            previous_code = editor.editor.getValue();
            return;
        }

        // Get the number of identical final rows
        for (var i = 0; i < rows.length; i++) {
            if (previous_rows.length - i - 1 < 0) {
                // No more previous rows
                break
            }

            var row = rows[rows.length - i - 1];
            var previous_row = previous_rows[previous_rows.length - i - 1];

            if (rows[rows.length - i - 1] == previous_rows[previous_rows.length - i - 1]) {
                // Keep incrementing i
                continue
            }

            // Otherwise, break
            break
        }

        var final_identical_rows = i;

        // Look for references in the final identical rows
        for (var i = 0; i < final_identical_rows; i++) {
            var rowNo = rows.length - i - 1;
            var row = rows[rowNo];

            var index = row.indexOf("ref{");

            if (index == -1) {
                // No reference
                continue;
            }

            // Find the closing }
            var close_index = index + row.substr(index).indexOf("}");

            // Get the inner reference
            var inner = row.slice(index + 4, close_index);

            // Split by comma
            var parts = inner.split(", ");
            var new_parts = [];
            for (var j = 0; j < parts.length; j++) {
                if (isNaN(parts[j])) {
                    // Not a number
                    new_parts.push(parts[j])
                    continue;
                }

                var int = Number(parts[j]);

                // Check if it needs changing
                if (((row_delta < 0) && (int > e.end.row)) || (row_delta > 0) && (int > e.start.row)) {
                    // Add row delta
                    new_parts.push(String(int + row_delta));
                } else {
                    new_parts.push(parts[j]);
                }
            }

            var new_inner = new_parts.join(", ");

            if (!(new_inner == inner)) {
                // Make the replacement
                editor.editor.session.replace(new ace.Range(rowNo, index + 4, rowNo, close_index), new_inner);
            }

        }

        previous_code = editor.editor.getValue();

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