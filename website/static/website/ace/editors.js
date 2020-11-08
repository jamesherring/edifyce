

var codeEditorClass = function(container) {
    var editorClass = this;

    this.save_file = function() {
        // Save the file if there are changes

        var update_local = function(url) {

            // Update the sessions object
            editorClass.sessions[url] = editorClass.sessionToJSON();

            // Save the sessions object in localStorage
            localStorage.setItem("editor_session", JSON.stringify(editorClass.sessions));
        }

        if (($(this.filename_input).val() == this.saved_name) && (this.editor.getValue() == this.saved_contents)) {
            // No changes
            update_local(window.location.href);
            return;
        }

        var path = window.location.pathname.split("/").slice(3, -1).join("/");

        AJAX(
            "/ajax/save_file/",
            {
                "path": path,
                "name": $(this.filename_input).val(),
                "contents": this.editor.getValue()
            },
            function(response) {

                // Update the saved values
                editorClass.saved_name = $(editorClass.filename_input).val();
                editorClass.saved_contents = editorClass.editor.getValue();

                // Update the filenav
                window.filenav.refresh();

                // Update the url
                var url_parts = window.location.href.split("/");
                var new_url = url_parts.slice(0, -2).join("/") + "/" + editorClass.saved_name + "/";
                window.history.pushState({}, "", new_url);

                update_local(new_url);

                // Update the color of the expand div
                $(editorClass.expand_div).css("background-color", "#408020");

            }
        )
    }

    this.expand = function() {
        // Expand the editor
        $(this.expanded_parent).append(this.container);
        $(this.container).css({
            "position": "absolute",
            "top": 0,
            "left": 0,
            "width": "100%",
            "height": "100%"
        });
        editorClass.editor.resize();

        sessionStorage["ace-editor-expanded"] = true;
    }

    this.contract = function() {
        // Contract the editor
        $(this.container).insertBefore(this.textarea);
        $(this.container).css({
            "position": "relative",
            "height": "40rem"
        });
        editorClass.editor.resize();

        sessionStorage["ace-editor-expanded"] = false;
    }

    // Add ace editors to the required form elements

    this.textarea = $("textarea");
    $(container).append(this.textarea);
    var textarea = this.textarea;

    this.container = container;

    this.expand_div = $("<div></div>");
    $(this.expand_div).css({
        "background-color": "#408020",
        "width": "1.5rem",
        "height": "1.5rem",
        "position": "absolute",
        "top": "1rem",
        "right": "1.5rem",
        "cursor": "pointer",
        "opacity": 0.8
    });
    $(this.expand_div).hover(function() {
        $(this).css("opacity", 1);
    }, function() {
        $(this).css("opacity", 0.8);
    });
    $(this.container).append(this.expand_div);

    this.expanded_parent = $("#content-main-wrapper");
    $(this.expand_div).on("click", function() {
        // Move the editor to a bigger container

        if ($(editorClass.container).parent().attr("id") == "content-main-wrapper") {
            // Already expanded, need to de-expand
            editorClass.contract();
        } else {
            // Expand the editor
            editorClass.expand();

        }
    })

    this.editor = ace.edit($(this.container).attr("id"));
    this.editor.setTheme("ace/theme/monokai");
    this.editor.session.setMode("ace/mode/latex");

    $(window).on("resize", function() {
        // Resize the editor with the window
        editorClass.editor.resize();
    });

    // Check for changes and save when the user stops typing
    this.editor.session.on("change", function() {
        // Clear any previous timeout
        window.clearTimeout(editorClass.saveTimeout);

        // Change the button color to indicate unsaved changes
        if (editorClass.editor.getValue() == editorClass.saved_contents) {
            $(editorClass.expand_div).css("background-color", "#408020");
        } else {
            $(editorClass.expand_div).css("background-color", "#FFAA33");
        }

        // Set a new timeout
        // editorClass.saveTimeout = window.setTimeout(function() {
            // editorClass.save_file();
        // }, 2000);
    })

    // Save on editor blur
    // this.editor.on("blur", function() {
       //  editorClass.save_file();

    // })

}
