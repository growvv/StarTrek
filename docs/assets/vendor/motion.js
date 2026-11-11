/* Motion glue for the SpecFCG site.
 *
 * Visual vocabulary is borrowed, not invented:
 *   - AOS 2.3.4  (MIT, https://michalsnik.github.io/aos/)  scroll reveal
 *   - CountUp.js (MIT, https://inorganik.github.io/countUp.js/)  stat counters
 * The rest is the usual landing-page plumbing: a page-load bar, a reading
 * progress bar in the nav, staggered group entrances, and screenshot
 * skeletons that shimmer until the image decodes.
 */
(function () {
  'use strict';

  var reduce =
    window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  /* 1. Page-load bar, NProgress style: trickle to 88%, finish on load. */
  var loadbar = document.getElementById('pageload');
  if (loadbar) {
    var width = 10;
    loadbar.style.width = width + '%';
    var trickle = setInterval(function () {
      width = Math.min(width + 6 + Math.random() * 10, 88);
      loadbar.style.width = width + '%';
    }, 220);
    var finish = function () {
      clearInterval(trickle);
      loadbar.style.width = '100%';
      setTimeout(function () {
        loadbar.classList.add('done');
      }, 380);
    };
    if (document.readyState === 'complete') finish();
    else window.addEventListener('load', finish);
  }

  /* 2. Reading progress, pinned to the bottom edge of the nav. */
  var scrollbar = document.getElementById('scrollbar');
  if (scrollbar) {
    var paint = function () {
      var max = document.documentElement.scrollHeight - window.innerHeight;
      var pct = max > 0 ? (window.scrollY / max) * 100 : 0;
      scrollbar.style.width = Math.min(100, Math.max(0, pct)) + '%';
    };
    window.addEventListener('scroll', paint, { passive: true });
    window.addEventListener('resize', paint);
    paint();
  }

  /* 3. Stagger a group so its members enter one after another. */
  var groups = [
    ['.stats > .stat', 90],
    ['.grid > .card', 80],
    ['.pipeline > .step', 70],
    ['.shot-strip > figure', 70],
    ['.step-list > .step-item', 45],
    ['.grid-two > .panel', 80]
  ];
  if (!reduce) {
    groups.forEach(function (pair) {
      document.querySelectorAll(pair[0]).forEach(function (el, i) {
        if (el.hasAttribute('data-aos')) return;
        el.setAttribute('data-aos', 'fade-up');
        el.setAttribute('data-aos-delay', String((i % 5) * pair[1]));
      });
    });
    ['.section-head', '.cta', '.card-doc', '.graph-wrap', 'table', '.note',
     '.demo-note', '.timeline'].forEach(function (sel) {
      document.querySelectorAll(sel).forEach(function (el) {
        if (el.hasAttribute('data-aos')) return;
        el.setAttribute('data-aos', 'fade-up');
      });
    });
  }

  /* 4. Scroll reveal, via AOS. */
  if (window.AOS) {
    AOS.init({
      once: true,
      duration: 700,
      easing: 'ease-out-cubic',
      offset: 70,
      disable: reduce
    });
  }

  /* 5. Stat counters, via CountUp; triggered when the tile enters view. */
  if (window.countUp && !reduce) {
    var targets = document.querySelectorAll('[data-count-to]');
    if ('IntersectionObserver' in window) {
      var io = new IntersectionObserver(
        function (entries) {
          entries.forEach(function (entry) {
            if (!entry.isIntersecting) return;
            var el = entry.target;
            io.unobserve(el);
            var up = new countUp.CountUp(el, Number(el.getAttribute('data-count-to')), {
              duration: 1.5,
              suffix: el.getAttribute('data-count-suffix') || '',
              useGrouping: false,
              useEasing: true
            });
            if (!up.error) up.start();
          });
        },
        { threshold: 0.5 }
      );
      targets.forEach(function (el) {
        io.observe(el);
      });
    }
  }

  /* 6. Shimmer until each screenshot decodes, then fade it in. */
  document.querySelectorAll('img').forEach(function (img) {
    var reveal = function () {
      img.classList.add('loaded');
      var box = img.closest('figure, .phone');
      if (box) box.classList.add('loaded');
    };
    if (img.complete && img.naturalWidth) {
      reveal();
      return;
    }
    img.addEventListener('load', reveal, { once: true });
    img.addEventListener('error', reveal, { once: true });
  });
})();
