function proofDisplayClass(parent) {
    // A class structure for proof displays

    this.clear = function() {
        // Clear the table
        $(this.parent).empty();
    }

    this.populate = function(code, data) {
        // Populate the table with the given code. Provide optional validation data

        // First clear the table
        this.clear();

        // Sort the code into lines
        var lines = code.split("\n");

        // Add a row for each line
        for (var i = 0; i < lines.length; i++) {
            if (data) {
                this.add_row(i + 1, lines[i], data.lines[i]);
            } else {
                this.add_row(i + 1, lines[i]);
            }
        }

    }

    this.add_row = function(line_number, line, data) {
        // Add a row to the table with the given line. Provide optional validation data

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

        if (!data) {
            return;
        }

        // Get validation columns
        var colour = "#F00";
        if (data.valid) {
            if (!data.logical) {
                // Line is valid, but not logical, so no need for any feedback
                return;
            }
            colour = "#0F0";
        }

        var indicator_cell = $("<div class='cell indicator' style='background-color: " + colour + "'></div>");
        $(row).append(indicator_cell);

        if (data.invalid_message) {
            var message_cell = $("<div class='cell'>" + data.invalid_message + "</div>");
            $(row).append(message_cell);
        }

    }

    // Add the parameters and do an initial populate based on the contents of the parent
    this.parent = parent;
    this.populate($(parent).html());

}