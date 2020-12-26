


$(function() {

    var editor = new codeEditorClass($("div#ace-container"));
    var output = $("#output");

//    function startTimeout() {
//        window.timeout = setTimeout(function() {
//            // Redo the MathJax
//            $(output).html(editor.editor.getValue());
//            MathJax.typeset();
//        }, 1000);
//    }
//
//    editor.editor.session.on("change", function() {
//        // Restart the timeout
//        window.clearTimeout(window.timeout);
//        startTimeout();
//    });



})