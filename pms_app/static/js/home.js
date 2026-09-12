/* Path: pms_app/static/js/home.js */
/* ==========================================================
   Project Agent Home Page Scripts
   Handles: Hero slider, counters, FAQ, scroll animations
   ========================================================== */

(function () {
    'use strict';

    document.addEventListener('DOMContentLoaded', function () {
        initHeroSlider();
        initCounters();
        initFaq();
        initScrollAnimations();
    });

    /* -------- Hero Slider -------- */
    function initHeroSlider() {
        const slides = document.querySelectorAll('.hero-slide');
        const dots = document.querySelectorAll('.hero-dot');
        if (!slides.length) return;

        let current = 0;
        let timer;
        const INTERVAL = 5000;

        function show(index) {
            slides.forEach((s, i) => s.classList.toggle('active', i === index));
            dots.forEach((d, i) => d.classList.toggle('active', i === index));
            current = index;
        }

        function next() { show((current + 1) % slides.length); }
        function start() { timer = setInterval(next, INTERVAL); }
        function stop() { clearInterval(timer); }

        show(0);
        start();

        dots.forEach((dot, i) => {
            dot.addEventListener('click', () => {
                stop();
                show(i);
                start();
            });
        });

        // Pause on hover
        const hero = document.querySelector('.hero');
        if (hero) {
            hero.addEventListener('mouseenter', stop);
            hero.addEventListener('mouseleave', start);
        }
    }

    /* -------- Counters -------- */
    function initCounters() {
        const counters = document.querySelectorAll('.counter');
        if (!counters.length || !('IntersectionObserver' in window)) return;

        const observer = new IntersectionObserver((entries) => {
            entries.forEach(entry => {
                if (!entry.isIntersecting) return;
                animateCounter(entry.target);
                observer.unobserve(entry.target);
            });
        }, { threshold: 0.5 });

        counters.forEach(c => observer.observe(c));
    }

    function animateCounter(el) {
        const target = parseInt(el.dataset.target, 10) || 0;
        const duration = 1500;
        const stepTime = 30;
        const steps = duration / stepTime;
        const increment = target / steps;
        let current = 0;

        const timer = setInterval(() => {
            current += increment;
            if (current >= target) {
                el.textContent = target.toLocaleString('fa-IR');
                clearInterval(timer);
            } else {
                el.textContent = Math.floor(current).toLocaleString('fa-IR');
            }
        }, stepTime);
    }

    /* -------- FAQ Accordion -------- */
    function initFaq() {
        document.querySelectorAll('.faq-question').forEach(btn => {
            btn.addEventListener('click', () => {
                const item = btn.closest('.faq-item');
                const isOpen = item.classList.contains('open');

                // Close others (optional - remove for multi-open)
                document.querySelectorAll('.faq-item.open').forEach(el => el.classList.remove('open'));

                if (!isOpen) item.classList.add('open');
                btn.setAttribute('aria-expanded', String(!isOpen));
            });
        });
    }

    /* -------- Scroll Animations -------- */
    function initScrollAnimations() {
        const items = document.querySelectorAll('.fade-in-up');
        if (!items.length || !('IntersectionObserver' in window)) return;

        const observer = new IntersectionObserver((entries) => {
            entries.forEach(entry => {
                if (entry.isIntersecting) {
                    entry.target.classList.add('visible');
                    observer.unobserve(entry.target);
                }
            });
        }, { threshold: 0.15 });

        items.forEach(el => observer.observe(el));
    }
})();