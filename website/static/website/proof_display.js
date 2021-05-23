function proofDisplayClass(parent) {
    // A class structure for proof displays

    this.clear = function() {
        // Clear the table
        $(this.parent).empty();
    }

    this.populate = function(data) {
        // Populate the table with the given data.

        // First clear the table
        this.clear();

        // Add a table element
        this.table = $("<table></table>");
        $(this.parent).append(this.table);

        // Add a row for each line
        for (var i = 0; i < data.lines.length; i++) {
            this.add_row(i + 1, data.lines[i]);
        }

    }

    this.add_row = function(line_number, data) {
        // Add a row to the table with the given line. Provide optional validation data

        // Get the display value and trim trailing whitespace
        var line = " ".repeat(data.indent) + data.display.replace(/\s+$/, "");

        // Check if the line contains a reference of the form "ref{...}"
        var index = line.indexOf("ref{");

        // Get label and reference if they exist
        var ref = "";
        if (data.reference) {
            // There is a reference
            ref = "(" + data.reference + ")";
        }

        var label = "";
        if (data.label) {
            // There is a label
            label = "(" + data.label + ")";
        }

        // Calculate the colspan.
        var colspan = 1;
        if (!ref) {
            colspan++;
            if (!label) {
                colspan++;
            }
        }

        // Add a row div
        var row = $("<tr></tr>");
        $(this.table).append(row);

        var number_cell = $("<td class='line-number'>" + String(line_number) + "</td>");
        $(row).append(number_cell);

        var line_cell = $("<td>" + line + "</td>");
        if (!ref) {
            // Allow the line to use space in the reference column
            line_cell = $("<td colspan='" + String(colspan) + "' class='allow-wrap'>" + line + "</td>");
        }
        $(row).append(line_cell);

        if (data && data.line_name == "comment") {
            $(line_cell).addClass("comment");
        }

        if (ref) {
            var ref_cell = $("<td>" + ref + "</td>");
            $(row).append(ref_cell);
        }

        if (label || ref) {
            var label_cell = $("<td>" + label + "</td>");
            $(row).append(label_cell);
        }

        // Get validation columns
        var colour = "#F00";
        var message = data.invalid_message;
        if (data.valid) {
            if (!(["logical", "import"].includes(data.behaviour))) {
                // Line is valid, but not logical or import, so no need for any feedback
                return;
            }
            colour = "#0F0";
        }

        if ((data.valid) && (data.warning_message)) {
            // There is a warning message
            colour = "#FFA500";
            message = data.warning_message;
        }

        var indicator_cell = $("<td class='indicator' style='background-color: " + colour + "'></td>");
        $(row).append(indicator_cell);


        if (message) {
            var message_cell = $("<span class='tooltiptext'>" + message + "</span>");
            $(indicator_cell).append(message_cell);
            $(indicator_cell).addClass("tooltip");
        }

    }

    this.parent = parent;

}