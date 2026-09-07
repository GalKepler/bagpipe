"""Inline-SVG charts shared by the interactive results page and the emailed
PDF report.

Why server-rendered SVG rather than a JS charting library: WeasyPrint has no
JS, so anything drawn client-side is a figure the printed report simply
cannot have — and the two surfaces drifting apart is exactly the failure this
module exists to prevent. Plain strings, no dependency, and both callers get
the identical figure.

Palette is passed in rather than read from CSS: the web page is the dark
`docs/design-brief.md` §3 ground and the report is a light print palette, and
WeasyPrint's support for CSS custom properties inside inline SVG is not
something to bet a mailed report on. `DARK`/`PRINT` below are the two
palettes in use; both obey the brief's central rule — the only saturated
colors are `warm`/`cool`, and they appear only where data is being reported.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from html import escape

from bagpipe.app.region_names import RegionScore

# Diverging scale bounds. z beyond +/-3 is clamped rather than rescaled, so a
# single extreme region can't flatten every other bar in the figure.
Z_LIMIT = 3.0


@dataclass(frozen=True)
class Palette:
    ground: str
    surface: str
    line: str
    ink: str
    muted: str
    warm: str
    cool: str
    band: str  # shading for a reference range, one step off `surface`


DARK = Palette(
    ground="#0B0F0E",
    surface="#141A18",
    line="#232B28",
    ink="#E8E6DF",
    muted="#8A928E",
    warm="#E0873A",
    cool="#3FA89A",
    band="#1E2624",
)
PRINT = Palette(
    ground="#FFFFFF",
    surface="#F4F5F1",
    line="#D8DBD3",
    ink="#14201D",
    muted="#5C665F",
    warm="#E0873A",
    cool="#3FA89A",
    band="#EDEEE8",
)

_MONO = "'Geist Mono', ui-monospace, monospace"
_SANS = "'Instrument Sans', 'Helvetica Neue', sans-serif"


def _svg(width: float, height: float, title: str, body: str, desc: str = "") -> str:
    return (
        f'<svg class="chart" viewBox="0 0 {width:.0f} {height:.0f}" width="100%" '
        f'preserveAspectRatio="xMidYMid meet" role="img" '
        f'aria-label="{escape(title)}" xmlns="http://www.w3.org/2000/svg">'
        f"<title>{escape(title)}</title>"
        + (f"<desc>{escape(desc)}</desc>" if desc else "")
        + body
        + "</svg>"
    )


def _text(x: float, y: float, s: str, *, fill: str, size: float = 11,
          anchor: str = "start", family: str = _MONO, weight: int = 400) -> str:
    return (
        f'<text x="{x:.1f}" y="{y:.1f}" fill="{fill}" font-size="{size}" '
        f'font-family="{family}" font-weight="{weight}" text-anchor="{anchor}">{escape(s)}</text>'
    )


def _signed(value: float, digits: int = 2) -> str:
    return f"{value:+.{digits}f}"


def z_color(z: float, palette: Palette) -> str:
    """Warm above the norm, cool below it — the site-wide convention
    (design-brief §3). Saturation tracks |z| so the near-zero majority stays
    quiet and only genuine outliers pull the eye; the same intent as
    `static/brainmap.js`'s ramp, expressed as opacity rather than a mixed RGB
    so it survives a grayscale print.
    """
    base = palette.warm if z >= 0 else palette.cool
    return base


def _z_opacity(z: float) -> float:
    return round(0.35 + 0.65 * min(abs(z) / Z_LIMIT, 1.0), 3)


# --------------------------------------------------------------------------
# 1. Where the person sits in the cohort's brain-age-gap distribution.
# --------------------------------------------------------------------------
def bag_distribution(
    histogram: dict, user_bag: float, percentile: float | None, palette: Palette
) -> str:
    """Cohort BAG histogram with the reader's own gap marked on it.

    `histogram` is the aggregate `{"edges": [...], "counts": [...]}` block
    computed in `bagpipe.app.pipeline.predict` — counts only, never the
    underlying subjects (see that module's note on why no per-subject data
    reaches the browser).
    """
    edges, counts = histogram["edges"], histogram["counts"]
    if not counts:
        return ""

    w, h = 640.0, 210.0
    pad_l, pad_r, pad_t, pad_b = 12.0, 12.0, 30.0, 34.0
    plot_w, plot_h = w - pad_l - pad_r, h - pad_t - pad_b
    lo, hi = edges[0], edges[-1]
    span = hi - lo or 1.0
    # Bin widths are not uniform — `predict._bag_histogram` pools sparse tail
    # bins so none of them describes a single subject — so bar height is
    # density, not count. Drawing raw counts here would make a merged wide
    # bin tower over the dense middle it was pooled away from.
    densities = [c / (edges[i + 1] - edges[i] or 1.0) for i, c in enumerate(counts)]
    peak = max(densities) or 1.0

    def x_of(value: float) -> float:
        return pad_l + (min(max(value, lo), hi) - lo) / span * plot_w

    bars = []
    for i in range(len(counts)):
        x0, x1 = x_of(edges[i]), x_of(edges[i + 1])
        bar_h = densities[i] / peak * plot_h
        # The bin containing the reader is filled in their gap's own color;
        # the rest of the distribution stays neutral, so the figure has
        # exactly one colored element and it is the reader's result.
        is_theirs = edges[i] <= user_bag < edges[i + 1]
        fill = z_color(user_bag, palette) if is_theirs else palette.line
        bars.append(
            f'<rect x="{x0:.1f}" y="{pad_t + plot_h - bar_h:.1f}" '
            f'width="{max(x1 - x0 - 1, 0.5):.1f}" height="{bar_h:.1f}" fill="{fill}"/>'
        )

    ticks = []
    for value in _nice_ticks(lo, hi, 7):
        x = x_of(value)
        ticks.append(
            f'<line x1="{x:.1f}" y1="{pad_t + plot_h:.1f}" x2="{x:.1f}" '
            f'y2="{pad_t + plot_h + 4:.1f}" stroke="{palette.line}"/>'
        )
        ticks.append(
            _text(x, pad_t + plot_h + 16, f"{value:+.0f}", fill=palette.muted,
                  size=10, anchor="middle")
        )

    zero_x = x_of(0.0)
    user_x = x_of(user_bag)
    marker = (
        f'<line x1="{zero_x:.1f}" y1="{pad_t - 6:.1f}" x2="{zero_x:.1f}" '
        f'y2="{pad_t + plot_h:.1f}" stroke="{palette.muted}" stroke-dasharray="3 3"/>'
        + _text(zero_x, pad_t - 10, "cohort average", fill=palette.muted, size=9, anchor="middle")
        + f'<line x1="{user_x:.1f}" y1="{pad_t - 2:.1f}" x2="{user_x:.1f}" '
        f'y2="{pad_t + plot_h + 2:.1f}" stroke="{palette.ink}" stroke-width="2"/>'
        + f'<circle cx="{user_x:.1f}" cy="{pad_t - 2:.1f}" r="4" fill="{palette.ink}"/>'
    )

    caption = f"you {_signed(user_bag, 1)} y"
    if percentile is not None:
        caption += f" · {_ordinal(percentile)} percentile"
    anchor = "end" if user_x > pad_l + plot_w * 0.7 else "start"
    caption_x = user_x + (-7 if anchor == "end" else 7)

    body = (
        "".join(bars)
        + f'<line x1="{pad_l:.1f}" y1="{pad_t + plot_h:.1f}" x2="{pad_l + plot_w:.1f}" '
        f'y2="{pad_t + plot_h:.1f}" stroke="{palette.line}"/>'
        + "".join(ticks)
        + marker
        + _text(caption_x, pad_t + 14, caption, fill=palette.ink, size=11, anchor=anchor)
        + _text(pad_l, h - 4, "brain age gap (years) across the reference cohort",
                fill=palette.muted, size=10, family=_SANS)
    )
    return _svg(w, h, "Your brain age gap against the reference cohort's distribution", body)


# --------------------------------------------------------------------------
# 2. How the model behaves across ages, and where the reader lands on it.
# --------------------------------------------------------------------------
def calibration(
    bands: list[dict], user_age: float | None, user_predicted: float, palette: Palette
) -> str:
    """Predicted vs. chronological age: the cohort's median and 10th-90th
    percentile band per age bin, the identity line, and the reader's point.

    This is the figure that makes the model's biggest honest limitation
    visible instead of buried in a caveat sentence — the band fans out with
    age, and the median pulls toward the middle (regression to the mean, the
    same effect the Cole correction exists to undo).
    """
    if not bands:
        return ""

    w, h = 640.0, 320.0
    pad_l, pad_r, pad_t, pad_b = 52.0, 14.0, 16.0, 40.0
    plot_w, plot_h = w - pad_l - pad_r, h - pad_t - pad_b

    xs = [b["age_lo"] for b in bands] + [b["age_hi"] for b in bands]
    ys = [b["p10"] for b in bands] + [b["p90"] for b in bands]
    lo = math.floor(min(xs + ys + [user_predicted] + ([user_age] if user_age else [])) / 10) * 10
    hi = math.ceil(max(xs + ys + [user_predicted] + ([user_age] if user_age else [])) / 10) * 10
    span = (hi - lo) or 1.0

    def x_of(v: float) -> float:
        return pad_l + (v - lo) / span * plot_w

    def y_of(v: float) -> float:
        return pad_t + plot_h - (v - lo) / span * plot_h

    points = [((b["age_lo"] + b["age_hi"]) / 2, b) for b in bands]
    upper = " ".join(f"{x_of(c):.1f},{y_of(b['p90']):.1f}" for c, b in points)
    lower = " ".join(f"{x_of(c):.1f},{y_of(b['p10']):.1f}" for c, b in reversed(points))
    median = " ".join(f"{x_of(c):.1f},{y_of(b['median']):.1f}" for c, b in points)

    grid = []
    for value in _nice_ticks(lo, hi, 6):
        grid.append(
            f'<line x1="{x_of(value):.1f}" y1="{pad_t:.1f}" x2="{x_of(value):.1f}" '
            f'y2="{pad_t + plot_h:.1f}" stroke="{palette.line}" stroke-width="0.5"/>'
        )
        grid.append(
            _text(x_of(value), pad_t + plot_h + 16, f"{value:.0f}", fill=palette.muted,
                  size=10, anchor="middle")
        )
        grid.append(
            _text(pad_l - 8, y_of(value) + 3, f"{value:.0f}", fill=palette.muted,
                  size=10, anchor="end")
        )

    user_marker = ""
    if user_age is not None:
        ux, uy = x_of(user_age), y_of(user_predicted)
        gap_color = z_color(user_predicted - user_age, palette)
        user_marker = (
            f'<line x1="{ux:.1f}" y1="{y_of(user_age):.1f}" x2="{ux:.1f}" y2="{uy:.1f}" '
            f'stroke="{gap_color}" stroke-width="2"/>'
            f'<circle cx="{ux:.1f}" cy="{uy:.1f}" r="5.5" fill="{gap_color}" '
            f'stroke="{palette.ground}" stroke-width="1.5"/>'
            + _text(ux + 10, uy - 8, "you", fill=palette.ink, size=11)
        )

    body = (
        "".join(grid)
        + f'<polygon points="{upper} {lower}" fill="{palette.muted}" fill-opacity="0.18"/>'
        + f'<line x1="{x_of(lo):.1f}" y1="{y_of(lo):.1f}" x2="{x_of(hi):.1f}" '
        f'y2="{y_of(hi):.1f}" stroke="{palette.muted}" stroke-dasharray="4 4"/>'
        + f'<polyline points="{median}" fill="none" stroke="{palette.ink}" stroke-width="1.5"/>'
        + user_marker
        + _text(pad_l, h - 6, "chronological age (years)", fill=palette.muted,
                size=10, family=_SANS)
        + f'<text x="{12:.0f}" y="{pad_t + plot_h / 2:.1f}" fill="{palette.muted}" '
        f'font-size="10" font-family="{_SANS}" text-anchor="middle" '
        f'transform="rotate(-90 12 {pad_t + plot_h / 2:.1f})">predicted brain age (years)</text>'  # noqa: E501
    )
    desc = (
        "Shaded band: the middle 80% of predictions in the reference cohort at each age. "
        "Solid line: cohort median. Dashed diagonal: a perfect prediction."
    )
    return _svg(w, h, "Predicted brain age against chronological age", body, desc)


# --------------------------------------------------------------------------
# 3. Network-level profile.
# --------------------------------------------------------------------------
def network_profile(rows: list[dict], palette: Palette) -> str:
    """Mean z per functional network — the "shape" of a person's result in
    eight bars instead of 432, and the level at which a deviation is actually
    stable enough to say anything about.
    """
    if not rows:
        return ""

    row_h = 30.0
    w = 640.0
    pad_l, pad_r, pad_t = 168.0, 56.0, 24.0
    h = pad_t + row_h * len(rows) + 24
    axis_w = w - pad_l - pad_r
    centre = pad_l + axis_w / 2
    # Network means are an order of magnitude tighter than single-region
    # z-scores, so they get their own (much narrower) axis — reusing the
    # +/-3 region scale would render every bar as an invisible stub.
    limit = max(0.5, min(1.5, max(abs(r["mean_z"]) for r in rows) * 1.25))

    def x_of(z: float) -> float:
        return centre + max(-limit, min(limit, z)) / limit * (axis_w / 2)

    parts = [
        f'<line x1="{centre:.1f}" y1="{pad_t - 6:.1f}" x2="{centre:.1f}" '
        f'y2="{pad_t + row_h * len(rows):.1f}" stroke="{palette.muted}"/>',
        _text(centre, pad_t - 10, "norm", fill=palette.muted, size=9, anchor="middle"),
    ]
    for i, row in enumerate(rows):
        y = pad_t + i * row_h
        z = row["mean_z"]
        x0, x1 = (centre, x_of(z)) if z >= 0 else (x_of(z), centre)
        parts.append(
            f'<rect x="{x0:.1f}" y="{y + 7:.1f}" width="{max(x1 - x0, 1):.1f}" height="12" '
            f'rx="2" fill="{z_color(z, palette)}" fill-opacity="{_z_opacity(z * 2):.2f}"/>'
        )
        parts.append(_text(pad_l - 12, y + 17, row["display"], fill=palette.ink,
                           size=11.5, anchor="end", family=_SANS))
        parts.append(_text(w - pad_r + 10, y + 17, _signed(z), fill=palette.muted, size=10.5))
        parts.append(
            f'<line x1="{pad_l - 156:.1f}" y1="{y + 0.5:.1f}" x2="{w - 10:.1f}" '
            f'y2="{y + 0.5:.1f}" stroke="{palette.line}" stroke-width="0.5"/>'
        )
    parts.append(
        _text(pad_l, h - 6, "average deviation from the norm, in standard deviations",
              fill=palette.muted, size=10, family=_SANS)
    )
    return _svg(w, h, "Average deviation by functional network", "".join(parts))


# --------------------------------------------------------------------------
# 4. The regions that deviate most — replaces a bare table of label strings.
# --------------------------------------------------------------------------
def deviation_ranking(scores: list[RegionScore], palette: Palette, limit: int = 10) -> str:
    if not scores:
        return ""
    rows = scores[:limit]
    row_h = 26.0
    w = 640.0
    pad_l, pad_r, pad_t = 286.0, 52.0, 30.0
    h = pad_t + row_h * len(rows) + 22
    axis_w = w - pad_l - pad_r
    centre = pad_l + axis_w / 2

    def x_of(z: float) -> float:
        return centre + max(-Z_LIMIT, min(Z_LIMIT, z)) / Z_LIMIT * (axis_w / 2)

    parts = []
    # +/-1 sigma shading: the range two thirds of the cohort falls in, so a
    # bar that stays inside it is visibly unremarkable rather than merely
    # "smaller than the ones above it".
    parts.append(
        f'<rect x="{x_of(-1):.1f}" y="{pad_t - 4:.1f}" width="{x_of(1) - x_of(-1):.1f}" '
        f'height="{row_h * len(rows) + 4:.1f}" fill="{palette.band}"/>'
    )
    parts.append(
        f'<line x1="{centre:.1f}" y1="{pad_t - 8:.1f}" x2="{centre:.1f}" '
        f'y2="{pad_t + row_h * len(rows):.1f}" stroke="{palette.muted}"/>'
    )
    for tick in (-3, -1, 1, 3):
        parts.append(
            _text(x_of(tick), pad_t - 12, f"{tick:+d}σ", fill=palette.muted, size=9,
                  anchor="middle")
        )

    for i, score in enumerate(rows):
        y = pad_t + i * row_h
        cx = x_of(score.z)
        x0, x1 = (centre, cx) if score.z >= 0 else (cx, centre)
        parts.append(
            f'<rect x="{x0:.1f}" y="{y + 11:.1f}" width="{max(x1 - x0, 1):.1f}" height="3" '
            f'fill="{z_color(score.z, palette)}" fill-opacity="{_z_opacity(score.z):.2f}"/>'
        )
        parts.append(
            f'<circle cx="{cx:.1f}" cy="{y + 12.5:.1f}" r="4.5" '
            f'fill="{z_color(score.z, palette)}"/>'
        )
        parts.append(_text(pad_l - 14, y + 16, _truncate(score.display, 40), fill=palette.ink,
                           size=11, anchor="end", family=_SANS))
        parts.append(_text(w - pad_r + 8, y + 16, f"{_signed(score.z, 1)}σ",
                           fill=palette.muted, size=10.5))

    parts.append(
        _text(pad_l - 14, h - 4, "shaded: the typical range (±1σ)", fill=palette.muted,
              size=10, family=_SANS, anchor="end")
    )
    return _svg(w, h, "Regions deviating most from the reference norm", "".join(parts))


# --------------------------------------------------------------------------
# 5. The whole regional profile at once, against what chance alone predicts.
# --------------------------------------------------------------------------
def zscore_spread(scores: list[RegionScore], palette: Palette) -> str:
    """Histogram of the reader's own regional z-scores with the standard
    normal overlaid.

    This answers the question the top-10 list provokes and cannot answer:
    *is having a few regions at 2 sigma unusual?* With 432 regions, roughly
    20 land beyond 2 sigma by chance alone, and the overlay says so visually
    rather than asking the reader to take a caveat's word for it.
    """
    values = [s.z for s in scores]
    if len(values) < 20:
        return ""

    w, h = 640.0, 200.0
    pad_l, pad_r, pad_t, pad_b = 14.0, 14.0, 18.0, 34.0
    plot_w, plot_h = w - pad_l - pad_r, h - pad_t - pad_b
    lo, hi, n_bins = -4.0, 4.0, 32
    width = (hi - lo) / n_bins

    counts = [0] * n_bins
    for v in values:
        idx = int((min(max(v, lo), hi - 1e-9) - lo) / width)
        counts[idx] += 1
    peak = max(counts) or 1

    def x_of(v: float) -> float:
        return pad_l + (v - lo) / (hi - lo) * plot_w

    bars = []
    for i, count in enumerate(counts):
        z0 = lo + i * width
        bar_h = count / peak * plot_h
        bars.append(
            f'<rect x="{x_of(z0):.1f}" y="{pad_t + plot_h - bar_h:.1f}" '
            f'width="{plot_w / n_bins - 1:.1f}" height="{bar_h:.1f}" '
            f'fill="{z_color(z0 + width / 2, palette)}" '
            f'fill-opacity="{_z_opacity(z0 + width / 2):.2f}"/>'
        )

    # Standard normal scaled to the same bin width and sample size, then to
    # the plot's own peak — an "expected counts" curve, not a density.
    def _curve_point(k: int) -> str:
        z = lo + k * (hi - lo) / 120
        expected = len(values) * width * _normal_pdf(z)
        return f"{x_of(z):.1f},{pad_t + plot_h - expected / peak * plot_h:.1f}"

    curve = " ".join(_curve_point(k) for k in range(121))

    beyond2 = sum(1 for v in values if abs(v) >= 2)
    expected2 = round(len(values) * 0.0455)

    body = (
        "".join(bars)
        + f'<polyline points="{curve}" fill="none" stroke="{palette.ink}" '
        f'stroke-width="1.4" stroke-dasharray="5 3"/>'
        + f'<line x1="{pad_l:.1f}" y1="{pad_t + plot_h:.1f}" x2="{pad_l + plot_w:.1f}" '
        f'y2="{pad_t + plot_h:.1f}" stroke="{palette.line}"/>'
        + "".join(
            _text(x_of(t), pad_t + plot_h + 15, f"{t:+.0f}σ", fill=palette.muted,
                  size=10, anchor="middle")
            for t in (-3, -2, -1, 0, 1, 2, 3)
        )
        + _text(
            pad_l + plot_w, h - 4,
            f"{beyond2} of your {len(values)} regions are beyond ±2σ · "
            f"~{expected2} expected by chance",
            fill=palette.muted, size=10, family=_SANS, anchor="end",
        )
    )
    return _svg(w, h, "Spread of your regional deviations", body)


def _normal_pdf(z: float) -> float:
    return math.exp(-0.5 * z * z) / math.sqrt(2 * math.pi)


def _nice_ticks(lo: float, hi: float, target: int) -> list[float]:
    span = hi - lo
    if span <= 0:
        return [lo]
    raw = span / max(target, 1)
    magnitude = 10 ** math.floor(math.log10(raw))
    step = min((m * magnitude for m in (1, 2, 2.5, 5, 10) if m * magnitude >= raw), default=raw)
    start = math.ceil(lo / step) * step
    ticks, value = [], start
    while value <= hi + 1e-9:
        ticks.append(round(value, 6))
        value += step
    return ticks


def _ordinal(value: float) -> str:
    n = int(round(value))
    n = max(1, min(99, n))
    suffix = "th" if 11 <= n % 100 <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


# Public alias — `bagpipe.app.results_page` and `report` both need to format
# a percentile the same way the figures do.
ordinal = _ordinal
