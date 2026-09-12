(function () {
    "use strict";

    var reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    var counters = document.querySelectorAll("[data-counter]");
    if (counters.length && "IntersectionObserver" in window) {
        var counterObserver = new IntersectionObserver(function (entries) {
            entries.forEach(function (entry) {
                if (!entry.isIntersecting) return;
                var el = entry.target;
                var target = parseFloat(el.dataset.target);
                var decimals = parseInt(el.dataset.decimals || "0", 10);
                var span = el.querySelector(".counter");
                if (!span || Number.isNaN(target)) {
                    counterObserver.unobserve(el);
                    return;
                }
                var toFa = function (n) {
                    return n.toLocaleString("fa-IR", {
                        minimumFractionDigits: decimals,
                        maximumFractionDigits: decimals,
                    });
                };
                if (reduceMotion) {
                    span.textContent = toFa(target);
                    counterObserver.unobserve(el);
                    return;
                }
                var duration = 1600;
                var start = performance.now();
                var tick = function (now) {
                    var p = Math.min((now - start) / duration, 1);
                    var eased = 1 - Math.pow(1 - p, 3);
                    span.textContent = toFa(target * eased);
                    if (p < 1) requestAnimationFrame(tick);
                    else span.textContent = toFa(target);
                };
                requestAnimationFrame(tick);
                counterObserver.unobserve(el);
            });
        }, { threshold: 0.4 });
        counters.forEach(function (c) {
            counterObserver.observe(c);
        });
    }

    var revealTargets = document.querySelectorAll(
        ".bento__item, .stat-card, .price-card, .section-head, .audience-card, .step-card, .proof-card"
    );
    if (reduceMotion) {
        revealTargets.forEach(function (el) {
            el.classList.add("is-visible");
        });
    } else if ("IntersectionObserver" in window) {
        revealTargets.forEach(function (el) {
            el.classList.add("reveal");
        });
        var revealObserver = new IntersectionObserver(function (entries) {
            entries.forEach(function (entry, i) {
                if (entry.isIntersecting) {
                    window.setTimeout(function () {
                        entry.target.classList.add("is-visible");
                    }, i * 60);
                    revealObserver.unobserve(entry.target);
                }
            });
        }, { threshold: 0.1, rootMargin: "0px 0px -50px 0px" });
        revealTargets.forEach(function (el) {
            revealObserver.observe(el);
        });
    }

    var tabs = document.querySelectorAll(".showcase__tab");
    var panels = document.querySelectorAll(".showcase__panel");
    tabs.forEach(function (tab) {
        tab.addEventListener("click", function () {
            var target = tab.dataset.target;
            tabs.forEach(function (t) {
                var on = t === tab;
                t.classList.toggle("is-active", on);
                t.setAttribute("aria-selected", on ? "true" : "false");
            });
            panels.forEach(function (p) {
                p.classList.toggle("is-active", p.id === target);
            });
        });
    });

    var showcaseIdx = 0;
    var showcaseTimer;
    var showcaseRoot = document.querySelector(".showcase");
    var startAutoRotate = function () {
        if (!tabs.length || reduceMotion) return;
        showcaseTimer = window.setInterval(function () {
            showcaseIdx = (showcaseIdx + 1) % tabs.length;
            tabs[showcaseIdx].click();
        }, 5000);
    };
    if (showcaseRoot && tabs.length) {
        startAutoRotate();
        showcaseRoot.addEventListener("mouseenter", function () {
            window.clearInterval(showcaseTimer);
        });
        showcaseRoot.addEventListener("mouseleave", startAutoRotate);
        showcaseRoot.addEventListener("focusin", function () {
            window.clearInterval(showcaseTimer);
        });
        showcaseRoot.addEventListener("focusout", startAutoRotate);
    }

    var tiltEl = document.querySelector("[data-tilt]");
    if (
        tiltEl &&
        window.matchMedia("(min-width: 960px)").matches &&
        !reduceMotion
    ) {
        var mockup = tiltEl.querySelector(".hero__mockup");
        if (mockup) {
            tiltEl.addEventListener("mousemove", function (e) {
                var rect = tiltEl.getBoundingClientRect();
                var x = (e.clientX - rect.left) / rect.width - 0.5;
                var y = (e.clientY - rect.top) / rect.height - 0.5;
                mockup.style.transform =
                    "rotate(" + (-2 + x * 4) + "deg) rotateY(" + x * 6 + "deg) rotateX(" + -y * 6 + "deg)";
            });
            tiltEl.addEventListener("mouseleave", function () {
                mockup.style.transform = "";
            });
        }
    }

    document.querySelectorAll('a[href^="#"]').forEach(function (a) {
        a.addEventListener("click", function (e) {
            var href = a.getAttribute("href");
            if (!href || href.length < 2) return;
            var target = document.querySelector(href);
            if (target) {
                e.preventDefault();
                target.scrollIntoView({ behavior: reduceMotion ? "auto" : "smooth", block: "start" });
            }
        });
    });

    document.querySelectorAll(".faq-item").forEach(function (item) {
        item.addEventListener("toggle", function () {
            if (!item.open) return;
            document.querySelectorAll(".faq-item").forEach(function (other) {
                if (other !== item) other.open = false;
            });
        });
    });
})();
