
function outputTableClass(parent) {
        // A class structure for the output table

        this.parent = parent;

        this.clear = function() {
            // Clear the table
            $(this.parent).empty();
        }

        this.populate = function(code) {
            // Populate the table with the given code

            // First clear the table
            this.clear();

            // Sort the code into lines
            var lines = code.split("\n");

            // Add a row for each line
            for (var i = 0; i < lines.length; i++) {
                this.add_row(i + 1, lines[i]);
            }

        }

        this.add_row = function(line_number, line) {
            // Add a row to the table with the given line

            // First trim trailing whitespace
            line = line.replace(/\s+$/, "");

            // Assume no reference by default
            var ref = "";

            // Check if the line ends with a reference of the form "ref{...}"
            if (line.slice(-1) == "}") {
                // Work backwards to find the corresponding open curly brace

                var index = line.length - 2;
                var depth = 1;
                while (index >= 0) {
                    if (line[index] == "{") {
                        depth -= 1;
                        if (depth == 0) {
                            // Found
                            break;
                        }
                    } else if (line[index] == "}") {
                        depth += 1;
                    }
                    index -= 1;
                }

                if ((index - 3 >= 0) && (line.substr(index - 3, 3) == "ref")) {
                    // This is a reference
                    ref = "(" + line.slice(index + 1, -1) + ")";

                    // Remove the reference from the end of the line
                    line = line.substr(0, index - 3);
                }
            }

            // Add a row div
            var row = $("<div class='row'></div>");
            $(this.parent).append(row);

            // Add the row number, line and reference as cells in the table
            var number_cell = $("<div class='cell line-number'>" + String(line_number) + "</div>");
            var line_cell = $("<div class='cell'>" + line + "</div>");
            var ref_cell = $("<div class='cell'>" + ref + "</div>");

            $(row).append(number_cell);
            $(row).append(line_cell);
            $(row).append(ref_cell);

        }

    }


$(function() {

    var editor = new codeEditorClass($("div#ace-container"));
    editor.editor.session.setMode("ace/mode/latex");

    // Get the proof id
    var proof_id = $("#proof_id").text();

    // Get the output div and build a table class in it
    var output_parent = $("#output");
    output = new outputTableClass(output_parent);

    // Populate it with the editor code
    output.populate(editor.editor.getValue());

    function startTimeout() {
        window.timeout = setTimeout(function() {
            // Repopulate the output and parse mathjax
            output.populate(editor.editor.getValue());
            MathJax.typeset();
        }, 500);
    }

    editor.editor.session.on("change", function() {
        // Restart the timeout
        window.clearTimeout(window.timeout);
        startTimeout();
    });


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