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

        // Check if the line contains a reference of the form "ref{...}"
        var index = line.indexOf("ref{");

        // Get line variables
        var result = this.get_line_variables(line);
        var vars = result[0];
        line = result[1];

        var ref = "";
        if (vars.ref) {
            // There is a reference
            ref = "(" + vars.ref + ")";
        }

        var label = "";
        if (vars.label) {
            // There is a label
            label = "(" + vars.label + ")";
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

        if (ref) {
            var ref_cell = $("<td>" + ref + "</td>");
            $(row).append(ref_cell);
        }

        if (label || ref) {
            var label_cell = $("<td>" + label + "</td>");
            $(row).append(label_cell);
        }

        if (!data) {
            // No indicator data
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

    this.get_line_variables = function(row, vars) {
        // Get a variable dictionary from the row

        // Create the dictionary
        var vars = vars || {};

        if (!(row.slice(-1) == "}")) {
            return [vars, row];
        }

        // Work backwards to find the corresponding open curly brace

        var index = row.length - 2;
        var depth = 1;
        while (index >= 0) {
            if (row[index] == "{") {
                depth -= 1;
                if (depth == 0) {
                    // Found
                    break;
                }
            } else if (row[index] == "}") {
                depth += 1;
            }
            index--;
        }

        var open_brace_index = index;

        // Work backwards to find the next space
        while (index >= 0) {
            if (row[index] == " ") {
                // Found the space
                break;
            }
            index--;
        }

        // Found the varname
        var varname = row.slice(index + 1, open_brace_index);
        var value = row.slice(open_brace_index + 1, -1);

        vars[varname] = value;

        if (index == -1) {
            return [vars, row];
        }

        // Otherwise trim the row and look for any more vars
        row = row.slice(0, index);

        return this.get_line_variables(row, vars);

    }

    // Add the parameters and do an initial populate based on the contents of the parent
    this.parent = parent;
    this.populate($(parent).html());

}