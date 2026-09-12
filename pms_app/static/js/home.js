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
                var duration = 1400;
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

    var stage = document.querySelector("[data-banner-stage]");
    var pile = document.querySelector("[data-banner-pile]");
    var banners = pile ? pile.querySelectorAll("[data-banner]") : [];

    var expandPile = function () {
        if (!pile) return;
        pile.classList.add("is-expanded");
        banners.forEach(function (banner) {
            banner.classList.add("is-dealt");
        });
    };

    var playBanners = function () {
        if (!pile || pile.dataset.played === "1") return;
        pile.dataset.played = "1";
        if (reduceMotion) {
            expandPile();
            return;
        }
        banners.forEach(function (banner, i) {
            window.setTimeout(function () {
                banner.classList.add("is-dealt");
            }, i * 280);
        });
        window.setTimeout(expandPile, banners.length * 280 + 700);
    };

    if (pile && banners.length) {
        if (reduceMotion) {
            expandPile();
        } else if ("IntersectionObserver" in window) {
            var bannerObserver = new IntersectionObserver(function (entries) {
                entries.forEach(function (entry) {
                    if (!entry.isIntersecting) return;
                    playBanners();
                    bannerObserver.disconnect();
                });
            }, { threshold: 0.25 });
            bannerObserver.observe(stage || pile);
        } else {
            expandPile();
        }
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
