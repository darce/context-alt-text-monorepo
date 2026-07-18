/**
 * E21-5 Slice 8 — media-footer CTA hierarchy (§7 state matrix).
 *
 * A small per-state selector deciding the SINGLE accent-carrying primary CTA in
 * the media footer, reconciled against the review card. Primacy is CHROMATIC
 * (accent bg + `--acx-color-accent-contrast` + semibold via tokens), not just
 * logical — the selector only decides which surface may carry the accent token;
 * the styling lives in `_workbench.scss` (sr-004) [COL-03][COL-09].
 *
 * Token roles (Design-direction preamble §3): primary = accent; secondary =
 * neutral/ghost, NO accent. Selection/focus tints on `--acx-color-accent-soft`
 * are exempt from the single-primary count and are not modelled here.
 */

/** Which surface owns the single accent-primary in a given viewport state. */
export type FooterAccentOwner = 'analyze' | 'describe' | 'card';

export type FooterCtaVariant = 'primary' | 'secondary';

export interface MediaFooterCtaState {
  /** Surface carrying the accent-primary token; `card` → no footer CTA is accent. */
  accentOwner: FooterAccentOwner;
  analyzeVariant: FooterCtaVariant;
  describeVariant: FooterCtaVariant;
}

export interface MediaFooterCtaInputs {
  /** A review card / label / review panel primary is mounted in the findings anchor. */
  reviewActive: boolean;
  /** A describe run is in flight — its progress owns the surface. */
  describeRunning: boolean;
}

/**
 * §7 per-state selector:
 *  - review active → the queue's card primary owns the accent; both footer CTAs
 *    render secondary (reconciled to a single viewport accent primary).
 *  - describe run in flight → its progress owns the footer surface; Analyze steps
 *    down to secondary.
 *  - select (default) → Analyze is the single accent primary, Describe secondary.
 *
 * Ordering matters: a review card outranks a describe run for accent ownership so
 * the card's on-screen primary is never doubled by the footer.
 *
 * This selector only decides which surface MAY carry the accent token; the single
 * accent-primary invariant is proven against the rendered DOM (`data-acx-accent-primary`
 * count) — see `mediaFooterSinglePrimary.dom.test.tsx` — not by arithmetic here.
 * `reviewActive` is the SAME signal the queue uses to place the card marker
 * (ScanTabContent wires ReviewQueue's card-primary presence into it), so the
 * footer demotion and the card marker can never disagree.
 */
export const selectMediaFooterCtaState = ({
  reviewActive,
  describeRunning,
}: MediaFooterCtaInputs): MediaFooterCtaState => {
  if (reviewActive) {
    return { accentOwner: 'card', analyzeVariant: 'secondary', describeVariant: 'secondary' };
  }
  if (describeRunning) {
    return { accentOwner: 'describe', analyzeVariant: 'secondary', describeVariant: 'secondary' };
  }
  return { accentOwner: 'analyze', analyzeVariant: 'primary', describeVariant: 'secondary' };
};

/** DOM marker for the single accent-primary element — counted by the DOM invariant test. */
export const ACCENT_PRIMARY_ATTR = 'data-acx-accent-primary';
