/* Path: pms_app/static/js/home.js
   Sequential card play + FAQ. No fake counters. */

(function () {
    "use strict";

    document.addEventListener("DOMContentLoaded", function () {
        initFaq();
        if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
            document.querySelectorAll("[data-play-cards] > *").forEach(function (card) {
                card.classList.add("is-playing");
            });
            return;
        }
        initPlayCards();
    });

    function initPlayCards() {
        document.querySelectorAll("[data-play-cards]").forEach(function (group) {
            var cards = Array.prototype.slice.call(group.children);
            if (!cards.length) return;
            var interval = parseInt(group.getAttribute("data-play-interval"), 10) || 2400;
            var index = Math.max(0, cards.findIndex(function (card) {
                return card.classList.contains("is-playing");
            }));
            var timer = null;
            var dotsRoot = group.parentElement
                ? group.parentElement.querySelector("[data-play-dots]")
                : null;
            var dots = dotsRoot ? Array.prototype.slice.call(dotsRoot.children) : [];

            function show(next) {
                cards.forEach(function (card, i) {
                    card.classList.toggle("is-playing", i === next);
                });
                dots.forEach(function (dot, i) {
                    dot.classList.toggle("is-on", i === next);
                });
                index = next;
            }

            function start() {
                if (timer) return;
                show(index);
                timer = setInterval(function () {
                    show((index + 1) % cards.length);
                }, interval);
            }

            function stop() {
                if (!timer) return;
                clearInterval(timer);
                timer = null;
            }

            start();

            if ("IntersectionObserver" in window) {
                var observer = new IntersectionObserver(
                    function (entries) {
                        entries.forEach(function (entry) {
                            if (entry.isIntersecting) start();
                            else stop();
                        });
                    },
                    { threshold: 0.2 }
                );
                observer.observe(group);
            }

            group.addEventListener("mouseenter", stop);
            group.addEventListener("mouseleave", start);
            group.addEventListener("focusin", stop);
            group.addEventListener("focusout", start);
        });
    }

    function initFaq() {
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
    }
})();
