# Controlled UI vocabulary

`controlled-vocabulary.json` is the source of truth for operator-facing
WordPress translation strings. It applies NAV-13 before labels freeze: each
term has a plain-language replacement, a short definition, and a reason for
the choice. `scripts/check_controlled_vocabulary.py` scans literal arguments
to WordPress translation calls (`__`, `_e`, `_n`, and `_x`) in the plugin's
JavaScript, TypeScript, and PHP source.

The gate runs in `baseline` mode. The `known_violations` list records the
current source debt so existing copy does not hide a new regression. A new
occurrence, a new message, or a new path fails the gate. Baseline entries are
keyed by path, normalized message, and banned term; repeated occurrences are
tracked in the `occurrences` count. `--report-all` prints the known entries
and identifies entries that have disappeared so the next copy-cleanup wave can
remove them.

The current contract covers these operator terms:

| Don't say | Say | Use when |
| --- | --- | --- |
| cluster, clusters, clustered, clustering | face group / group faces | Naming the visible group or the grouping action |
| embedding, embeddings | face signature, or omit the detail | The recognition implementation helps an operator decide |
| tenant, tenants | this site | Referring to the current WordPress site |
| provenance | where this came from | Explaining the source of a result or record |
| outlier, outliers | unmatched face | Describing a detected face with no group |

The checker scans the plugin source tree, excluding tests, fixtures, generated
assets, dependencies, and build output. Code identifiers, API fields, database
names, job IDs, and comments are outside this copy gate. Literal strings built
dynamically are also outside its parser; the existing rendered-surface sweep
in `js/admin/__tests__/banned-vocabulary.test.tsx` supplies the complementary
DOM and accessibility-attribute check for its covered fixtures.

## Review acceptance protocol

1. Run `make check-controlled-vocabulary` from the repository root and confirm
   that it reports no new violations.
2. Run the bounded checker tests:
   `python3 -m pytest scripts/test_check_controlled_vocabulary.py -q`.
3. For a vocabulary change, add a fixture that fails before the checker or
   contract change, then prove the same fixture passes after the change.
4. Review any baseline edit against the current source with
   `--report-all`; each retained entry needs a real current call site and each
   removed entry needs a corresponding copy fix or an explicit next-wave note.
5. Re-run the relevant rendered UI vocabulary test when a page or copy module
   changes. A green checker does not claim that every dynamic or unmounted
   surface was rendered.

The design anchor is [NAV-13](../../../../heuristics-canon-research/lexicons/interaction-ux.md#nav-13): publish preferred terms,
don't-say terms, and definitions before label freeze. The mechanism is also
consistent with the `controlled-vocabulary-caps-hallucination` reasoning card
and [WRIT-03](../../../../heuristics-canon-research/lexicons/writing.md#writ-03)'s plain-language test. These references guide the
contract; the checker and current baseline are the repository's executable
acceptance surface.
