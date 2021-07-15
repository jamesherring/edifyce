
$(function() {

    $(".messages-container").on("click", ".close-cross", function() {
        $(this).parent().remove();
    });
});

function add_message(text) {

    var message = $("<div class='message'></div>");
    $(message).append("<span>" + text + "</span>");
    $(message).append("<span class='close-cross'>&#x2715;</span>");

    var container = $("<div class='message-container'></div>");

    $(container).append(message)
    $(".messages-container").append(container);
}

