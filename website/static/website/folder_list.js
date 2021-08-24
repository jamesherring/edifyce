
$(function() {

    var tableClass = function(table) {
        var self = this;

        // The table element
        this.table_element = table;

        // Whether the table is editable
        this.editable = $(table).data("editable") == true;

        // The row instances
        this.rows = [];

        // Get the column names
        var headers = $(table).find(".header-row .table-cell");
        this.columns = $(headers).map(function() {
            return $(this).data("name");
        }).get();

        // Dragging dictionary
        this.dragging = {
            "status": "none",
            "target": null,
            "rows": null,
            "startY": null,
            "minDelta": null,
            "maxDelta": null,
        };

        this.header = function() {
            return $(this.table_element).children(".header-row");
        }

        this.last_row = function() {
            return this.rows[this.rows.length - 1];
        }

        this.row_elements = function() {
            // Return all rows elements (ignoring the header row)
            return $(this.table_element).children(".table-row").slice(1);
        }

        this.add_row = function(row_element) {
            // Add a row

            // Create the row instance
            var row = new rowClass(this, row_element);

            // Don't check the row depth
            this.rows.push(row);
        }

        this.add_row_at_index = function(row, index) {
            // Add the given row instance at the given index

            // Remove the row from its original parent
            row.remove_from_parent();

            this.rows.splice(index, 0, row);
            row.parent_row = null;

            var previous = this.header();
            if (index > 0) {
                previous = this.rows[index - 1].group().last();
            }

            // Update the DOM
            $(row.group()).insertAfter(previous);

            // Update the depth
            row.set_depth(0);

        }

        if (this.editable) {
            $(document).on("mousemove", function(e) {

                var dragging = self.dragging;

                if (!(dragging.status == "dragging")) {
                    // Not dragging anything
                    return;
                }

                // Calculate the delta
                var delta = e.clientY - dragging.startY;
                delta = Math.min(delta, dragging.maxDelta);
                delta = Math.max(delta, dragging.minDelta);

                // Move the rows
                $(dragging.rows).css("top", String(delta) + "px");

                // Flag if a swap is made
                var dom_swap = false;
                var swapHeight = 0;

                if (dragging.threshold_above && (delta < dragging.threshold_above)) {
                    // Move up
                    dragging.target.insert_before(dragging.row_above);

                    dom_swap = true;
                    swapHeight = dragging.row_above.height();

                }

                if ((dragging.intermediate_thresholds_above) && (delta < 0) && (!(dom_swap))) {
                    // Check for intermediate places to swap above - changes depth but no dom swap

                    var target_row = null;
                    for (var i = 0; i < dragging.intermediate_thresholds_above.length; i++) {
                        var sub_threshold = dragging.intermediate_thresholds_above[i][0];
                        var row = dragging.intermediate_thresholds_above[i][1];

                        if (delta < sub_threshold) {
                            target_row = row;
                        }
                    }

                    if (target_row) {
                        // Add target to target row if it isn't already there
                        if (dragging.target.parent_row !== target_row) {
                            target_row.add_row_at_index(dragging.target, "last");
                        }
                    } else {
                        // Check if we need to return to default
                        if (dragging.target.parent_row !== dragging.original_parent_row) {
                            if (dragging.original_parent_row) {
                                dragging.original_parent_row.add_row_at_index(dragging.target, dragging.original_index);
                            } else {
                                self.add_row_at_index(dragging.target, dragging.original_index);
                            }
                        }
                    }
                }

                if (dragging.threshold_below && (delta > dragging.threshold_below)) {
                    // Move down

                    if (dragging.row_below.type == "proof") {
                        // Simple swap
                        dragging.target.insert_after(dragging.row_below);
                        swapHeight = -dragging.row_below.height();

                    } else {
                        // Folder is below
                        if (dragging.row_below.status == "expanded") {
                            // Add at the top
                            dragging.target.insert_after(dragging.row_below);
                        } else {
                            // Folder is closed - need to include it at the bottom
                            dragging.row_below.add_row_at_index(dragging.target, "last");

                            if (dragging.row_below.status == "default") {
                                // The row is currently unopened
                            }
                        }
                    }

                    dom_swap = true;
                    swapHeight = -dragging.row_below.height();

                }

                if ((dragging.intermediate_thresholds_below) && (delta > 0) && (!(dom_swap))) {
                    // Check for intermediate places to swap below - changes depth but no dom swap

                    var target_row = null;
                    for (var i = 0; i < dragging.intermediate_thresholds_below.length; i++) {
                        var sub_threshold = dragging.intermediate_thresholds_below[i][0];
                        var row = dragging.intermediate_thresholds_below[i][1];

                        if (delta > sub_threshold) {
                            target_row = row;
                        }
                    }

                    if (target_row) {
                        // Add target to the position after target row if it isn't already there
                        if (dragging.target.parent_row !== target_row.parent_row) {
                            dragging.target.insert_after(target_row, true);
                        }
                    } else {
                        // Check if we need to return to default
                        if (dragging.target.parent_row !== dragging.original_parent_row) {
                            if (dragging.original_parent_row) {
                                dragging.original_parent_row.add_row_at_index(dragging.target, dragging.original_index);
                            } else {
                                self.add_row_at_index(dragging.target, dragging.original_index);
                            }
                        }
                    }
                }

                if (dom_swap) {
                    // Rows have been swapped in the dom

                    // Update the row position
                    $(self.dragging.rows).css("top", String(delta + swapHeight) + "px");

                    // Recalculate dragging parameters
                    dragging.target.calculate_dragging_parameters(e, delta + swapHeight);

                }

            });

            $(document).on("mouseup", function(e) {
                var dragging = self.dragging;

                if (!(dragging.status == "dragging")) {
                    // Not dragging anything
                    return;
                }

                // Drop
                dragging.status = "none";

                // Remove the relative position
                $(dragging.rows).css("position", "static");
                $(dragging.rows).css("top", "");
                $(dragging.rows).css("background-color", "");

                var target = dragging.target;

                if ((target.parent_row == dragging.start_parent_row) && (target.index() == dragging.start_index)) {
                    // No change
                    return;
                }

                // Push the update to the backend
                var parent_id = "root";
                if (target.parent_row) {
                    parent_id = target.parent_row.entry_id;
                }

                var index = target.index();
                if ((target.parent_row) && (target.parent_row.status == "default")) {
                    // Add target at the end
                    index = "last";
                }

                AJAX(
                    "/folderentry/ajax/move/",
                    {
                        "entry_id": target.entry_id,
                        "target_parent_id": parent_id,
                        "index": index
                    },
                    function(response) {
                    }
                );

                // Check if we dropped it into a collapsed folder
                if ((target.parent_row) && (!target.parent_row.is_empty)) {
                    if (target.parent_row.status == "default") {
                        // Remove the row entirely - we haven't fetched the other child rows
                        target.remove_from_parent();
                        $(dragging.rows).remove();
                    } else if (target.parent_row.status == "collapsed") {
                        // Just hide the row
                        target.collapse();
                        target.hide();
                    }
                }

            });
        }


        this.initialise = function() {
            // Check for existing rows
            var row_elements = this.row_elements();

            for (var i = 0; i < row_elements.length; i++) {
                var row_element = row_elements[i];

                this.add_row(row_element);
            }
        }

        this.initialise();


    }


    var rowClass = function(table, row_element) {
        var self = this;

        // The table class
        this.table = table;

        // The row element
        this.row = row_element;

        this.entry_id = $(row_element).data("id");
        this.is_empty = $(row_element).data("empty");

        // What type of entry this is ("proof", "folder")
        this.type = $(row_element).data("type");

        // The depth of this row
        this.depth = Number($(row_element).data("depth")) || 0;

        // The parent row (if any)
        this.parent_row = null;

        // Child rows
        this.rows = [];

        // Status of sub-rows ("default", "expanded", "collapsed")
        this.status = "default";

        this.text = function() {
            return $(this.row).find(".table-cell[data-name='name'] a").html();
        }

        this.index = function() {
            if (this.parent_row) {
                return this.parent_row.rows.indexOf(self);
            }
            return this.table.rows.indexOf(self);
        }

        this.update_expand_button = function() {
            // Update the expand button based on the number of child rows
            if (this.is_empty) {
                $(this.row).find("span.expand-folder").addClass("hidden");
            } else {
                $(this.row).find("span.expand-folder").removeClass("hidden");
            }
        }

        this.remove_from_parent = function() {
            // Remove this row from the current parent
            var parent_rows = this.table.rows;
            if (this.parent_row) {
                parent_rows = this.parent_row.rows;
            }

            if (parent_rows.indexOf(this) > -1) {
                parent_rows.splice(this.index(), 1);
            }

            // Check if the parent folder now has no child rows
            if ((this.parent_row) && (this.parent_row.status !== "default")) {
                if (parent_rows.length == 0) {
                    this.parent_row.is_empty = true;
                    this.parent_row.status = "collapsed";
                }
                this.parent_row.update_expand_button();
            }

            this.parent_row = null;
        }

        this.last_row = function() {
            // Get the last child row
            if (this.rows.length == 0) {
                return null;
            }
            return this.rows[this.rows.length - 1];
        }

        this.previous_sibling = function() {
            // Get the previous visible sibling row if it exists

            var index = this.index();
            if (index == 0) {
                return null;
            }

            var parent_rows = this.table.rows;
            if (this.parent_row) {
                parent_rows = this.parent_row.rows;
            }

            return parent_rows[index - 1];

        }

        this.row_boundaries_above = function() {
            // Return a list of rows with group boundaries immediately above this row

            if ((this.index() == 0) || ((this.parent_row) && (this.parent_row.status !== "expanded"))) {
                // The first child, or the child of a parent row which is not expanded.
                // Just use the parent row
                if (this.parent_row) {
                    return [this.parent_row];
                } else {
                    return [];
                }
            }

            // Otherwise, there are previous siblings
            var result = [this.previous_sibling()];

            // Append children if expanded
            last_child = result[0];
            while ((last_child) && (last_child.status == "expanded")) {
                // It's an expanded row
                var next = last_child.last_row();
                if (next) {
                    result.push(next);
                }
                last_child = next;
            }

            return result;

        }

        this.row_boundaries_below = function() {
            // Get the row boundaries (end of folders or entries) immediately below this row group

            if (this.parent_row == null) {
                // no parent row
                return [];
            }

            var parent_rows = this.parent_row.rows;
            if (parent_rows[parent_rows.length - 1] == this) {
                // This is the last row in the parent - use all the parent row boundaries below and add parent
                var result = this.parent_row.row_boundaries_below();
                result.splice(0, 0, this.parent_row);
                return result;
            }

            // Otherwise, no boundaries below
            return [];
        }

        this.next_sibling = function() {
            // Get the next sibling in the table - escalating to parent folders if needed
            var index = this.index();
            if (this.parent_row) {
                if (index + 1 < this.parent_row.rows.length) {
                    // Found the next sibling
                    return this.parent_row.rows[index + 1];
                }

                // Otherwise, this is the last sibling
                return this.parent_row.next_sibling();
            }

            // Otherwise, we are on the root level
            if (index + 1 < this.table.rows.length) {
                // Found the next sibling
                return this.table.rows[index + 1];
            }

            // Otherwise, no next sibling
            return null;
        }

        this.add_row = function(row_element) {
            // Add a child row

            // Create the row instance
            var child_row = new rowClass(this.table, row_element);

            child_row.parent_row = this;
            child_row.set_depth(this.depth + 1);

            // Add the row to the DOM
            if (this.rows.length == 0) {
                // No child rows yet
                $(child_row.row).insertAfter(this.row);
            } else {
                // Insert at the end
                $(child_row.row).insertAfter(this.last_row().row);
            }

            this.rows.push(child_row);

            this.update_expand_button();

        }

        this.add_row_at_index = function(row, index) {
            // Add the given row at the given index.

            // First remove row from the parent rows
            row.remove_from_parent();

            if (index == "last") {
                // Add at the end
                index = this.rows.length;
            }

            this.rows.splice(index, 0, row);
            row.parent_row = this;

            // Get the previous row in the DOM
            var previous = this.row;
            if (index > 0) {
                previous = this.rows[index - 1].group().last();
            }

            // Update the DOM
            $(row.group()).insertAfter(previous);

            // Update the depth
            row.set_depth(this.depth + 1);

            if ((this.is_empty) && (this.rows.length == 1)) {
                // We just added a row into an empty folder
                this.is_empty = false;
                this.status = "expanded";
            }

            // Update the expand button
            this.update_expand_button();

        }

        this.set_depth = function(depth) {
            this.depth = depth;
            $(this.row).attr("data-depth", depth);

            // Update style for depth
            var name_cell = $(this.row).find(".table-cell[data-name='name']");

            if (depth == 0) {
                $(name_cell).css("padding-left", "");
            } else {
                $(name_cell).css("padding-left", String((depth * 1.5) + 0.8) + "rem");
            }

            // Update depth of child rows
            for (var i = 0; i < this.rows.length; i++) {
                this.rows[i].set_depth(depth + 1);
            }
        }

        this.hide = function() {
            $(this.row).addClass("hidden");
        }

        this.show = function() {
            $(this.row).removeClass("hidden");
        }

        this.toggle_folder = function() {
            if (this.status == "expanded") {
                this.collapse();
            } else {
                this.expand();
            }
        }

        this.collapse = function() {
            // Collapse and hide the child rows
            for (var i = 0; i < this.rows.length; i++) {
                var row = this.rows[i];
                row.collapse();
                row.hide();
            }

            if (this.rows.length > 0) {
                this.status = "collapsed";
            }
        }

        this.expand = function() {
            // Expand this row as a folder

            if (this.status == "collapsed") {
                // Just need to show child rows
                for (var i = 0; i < this.rows.length; i++ ) {
                    this.rows[i].show();
                }

                this.status = "expanded";
                return;
            }

            // status is default - we need to get the child rows with ajax
            AJAX(
                "/folder/ajax/expand/",
                {
                    "entry_id": this.entry_id
                },
                function(response) {
                    // Append the rows

                    var sub_table = $(response.html);

                    // Get the rows (ignoring header row)
                    var rows = $(sub_table).find(".table-row").slice(1);

                    // Remove cells with mismatched column names
                    for (var i = 0; i < rows.length; i++) {
                        var new_row = rows[i];

                        var cells = $(new_row).find(".table-cell");
                        for (var j = 0; j < cells.length; j++) {
                            var cell = cells[j];
                            var name = $(cell).data("name");

                            if (!self.table.columns.includes(name)) {
                                // This cell is not included
                                $(cell).remove();
                                continue;
                            }
                        }

                        // Add the row
                        self.add_row(new_row);

                        self.status = "expanded";
                    }

                }
            )

        }

        this.insert_before = function(other) {
            // Insert this (and any child rows) before another row instance - on the same depth level as other.

            this.remove_from_parent();

            // Now add to the new parent
            var index = other.index();
            if (other.parent_row) {
                other.parent_row.add_row_at_index(this, index);
                return;
            }

            other.table.add_row_at_index(this, index);

        }

        this.insert_after = function(other, skip_child_rows=false) {
            // Insert this (and any child rows) after another row instance.
            // Optionally skip the child rows on other if it is expanded

            if (!(skip_child_rows) && (other.type == "folder")) {
                // Other is a folder
                if (other.status == "expanded") {
                    // Expanded - move to first place
                    other.add_row_at_index(this, 0);
                } else {
                    // Not expanded - move to last place
                    other.add_row_at_index(this, "last");
                }
                return;
            }

            // Calculate the target index
            var index = other.index() + 1;

            if ((other.parent_row == this.parent_row) && (this.index() <= other.index())) {
                // The rows share the same parent and we are moving this to a place later on.
                // Therefore - the target index should be one place lower to account for removal.
                index--;
            }

            // Otherwise add after other as a sibling
            if (other.parent_row) {
                other.parent_row.add_row_at_index(this, index);
                return;
            }

            // Must be root level - add to table
            this.table.add_row_at_index(this, index);
        }

        this.group = function() {
            // Get the group of elements - this row and all child rows.
            var result = $(this.row);
            for (var i = 0; i < this.rows.length; i++) {
                result = result.add($(this.rows[i].group()));
            }
            return result;
        }

        // Position functions
        this.top = function() {
            return $(this.row).position().top;
        }

        this.bottom = function() {
            // Bottom does not include child rows
            return this.top() + this.height();
        }

        this.height = function() {
            return $(this.row).outerHeight(true);
        }

        this.calculate_dragging_parameters = function(e, offset) {
            // Calculate the dragging parameters for this row - ie the points at which to swap this row or change its depth

            // Optionally specify an offset if this row is currently out of base position
            offset = offset || 0;

            var dragging = this.table.dragging;

            dragging.target = this;
            dragging.rows = this.group();
            dragging.startY = e.clientY - offset;

            // Calculate which neighboring rows have boundaries above and below this one
            var row_boundaries_above = this.row_boundaries_above();
            var row_boundaries_below = this.row_boundaries_below();

            // Row above and row below are the rows above and below this one in the dom
            dragging.row_above = row_boundaries_above.slice(-1)[0];
            dragging.row_below = this.next_sibling();

            // Calculate the max and min deltas
            var headerRow = this.table.header();
            var table = this.table.table_element;

            dragging.minDelta = 0;
            if (dragging.row_above) {
                dragging.minDelta = $(headerRow).position().top + $(headerRow).outerHeight(true) - dragging.row_above.bottom();
            }

            dragging.maxDelta = 0;
            if (dragging.row_below) {
                dragging.maxDelta = $(table).position().top + $(table).outerHeight(true) - dragging.row_below.top();
            }

            // Constant threshold parameter
            var swap_ratio = 0.6;

            // Calculate the threshold values
            dragging.threshold_above = null;
            if (dragging.row_above) {
                dragging.threshold_above = - dragging.row_above.height() * swap_ratio;
            }

            dragging.threshold_below = null;
            if (dragging.row_below) {
                dragging.threshold_below = dragging.row_below.height() * swap_ratio;
            }

            // Calculate intermediate thresholds for boundaries above and below
            dragging.intermediate_thresholds_above = null;
            if (dragging.threshold_above) {

                dragging.intermediate_thresholds_above = [];

                // Ignore the final boundary which is the immediate row above, corresponding to threshold
                var count = row_boundaries_above.length - 1;

                // Check if the immediate row above is a non-expanded folder
                var empty_folder_above = false;
                if (row_boundaries_above.length > 0) {
                    empty_folder_above = ((dragging.row_above.type == "folder") && (!(dragging.row_above.status == "expanded")));
                }
                if (empty_folder_above) {
                    // Add a position for the inside of this folder
                    count++;
                }

                for (var i = 0; i < count; i++) {
                    var sub_threshold = dragging.threshold_above * (i + 1) / (count + 1);
                    dragging.intermediate_thresholds_above.push([sub_threshold, row_boundaries_above[i]]);
                }
            }

            dragging.intermediate_thresholds_below = [];

            var count = row_boundaries_below.length;

            // Calculate subthresholds as a proportion of the threshold below - or the row height if it doesn't exist
            var max = dragging.threshold_below || this.height();

            for (var i = 0; i < count; i++) {
                var sub_threshold = max * (i + 1) / (count + 1);
                dragging.intermediate_thresholds_below.push([sub_threshold, row_boundaries_below[i]]);
            }

            // Update the dragging max delta if need be to allow intermediate moves at the bottom of the table
            dragging.maxDelta = Math.max(dragging.maxDelta, max);

            // Also store the original parent and index of the row - these change whenever a swap happens
            dragging.original_parent_row = this.parent_row;
            dragging.original_index = this.index();

        }

        $(row_element).on("click", "span.expand-folder", function(e) {
            // Expand this row as a folder
            self.toggle_folder();
        });

        if (this.table.editable) {
            $(row_element).on("mousedown", function(e) {
                // Mousedown - start dragging
                var dragging = self.table.dragging;

                dragging.status = "dragging";

                // Record the original position of the row - doesn't change until mouseup
                dragging.start_parent_row = self.parent_row;
                dragging.start_index = self.index();

                // Calculate boundaries
                self.calculate_dragging_parameters(e);

                // Relatively position the rows so we can move them
                $(dragging.rows).css("position", "relative");
                $(dragging.rows).css("background-color", "#EEE");

                // Prevent text selection etc
                e.preventDefault();
            });
        }

    }


    // Find all folder list tables and initialise the classes
    var tables = $(".folder-list-table");
    for (var i = 0; i < tables.length; i++) {
        // Create the table
        new tableClass(tables[i]);
    }

});

