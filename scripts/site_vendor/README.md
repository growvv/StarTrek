# Vendored motion assets

These files are copied verbatim (no edits) from their upstream distributions:

| File | Source | Version | License |
|---|---|---|---|
| `aos.css`, `aos.js` | https://github.com/michalsnik/aos | 2.3.4 | MIT |
| `countup.umd.js` | https://github.com/inorganik/countUp.js | 2.9.0 | MIT |
| `motion.js` | this repository | — | MIT |

`motion.js` is the only local file: it initialises AOS, triggers the CountUp
stat counters when they enter the viewport, drives the page-load and reading
progress bars, adds the staggered group delays, and swaps screenshot
skeletons for the decoded image. The site's visual vocabulary (scroll reveal,
counters, shimmer) is deliberately borrowed from these libraries and from
common product-landing-page patterns rather than invented here.

Regenerate the published copy with `python scripts/build_site.py`.
