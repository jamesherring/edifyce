
function getCookie(name) {
    var cookieValue = null;
    if (document.cookie && document.cookie !== '') {
        var cookies = document.cookie.split(';');
        for (var i = 0; i < cookies.length; i++) {
            var cookie = cookies[i].trim();
            // Does this cookie string begin with the name we want?
            if (cookie.substring(0, name.length + 1) === (name + '=')) {
                cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                break;
            }
        }
    }
    return cookieValue;
}


function setCookie(name, value) {
    document.cookie = name + "=" + encodeURIComponent(value) + ";";
}


function getParameterByName(name, url) {
    if (!url) url = window.location.href;
    name = name.replace(/[\[\]]/g, '\\$&');
    var regex = new RegExp('[?&]' + name + '(=([^&#]*)|&|#|$)'),
        results = regex.exec(url);
    if (!results) return null;
    if (!results[2]) return '';
    return decodeURIComponent(results[2].replace(/\+/g, ' '));
}


function AJAX(url, data, response) {

    $.ajaxSetup({
        beforeSend: function(xhr, settings) {
            if (!(/^http:.*/.test(settings.url) || /^https:.*/.test(settings.url))) {
                // Only send the token to relative URLs i.e. locally.
                xhr.setRequestHeader("X-CSRFToken", getCookie('csrftoken'));
            }
        }
    });

    $.ajax({
        "url": url,
        "dataType": "json",
        "type": "POST",
        "cache": false,
        "headers": {
            "X-CSRFTOKEN": getCookie("csrftoken")
        },
        "data": data,
        "success": function(response_data) {
            if ("success" in response_data) {
                if (response_data.success) {
                    // Call the user functions
                    response(response_data);
    
                } else {
                    // Alert the error
                    alert(response_data.errorMessage);
                }
            } else {
                response(response_data);
            }
        }
    });
}


function decodeHtml(html) {
    var txt = document.createElement("textarea");
    txt.innerHTML = html;
    return txt.value;
}

function animate_height_change(e, h_start, h_end, max_t, dt, on_complete) {
    // Animate the change in height for an element
    
    // Time for animation in ms
    max_t = max_t || 250;
    
    // Time between frames in ms
    dt = dt || 20;
        
    $(e).css({
        "overflow": "hidden",
        "height": h_start
    });
    
    var t = 0;
    var si = setInterval(function() {
        t = t + dt;
        
        if (t > max_t) {
            clearInterval(si);
            $(e).css("height", "auto");
            
            if (on_complete) {
                on_complete();
            }
            
        } else {
        
            var h = Math.round(h_start + ((t / max_t) * (h_end - h_start)));
            $(e).css("height", h);
            
        }
        
    }, dt);
}

function animate_entry(e, on_complete) {
    // Animate entry of an element e
    
    $(e).removeClass("hidden");
    
    var temp_div = $("<div></div>");
    
    // Hide the temp div but keep the height
    $(temp_div).css({
        "position": "absolute",
        "visibility": "hidden"
    });
    
    $(temp_div).insertBefore(e);
    $(temp_div).append(e);
    
    var height = $(temp_div).outerHeight();
    
    setTimeout(function() {
        
        $(temp_div).css({
            "position": "static",
            "visibility": "visible",
            "overflow": "hidden",
            "height": 0
        });
        
        animate_height_change(temp_div, 0, height, 250, 20, function() {
            // Remove the temp div
            $(e).insertBefore(temp_div);
            $(temp_div).remove();
            
            if (on_complete) {
                on_complete();
            }
        });
    }, 0);
    
}

function animate_or_show(e, animate, on_complete) {
    // Animate entry or show e
    if (animate) {
        animate_entry(e, on_complete);
    } else {
        $(e).removeClass("hidden");
        if (on_complete) {
            on_complete();
        }
    }
}

function animate_exit(e, save) {
    // Animate exit of element e. Removes e from the DOM unless save === true
    
    var temp_div = $("<div></div>");
    $(temp_div).insertBefore(e);
    $(temp_div).append(e);
    
    var height = $(temp_div).outerHeight();
    
    animate_height_change(temp_div, height, 0, 250, 20, function() {
        
        if (save) {
            // Save e
            $(e).insertBefore(temp_div);
            $(e).addClass("hidden");
            
        }
        
        // Delete the temp_div
        $(temp_div).remove();
        
    });
}




// Is it a mobile device?
window.is_mobile = function() {
    return $("#is-mobile").css("display") == "none";
};

// Is the user logged in?
window.logged_in = function() {
//    return ($("div#menu a[href='/signin/']").length === 0);
};


// Clear selection
function clear_selection() {
    if (window.getSelection) {
        if (window.getSelection().empty) {  // Chrome
            window.getSelection().empty();
            
        } else if (window.getSelection().removeAllRanges) {  // Firefox
            window.getSelection().removeAllRanges();
            
        }
    } else if (document.selection) {  // IE?
        document.selection.empty();
    }
}






