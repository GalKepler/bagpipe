"""Plain-language prose about one person's result — the paragraphs that sit
between the figures and explain what they are looking at.

Two implementations behind one interface:

* `_template_narrative` — deterministic, offline, always available. Composes
  the prose from the numbers the report already computed. It is not a
  stand-in for nothing: a report should never ship an empty explanation box,
  and a rule-based paragraph that is *correct* beats an eloquent one that is
  unverifiable.
* `_llm_narrative` — the hook for LLM-written prose, gated on `app.narrative`
  in `config/local.yaml`. Not wired to a provider yet (see NOT-YET-WIRED
  below); it returns None today and the template result is used.

Whichever runs, the output carries `source` so the page/PDF can label it, and
neither is ever allowed to state or imply a diagnosis — this is a wellness
report (`docs/design-brief.md` §1/§10), and the copy constraints in
`COPY_RULES` are the ones an LLM prompt would have to carry too.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from bagpipe.app.region_names import RegionScore, by_network, describe, top_deviations

logger = logging.getLogger(__name__)

# Hard constraints on anything this module emits, in either implementation.
# Stated once, here, so the template generator and any future prompt are
# written against the same list rather than drifting.
COPY_RULES = (
    "Never diagnose, screen, or predict risk — this is a wellness and "
    "informational report.",
    "Never state a point estimate without its uncertainty.",
    "Never describe a single region's deviation as meaningful on its own; "
    "with 432 regions, some land beyond 2 sigma by chance.",
    "Never tell the reader what to do about a result, medically or otherwise.",
    "Plain language: no z-scores, atlas names, or model internals in prose.",
)


@dataclass(frozen=True)
class NarrativeSection:
    heading: str
    paragraphs: list[str]


@dataclass(frozen=True)
class Narrative:
    sections: list[NarrativeSection]
    source: str  # "template" | "llm"
    model: str | None = None
    context: dict = field(default_factory=dict, repr=False)


def generate(prediction: dict, qc_metrics: dict) -> Narrative:
    """The one entry point. Falls back to the template narrative whenever the
    LLM path is unconfigured or fails — a report is never blocked on it."""
    context = build_context(prediction, qc_metrics)
    try:
        narrative = _llm_narrative(context)
    except Exception:  # noqa: BLE001 — prose is never worth failing a job over
        logger.exception("LLM narrative failed; falling back to the template narrative")
        narrative = None
    return narrative or _template_narrative(context)


# --------------------------------------------------------------------------
# Context — the compact, already-derived view both implementations read from.
# --------------------------------------------------------------------------
def build_context(prediction: dict, qc_metrics: dict) -> dict:
    """Flattens a `prediction.json` into the handful of facts the prose
    actually needs. Also, deliberately, the exact payload an LLM prompt would
    carry: readable region names and derived statistics only — no imaging,
    no identifiers, no raw feature values, nothing that would leave this
    machine as personal data beyond the result itself.
    """
    scores = describe(prediction.get("regional_zscores", {}))
    gm = [s for s in scores if s.metric == "vol_gm"]
    population = prediction.get("population") or {}
    band = prediction.get("age_band") or {}

    return {
        "bag": prediction.get("bag_corrected"),
        "predicted_age": prediction.get("predicted_age"),
        "chronological_age": prediction.get("chronological_age"),
        "uncertainty_years": band.get("mae_corrected"),
        "band_label": band.get("label"),
        "band_is_fallback": bool(band.get("is_fallback")),
        "bag_percentile": population.get("bag_percentile"),
        "cohort_n": population.get("n"),
        "cohort_bag_sd": population.get("bag_sd"),
        "age_out_of_range": bool(prediction.get("age_out_of_range")),
        "scan_quality_pct": qc_metrics.get("siqr_pct"),
        "scan_quality_grade": qc_metrics.get("siqr_grade"),
        "n_regions": len(gm),
        "n_beyond_2sd": sum(1 for s in gm if abs(s.z) >= 2),
        "expected_beyond_2sd": round(len(gm) * 0.0455),
        "networks": by_network(scores),
        "top_regions": [
            {"name": s.display, "network": s.network_display, "z": round(s.z, 2)}
            for s in top_deviations(scores, n=6)
        ],
        "copy_rules": list(COPY_RULES),
    }


# --------------------------------------------------------------------------
# NOT-YET-WIRED: the LLM path.
# --------------------------------------------------------------------------
PROMPT_TEMPLATE = """\
You are writing three short paragraphs for a person reading their own brain
imaging wellness report. You are given only derived statistics, never images
or identifiers.

Rules you must follow exactly:
{rules}

Write, in this order and with these headings:
1. "What this means" — what the brain age gap is and what theirs is, always
   with its uncertainty, and what the comparison to the reference cohort does
   and does not tell them.
2. "Your regional pattern" — whether their regional deviations look like an
   ordinary spread or stand out, using the count beyond 2 sigma against the
   count expected by chance. Name at most two regions, in plain anatomy.
3. "How to read this" — the honest limits: self-reported age, one scan, a
   single-site reference cohort, error that grows with age.

