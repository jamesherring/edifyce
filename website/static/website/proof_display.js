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

        // Add a table element
        this.table = $("<table></table>");
        $(this.parent).append(this.table);

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
        var row = $("<tr></tr>");
        $(this.table).append(row);

        // Add the row number, line and reference as cells in the table
        // var number_cell = $("<div class='cell line-number'>" + String(line_number) + "</div>");
        // var line_cell = $("<div class='cell'>" + line + "</div>");
        // var ref_cell = $("<div class='cell'>" + ref + "</div>");

        var number_cell = $("<td class='line-number'>" + String(line_number) + "</td>");
        $(row).append(number_cell);

        var line_cell = $("<td>" + line + "</td>");
        if (!ref) {
            // Allow the line to use space in the reference column
            line_cell = $("<td colspan='2' class='allow-wrap'>" + line + "</td>");
        }
        $(row).append(line_cell);

        if (ref) {
            var ref_cell = $("<td>" + ref + "</td>");
            $(row).append(ref_cell);
        }


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

        var indicator_cell = $("<td class='indicator' style='background-color: " + colour + "'></td>");
        $(row).append(indicator_cell);

        if (data.invalid_message) {
            var message_cell = $("<td>" + data.invalid_message + "</td>");
            $(row).append(message_cell);
        }

    }

    // Add the parameters and do an initial populate based on the contents of the parent
    this.parent = parent;
    this.populate($(parent).html());

}