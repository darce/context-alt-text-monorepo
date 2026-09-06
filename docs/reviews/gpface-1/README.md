# GPFACE-1 adversarial review-lane artifacts

Raw output of the three GPFACE-1 review lanes (codex-remote `gpt-5.6-luna`,
effort `max`), reviewing `feature/gpface-1` @ `a820d3eb1`.

| File | reviewed_files | hypotheses | refuted | findings |
| --- | --- | --- | --- | --- |
| `gpface-1-r-a11y.findings.json` | 24 | 11 | 8 | 4 |
| `gpface-1-r-eng.findings.json` | 30 | 15 | 13 | 6 |
| `gpface-1-r-writing.findings.json` | 23 | 19 | 9 | 12 |

**These are not duplicates of the handoff DB — do not delete them as such.**
The `findings` arrays were recorded into workbay-handoff-mcp and are canonical
there (Review Findings Placement rule). The `reviewed_files` and `hypotheses`
arrays are not: MCP stores confirmed defects, so the 77 coverage entries and 30
refuted hypotheses — the evidence that each reviewer actually looked, and what
it cleared — exist only in these files.

Retained per heuristics canon [STOR-07] (precompute is an optimization, not the
source; keep the raw facts), [HAI-06] (audit trail must reconstruct the
decision), [PROV-01] (every output walks back to its evidence).

History: these were dropped during the GPFACE-1 teardown on 2026-09-06 on the
mistaken reading that they duplicated MCP rows, and restored the same day.
Lane branch tips are also preserved as `archive/gpface-1-*` tags.
