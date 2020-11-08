$(function() {

    var inputs = $("input.pattern");

    $(document).on("keyup", "input.fd", function() {

        // Ajax the new formula pattern
        AJAX(
            "/formula_definition/update/",
            {
                "formula_definition_id": $(this).attr("data-id"),
                "pattern": $(this).val()
            },
            function(response) {
                // Update the formula regex

                var formula_regex_p = $("p.formula-regex[data-id='" + response.system_id + "']");
                $(formula_regex_p).text(response.system_regex);

            }
        );
    });


    $(document).on("keyup", "input.test-formula", function() {

        var system_id = $(this).attr("data-id");

        // Ajax the new formula pattern
        AJAX(
            "/formal_system/test_formula/",
            {
                "system_id": system_id,
                "test_string": $(this).val()
            },
            function(response) {
                // Update the result

                var output = $("p.test-formula-output[data-id='" + system_id + "']");

                if (response.result) {
                    $(output).html("Pass");
                } else {
                    $(output).html("Fail");
                }

            }
        );
    });

});
