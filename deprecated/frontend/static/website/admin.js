
$(function() {

    // Refresh proofs button
    $("div#refresh-proofs").on("click", function() {
        AJAX(
            "/ajax/admin/refresh-proofs/",
            {},
            function(response) {
                console.log(response);
            }
        )
    })
})