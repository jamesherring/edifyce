

$(function() {

    // Get the output div and build a table class in it
    var output_parent = $("#output");
    var code = $(output_parent).html();
    var output = new proofDisplayClass(output_parent);

    // Get the validation data script
    var validation = JSON.parse(document.getElementById("validation").innerHTML);
    output.populate(code, validation);

})