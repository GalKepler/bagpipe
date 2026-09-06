// Scroll orchestration for the landing page (docs/design-brief.md §5/§7):
// the cortex stays pinned in `.landing__brain`, rotates/re-colors driven by
// scroll position (never autoplay), and regions illuminate only while the
// section discussing them is on screen. CortexViewer already exposes
// exactly this surface (setScrollProgress/setRegionValues/regionhover —
// see static/demo.html), so this file is wiring, not new viewer logic.

import { CortexViewer } from "./cortex-viewer.js";

const stage = document.querySelector("[data-scroll-brain]");
if (stage) {
  const viewer = new CortexViewer(stage, { glbUrl: "/static/mesh/cortex.glb" });

  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  // Overall page scroll progress [0,1] drives ambient rotation.
  function onScroll() {
    const doc = document.documentElement;
    const max = doc.scrollHeight - doc.clientHeight;
    viewer.setScrollProgress(max > 0 ? window.scrollY / max : 0);
  }
  if (!reducedMotion) {
    window.addEventListener("scroll", onScroll, { passive: true });
    onScroll();
  }

  // Illuminate a few regions per named section while it's in view — a
  // light illustrative touch, not a data-accurate overlay (that's the
  // results page's job). Picks a small fixed spread of region ids per
  // section so no extra fetch is needed.
  const ILLUMINATE_REGIONS = {
    tissue: { 5: 1.2, 40: -0.9, 120: 0.7 },
    regions: { 20: -1.4, 60: 1.1, 200: -0.6, 310: 0.9 },
    bag: { 8: 2.1, 45: -2.4, 150: 1.6, 260: -1.2 },
  };

  const sections = document.querySelectorAll("[data-illuminate]");
  if (sections.length && "IntersectionObserver" in window) {
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            const key = entry.target.dataset.illuminate;
            viewer.setRegionValues(ILLUMINATE_REGIONS[key] ?? {});
          }
        }
      },
      { rootMargin: "-40% 0px -40% 0px" }
    );
    sections.forEach((el) => observer.observe(el));
  }
}

// Smooth-scroll for the CTA buttons (`data-scroll-to="upload"` etc). Native
// behavior, not a library — respects reduced-motion automatically via CSS
// scroll-behavior being left unset when that media query is active.
document.querySelectorAll("[data-scroll-to]").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.getElementById(btn.dataset.scrollTo)?.scrollIntoView({
      behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth",
    });
  });
});

// ponytail: skipped a per-number count-up animation for the accuracy table
// (brief §7) — the section-level fade-in below already gives entry motion
// for a static 6-cell table; add a real count-up if a section grows a
// single large hero number that needs it.
if ("IntersectionObserver" in window && !window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
  const fadeObserver = new IntersectionObserver(
    (entries) => {
      for (const entry of entries) {
        if (entry.isIntersecting) {
          entry.target.style.animation = "fade-in 600ms ease both";
          fadeObserver.unobserve(entry.target);
        }
      }
    },
    { threshold: 0.2 }
  );
  document.querySelectorAll(".landing__section").forEach((el) => fadeObserver.observe(el));
}
