
$(function() {

    // Make text editable
    $(".edit-text").on("click", function() {
        // Remove text and show the input
        var span = $(this).prevAll("span.editable-value");
        var input = $(this).prevAll(".editable-text");

        // $(input).val($(span).text());
        $(input).removeClass("hidden");
        $(input).select();

        // Check for city and country inputs
        var city_input = $(this).prevAll(".editable-city");
        var country_input = $(this).prevAll("select");
        var save_button = $(this).nextAll(".save-location");

        $(city_input).removeClass("hidden");
        $(country_input).removeClass("hidden");
        $(save_button).removeClass("hidden");
        $(city_input).select();

        $(span).empty();

    });

    // Handle change of text values
    $(".editable-text").on("blur", function() {
        // Update the text value
        var value = $(this).val();
        var field = $(this).data("field");

        var obj = $(this).data("obj").split("_");

        var table = obj[0];
        var id = obj[1];

        var span = $(this).prevAll("span");
        $(span).html(value);

        if (value.length > 0) {
            // Hide the input
            $(this).addClass("hidden");

            // Parse mathjax
            MathJax.typeset(span);

        } else {
            // Value set to empty string - keep the input
        }

        AJAX(
            "/ajax/update-text/" + table + "/" + field + "/",
            {
                "target_id": id,
                "value": value
            },
            function(response) {
                console.log(response);
            }
        )

    });

    // Make images editable
    $(".edit-pencil").on("click", function() {
        var button = $(this).prev();
        if (button) {
            $(button).click();
        }
    });

    // Handle change of image file
    $('input[type="file"]').on("change", function() {
        if (this.files && this.files[0]) {

            // Only works if the input comes immediately after the target image
            var target_img = $(this).prev("img")[0];

            if (!target_img) {
                return;
            }

            target_img.onload = () => {
                URL.revokeObjectURL(target_img.src);  // no longer needed, free memory
            }

            target_img.src = URL.createObjectURL(this.files[0]); // set src to blob url

            // Submit an AJAX request to update the image
            var fd = new FormData();
            fd.append("file", this.files[0]);

            $.ajax({
				url: "/ajax/update-image/" + this.id + "/",
				"headers": {
                    "X-CSRFTOKEN": getCookie("csrftoken")
                },
				type: "POST",
				data: fd,
				dataType: "json",
				processData: false,
				contentType: false,
                cache: false,
				success: function(response) {
				    console.log(response);
				}
			});

        }
    });

    // City and country
    $(".save-location").on("click", function() {
        // Save the location and hide the inputs

        var city_input = $(this).prevAll(".editable-city");
        var country_input = $(this).prevAll("select");

        var city = $(city_input).val();
        var country = $(country_input).val();

        var obj = $(city_input).data("obj").split("_");
        var table = obj[0];
        var id = obj[1];

        // Send values to the server
        AJAX(
            "/ajax/update-text/" + table + "/city/",
            {
                "target_id": id,
                "value": city
            },
            function(response) {
                console.log(response);
            }
        );

        AJAX(
            "/ajax/update-text/" + table + "/country/",
            {
                "target_id": id,
                "value": country
            },
            function(response) {
                console.log(response);
            }
        );

        // Calculate location text for front-end
        var location_text = city;
        if (country) {
            location_text += ", " + country;
        }

        if (location_text == "") {
            // No location
            return;
        }

        // Hide the inputs and save button
        $(city_input).addClass("hidden");
        $(country_input).addClass("hidden");
        $(this).addClass("hidden");

        // Show the value span
        var span = $(this).prevAll("span.editable-value");
        $(span).removeClass("hidden");
        $(span).text(location_text);

    });
})