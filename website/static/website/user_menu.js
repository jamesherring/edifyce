
$(function() {

    $(".user-menu-toggle").on("click", function() {
        $("#user-menu").toggleClass("hidden");
        return false;
    });

    $(document.body).on("click", function(e) {
        if (!$(e.target).closest("#user-menu").length) {
            $("#user-menu").addClass("hidden");
        }
    });
})