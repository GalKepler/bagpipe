// Scroll-reveal for `.reveal` sections (style.py's `.reveal`/`.reveal.is-visible`)
// — shared by every page (kept out of landing.js so /science, /team,
// /privacy, /upload get the same entry animation without loading three.js).
if (
  "IntersectionObserver" in window &&
  !window.matchMedia("(prefers-reduced-motion: reduce)").matches
) {
  const observer = new IntersectionObserver(
    (entries) => {
      for (const entry of entries) {
        if (entry.isIntersecting) {
          entry.target.classList.add("is-visible");
          observer.unobserve(entry.target);
        }
      }
    },
    // threshold: 0 — fires as soon as any pixel is visible. A content page's
    // whole-body ".reveal" section is several viewport-heights tall, so a
    // higher ratio-based threshold (e.g. 0.2 of the element's own height)
    // could never be reached and the section — the entire page — would stay
    // invisible forever.
    { threshold: 0 }
  );
  document.querySelectorAll(".reveal").forEach((el) => observer.observe(el));
} else {
  // No IntersectionObserver, or the visitor asked for reduced motion —
  // show everything immediately rather than leaving it permanently faded.
  document.querySelectorAll(".reveal").forEach((el) => el.classList.add("is-visible"));
}