Result:
{context}
"""


def _llm_narrative(context: dict) -> Narrative | None:
    """Placeholder for LLM-written prose.

    To wire it up: read the provider/model/key from `app.narrative` in
    `config/local.yaml`, render `PROMPT_TEMPLATE` with `context` (which is
    already scrubbed — see `build_context`), and return a `Narrative` with
    `source="llm"` and the model id. Until then this returns None on every
    call and `generate` uses the template narrative, so the report renders
    identically whether or not the key is ever set.

    Two things this must keep doing when it is wired: send only `context`
    (never the manifest, the feature vector, or the upload), and stay inside
    `generate`'s try/except so a provider outage degrades the prose rather
    than failing an hour-long job at the last stage.
    """
    return None


# --------------------------------------------------------------------------
# The deterministic narrative.
# --------------------------------------------------------------------------
def _describe_gap(bag: float, uncertainty: float | None) -> str:
    if uncertainty is not None and abs(bag) <= uncertainty:
        return "close enough to the average that it is within this model's typical error"
    direction = "older" if bag > 0 else "younger"
    magnitude = "somewhat" if abs(bag) < 2 * (uncertainty or 5) else "noticeably"
    return f"{magnitude} {direction} than your chronological age"


def _percentile_sentence(percentile: float | None, cohort_n: int | None) -> str:
    if percentile is None or not cohort_n:
        return ""
    higher = round(percentile)
    if higher >= 50:
        comparison = f"higher than about {higher}% of the reference cohort"
    else:
        comparison = f"lower than about {100 - higher}% of the reference cohort"
    return (
        f" Placed against the {cohort_n:,} people this model was validated on, your gap is "
        f"{comparison}."
    )


def _template_narrative(context: dict) -> Narrative:
    bag = context.get("bag")
    uncertainty = context.get("uncertainty_years")
    sections: list[NarrativeSection] = []

    if bag is None:
        opening = (
            "Your brain age gap could not be placed against your chronological age, "
            "because no age was given with this upload."
        )
    else:
        opening = (
            f"Your brain's predicted age came out {abs(bag):.1f} years "
            f"{'above' if bag >= 0 else 'below'} the age you gave, a gap of "
            f"{bag:+.1f} years"
            + (f" give or take {uncertainty:.1f} years" if uncertainty else "")
            + f". That is {_describe_gap(bag, uncertainty)}."
        )
    meaning = [
        opening + _percentile_sentence(context.get("bag_percentile"), context.get("cohort_n")),
        "A brain age gap is one number summarising how the overall pattern of tissue "
        "volumes in your scan compares with people of different ages. It is a "
        "population-level measure: it describes how your scan looks relative to a "
        "reference group, not anything about your health, and it is not a diagnosis "
        "or a screening result.",
    ]
    if context.get("age_out_of_range"):
        meaning.append(
            "Your predicted age also falls outside the range this model reports on "
            "confidently, so treat the number above with extra caution."
        )
    sections.append(NarrativeSection("What this means", meaning))

    n_beyond, expected = context.get("n_beyond_2sd", 0), context.get("expected_beyond_2sd", 0)
    n_regions = context.get("n_regions", 0)
    if n_regions:
        if n_beyond <= expected:
            spread = (
                f"{n_beyond} of your {n_regions} regions sit more than two standard "
                f"deviations from the reference average — about the {expected} you would "
                "expect from chance alone in this many measurements. Your regional "
                "pattern looks unremarkable."
            )
        else:
            spread = (
                f"{n_beyond} of your {n_regions} regions sit more than two standard "
                f"deviations from the reference average, against roughly {expected} "
                "expected from chance alone in this many measurements. That is a wider "
                "spread than typical, though it is still a description of one scan and "
                "not a finding about any one region."
            )
        regional = [spread]
        top = context.get("top_regions") or []
        if top:
            named = " and the ".join(
                f"{r['name'].lower()} ({r['z']:+.1f} standard deviations)" for r in top[:2]
            )
            regional.append(
                f"The largest differences in your scan are in the {named}. Single regions "
                "move around a lot between scans and between people, so read the network "
                "profile in this report — which averages over dozens of regions at once — "
                "before reading any individual region."
            )
        sections.append(NarrativeSection("Your regional pattern", regional))

    limits = [
        "This estimate comes from one scan, compared against a single-site reference "
        "cohort, using an age you reported yourself and we could not verify. The model's "
        "error grows with age — it is roughly two and a half times larger for a "
        "seventy-year-old than for a twenty-five-year-old — which is why the figure "
        "beside your result is a range, not a point.",
    ]
    quality = context.get("scan_quality_pct")
    if quality is not None:
        limits.append(
            f"Your scan's automatic quality rating was {quality}% "
            f"({context.get('scan_quality_grade', 'n/a')}). Lower-quality scans give "
            "noisier volumes, and that noise ends up in every number in this report."
        )
    sections.append(NarrativeSection("How to read this", limits))

    return Narrative(sections=sections, source="template", context=context)


def sections_html(narrative: Narrative) -> str:
    """Both the results page and the PDF render the narrative identically —
    same markup, styled by each surface's own CSS."""
    from html import escape

    parts = []
    for section in narrative.sections:
        paragraphs = "".join(f"<p>{escape(p)}</p>" for p in section.paragraphs)
        parts.append(
            f'<div class="narrative__block"><h3 class="narrative__heading">'
            f"{escape(section.heading)}</h3>{paragraphs}</div>"
        )
    return "".join(parts)


__all__ = [
    "COPY_RULES",
    "PROMPT_TEMPLATE",
    "Narrative",
    "NarrativeSection",
    "RegionScore",
    "build_context",
    "generate",
    "sections_html",
]
