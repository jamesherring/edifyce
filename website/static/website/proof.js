

$(function() {

    // Get the output div and build a table class in it
    var output_parent = $("#output");
    var output = new proofDisplayClass(output_parent);

     var data = JSON.parse(document.getElementById("proof_data").innerHTML);
     output.populate(data);

    console.log(data.valid);

})