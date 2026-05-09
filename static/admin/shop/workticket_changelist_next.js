/* Next stage on Work ticket changelist — POST via fetch so we never nest <form>
 * inside Django/Unfold's bulk-action #changelist-form (invalid HTML breaks row 1).
 */
(function () {
    "use strict";

    function getCookie(name) {
        var cookieValue = null;
        if (document.cookie && document.cookie !== "") {
            var cookies = document.cookie.split(";");
            for (var i = 0; i < cookies.length; i++) {
                var cookie = cookies[i].trim();
                if (cookie.substring(0, name.length + 1) === name + "=") {
                    cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                    break;
                }
            }
        }
        return cookieValue;
    }

    document.addEventListener(
        "click",
        function (e) {
            var btn = e.target.closest(".sss-wt-next-stage-btn");
            if (!btn || btn.disabled) return;
            e.preventDefault();
            e.stopPropagation();
            e.stopImmediatePropagation();
            var url = btn.getAttribute("data-post-url");
            var next = btn.getAttribute("data-next") || window.location.href;
            if (!url) return;
            var token = getCookie("csrftoken") || "";
            btn.disabled = true;
            var body = new URLSearchParams();
            body.append("csrfmiddlewaretoken", token);
            body.append("next", next);
            fetch(url, {
                method: "POST",
                credentials: "same-origin",
                headers: {
                    "X-CSRFToken": token,
                    "X-Requested-With": "XMLHttpRequest",
                },
                body: body,
            })
                .then(function (r) {
                    /* POST usually ends as redirect→GET; fetch follows and exposes final URL */
                    if (r.redirected && r.url) {
                        window.location.href = r.url;
                        return;
                    }
                    if (r.ok) {
                        window.location.reload();
                        return;
                    }
                    btn.disabled = false;
                })
                .catch(function () {
                    btn.disabled = false;
                });
        },
        true,
    );
})();
