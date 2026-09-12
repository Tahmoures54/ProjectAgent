/* Path: pms_app/static/js/home.js
   FAQ only. Homepage stays still — no looping motion. */

(function () {
    "use strict";

    document.addEventListener("DOMContentLoaded", function () {
        document.querySelectorAll(".faq-question").forEach(function (btn) {
            btn.addEventListener("click", function () {
                var item = btn.closest(".faq-item");
                var open = item.classList.contains("open");
                document.querySelectorAll(".faq-item.open").forEach(function (el) {
                    el.classList.remove("open");
                    var q = el.querySelector(".faq-question");
                    if (q) q.setAttribute("aria-expanded", "false");
                });
                if (!open) {
                    item.classList.add("open");
                    btn.setAttribute("aria-expanded", "true");
                }
            });
        });
    });
})();
