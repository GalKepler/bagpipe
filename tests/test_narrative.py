"""`bagpipe.app.narrative` — the prose block, and its LLM hook.

The copy rules in `narrative.COPY_RULES` are the point of this module, so the
tests check the output against them (no diagnosis language, never a bare
point estimate) rather than just that some text came back.
"""

from __future__ import annotations

import pytest

from bagpipe.app import narrative as nv
from bagpipe.app.region_names import ATLAS_PREFIX, regions

LABELS = list(regions())


def _prediction(**overrides) -> dict:
    zscores = {f"{ATLAS_PREFIX}__{label}__vol_gm": 0.2 for label in LABELS}
    zscores[f"{ATLAS_PREFIX}__{LABELS[5]}__vol_gm"] = -3.4
    base = {
        "predicted_age": 46.3,
        "chronological_age": 43.9,
        "bag_corrected": 2.4,
        "regional_zscores": zscores,
        "age_band": {"label": "40-50", "n": 331, "mae_corrected": 6.1, "is_fallback": False},
        "population": {"n": 2260, "bag_sd": 5.2, "bag_percentile": 68.0},
    }
    base.update(overrides)
    return base


@pytest.fixture
def qc() -> dict:
    return {"siqr_pct": 88.4, "siqr_grade": "B+"}


def test_generate_falls_back_to_the_template_narrative(qc):
    narrative = nv.generate(_prediction(), qc)
    assert narrative.source == "template"
    assert [s.heading for s in narrative.sections] == [
        "What this means",
        "Your regional pattern",
        "How to read this",
    ]
    assert all(s.paragraphs for s in narrative.sections)


def test_narrative_states_the_gap_with_its_uncertainty(qc):
    text = " ".join(p for s in nv.generate(_prediction(), qc).sections for p in s.paragraphs)
    assert "+2.4 years" in text
    assert "give or take 6.1 years" in text
    assert "68% of the reference cohort" in text


def test_narrative_never_uses_diagnostic_language(qc):
    text = " ".join(
        p for s in nv.generate(_prediction(), qc).sections for p in s.paragraphs
    ).lower()
    for forbidden in ("diagnos", "risk of", "you should see", "abnormal", "disease", "screening f"):
        assert forbidden not in text or forbidden == "diagnos"  # only as "not a diagnosis"
    assert "not a diagnosis" in text


def test_narrative_compares_outliers_against_the_chance_baseline(qc):
    text = " ".join(p for s in nv.generate(_prediction(), qc).sections for p in s.paragraphs)
    assert "chance alone" in text and "432 regions" in text


def test_narrative_handles_a_missing_chronological_age(qc):
    prediction = _prediction(chronological_age=None, bag_corrected=None)
    text = " ".join(p for s in nv.generate(prediction, qc).sections for p in s.paragraphs)
    assert "no age was given" in text


def test_narrative_flags_an_out_of_range_prediction(qc):
    text = " ".join(
        p
        for s in nv.generate(_prediction(age_out_of_range=True), qc).sections
        for p in s.paragraphs
    )
    assert "outside the range" in text


def test_build_context_carries_only_derived_statistics(qc):
    """This dict is what an LLM prompt would send off the machine — assert it
    holds no identifiers, no raw features and no file paths."""
    context = nv.build_context(_prediction(), qc)
    assert set(context) >= {"bag", "bag_percentile", "networks", "top_regions", "copy_rules"}
    assert all(set(r) == {"name", "network", "z"} for r in context["top_regions"])
    serialised = repr(context)
    for leak in ("subject", "session", "job_id", "sub-", ".nii", "/home", "/media", ATLAS_PREFIX):
        assert leak not in serialised


def test_llm_narrative_is_not_wired_yet_and_generate_survives_it_raising(qc, monkeypatch):
    assert nv._llm_narrative(nv.build_context(_prediction(), qc)) is None

    def boom(_context):
        raise RuntimeError("provider down")

    monkeypatch.setattr(nv, "_llm_narrative", boom)
    narrative = nv.generate(_prediction(), qc)
    assert narrative.source == "template"


def test_sections_html_escapes_and_wraps_each_section(qc):
    narrative = nv.Narrative(
        sections=[nv.NarrativeSection("A & B", ["<script>x</script>"])], source="template"
    )
    html = nv.sections_html(narrative)
    assert "A &amp; B" in html
    assert "<script>" not in html
    assert 'class="narrative__block"' in html
