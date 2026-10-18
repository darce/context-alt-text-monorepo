"""Reader vocabulary for the report; definitions describe rules, not active policy.

Canon v0.26.2 [NAV-13] Controlled vocabulary before label freeze (How to Make
Sense of Any Mess, ch. 4); [WRIT-71] Unpack private knowledge (The Sense of
Style, ch. 3). Wire keys remain secondary references in the report.
"""

from __future__ import annotations

import html
import re


_TERMS = {
    "fnir": ("FNIR (false negative identification rate)",
             "Among searches for people who are enrolled (mated searches), the share that miss "
             "a correct accepted identity at the acceptance threshold. End-to-end misses include "
             "undetected mates and other detector misses, not just rejected embeddings."),
    "fpir": ("FPIR (false positive identification rate)",
             "The share of independent nonmated source units (sources without an enrolled mate) "
             "that produce a false identification at the acceptance threshold. Use the recorded "
             "source-unit denominator, not detection counts. Legacy identification precision and "
             "recall use different denominators and are not this rate."),
    "threshold": ("Acceptance threshold τ",
                  "The similarity score a face match must reach before the system accepts it. "
                  "Each model uses its own recorded score space; this is not a clustering cut."),
    "clustering-cut": ("Clustering cut",
                       "A recorded boundary used to group face embeddings. Its metric and units "
                       "come from the grouping record; an acceptance threshold is not a substitute."),
    "psu": ("PSU (primary sampling unit)",
            "An independent sampling unit defined by the recorded frame, such as a capture group. "
            "The independent-unit count is n_psu; multiple faces from one unit are not independent repeats."),
    "neff": ("Effective count (n_eff)",
             "The sample size after the recorded adjustment for dependence among observations. "
             "It is not necessarily the number of faces, images or independent sampling units."),
    "mde": ("MDE (minimum detectable effect)",
            "The smallest effect the recorded design can detect at its specified power and error rate. "
            "An unavailable value does not establish adequate power."),
    "ratified": ("Ratified",
                 "The decision policy has recorded approval. A declared default or a software test "
                 "does not establish approval; unavailable approval remains unavailable."),
    "sealed": ("Sealed",
               "The run has a recorded seal binding its inputs and policy. A report alone does not "
               "establish a seal or confirmatory qualification."),
    "admissibility": ("Frame admissibility: diagnostic, development, confirmatory",
                      "The recorded permitted use of the sampling frame: diagnostic for inspection, "
                      "development for tuning, confirmatory for the recorded acceptance protocol. "
                      "A label alone does not establish ground truth, approval or a seal."),
    "occlusion-cell": ("Occlusion cell",
                       "A subgroup pairing the query face's occlusion with the enrolled face's occlusion. "
                       "Cell origin describes that cell's data; synthetic occlusions can be generated "
                       "from real inputs and do not establish that the whole run is a software fixture."),
    "native": ("Native arm",
               "The model's normal whole-image detection, alignment and embedding path. "
               "Its end-to-end misses include faces the detector did not find."),
    "gt-crop-redetect": ("GT-crop redetect arm",
                         "A diagnostic path that crops from ground-truth (GT) face boxes and runs "
                         "detection again. This changes the input and is distinct from native processing."),
    "cached-landmark-replay": ("Cached landmark replay arm",
                               "A diagnostic path that reuses recorded landmarks for alignment. "
                               "It does not measure the native detector's ability to find those landmarks."),
    "hypothesis": ("Hypothesis (H1, H2)",
                   "A comparison question governed by the recorded decision policy. H1 and H2 are "
                   "protocol identifiers, not model names. H2 is reached only after H1 passes. "
                   "For superiority, the lower bound of the comparison interval must exceed the "
                   "recorded margin; for non-inferiority it must exceed the negative recorded margin "
                   "in the policy's improvement direction. These are generic rules, not active margins, "
                   "directions or comparison legs; absent policy details remain unavailable."),
    "guardrail": ("Guardrail",
                  "A recorded safety or operational check. A veto-role failure can block acceptance; "
                  "a report-only check describes a result. Unscored is not a pass. G identifiers are "
                  "protocol references; the metric, role, limit and evidence determine their meaning."),
    "kind-per-cohort-fpir": ("False-match rate by demographic group (per_cohort_fpir)",
                             "FPIR evaluated separately for a recorded cohort or subgroup: people "
                             "sharing a recorded demographic attribute. Each group needs its own "
                             "nonmated source-unit evidence and recorded limit; a missing limit is unavailable."),
    "kind-p95": ("95th-percentile time per face (p95_ms_per_face)",
                 "The 95th percentile of amortized whole-image native processing cost per expected "
                 "ground-truth (GT) face. Each GT face receives its image's whole native work divided "
                 "by that image's expected GT-face count, plus an equal share of overhead from images "
                 "with no GT faces. This is an allocated cost, not a per-face stopwatch measurement. "
                 "Numeric milliseconds come from timings.json when supplied."),
}


def term_link(term_id: str, label: str) -> str:
    """Link an escaped label to one of the fixed definitions."""
    if term_id not in _TERMS:
        raise ValueError("unknown report glossary term")
    return f'<a href="#glossary-{term_id}">{html.escape(label, quote=True)}</a>'


def render_glossary(return_href: str = '#verdict') -> str:
    """Render definitions with a native, report-local return link."""
    if not re.fullmatch(r"#[a-zA-Z][a-zA-Z0-9_-]*", return_href):
        raise ValueError("glossary return must be a report anchor")
    entries = "\n".join(
        f'<dt id="glossary-{key}">{html.escape(label)}</dt><dd>{html.escape(definition)}</dd>'
        for key, (label, definition) in _TERMS.items()
    )
    return (
        '<section id="glossary" tabindex="-1" aria-label="Glossary"><h2>Glossary</h2>'
        '<p>Definitions explain the recorded report vocabulary. Policy values and evidence '
        'that are not supplied remain unavailable. GT means ground truth; ID means identifier.</p>'
        f'<dl style="max-width:72ch;line-height:1.55">{entries}</dl>'
        f'<p><a href="{html.escape(return_href, quote=True)}">Return to report</a></p></section>'
    )
