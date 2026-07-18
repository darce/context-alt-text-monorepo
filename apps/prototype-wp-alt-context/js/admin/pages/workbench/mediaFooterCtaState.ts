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

/** Footer-local accent-primary element count (the card's 1 lives outside the footer). */
export const footerAccentPrimaryCount = (state: MediaFooterCtaState): number =>
  state.accentOwner === 'card' ? 0 : 1;

/**
 * Viewport single-accent-primary invariant (§7 / COL-03): the footer's accent
 * count reconciled against the review card's contribution (1 when a review card
 * or panel primary is on screen, else 0) is EXACTLY ONE in every screen state.
 */
export const viewportAccentPrimaryCount = (state: MediaFooterCtaState, reviewActive: boolean): number =>
  footerAccentPrimaryCount(state) + (reviewActive ? 1 : 0);

/** DOM marker for the single accent-primary element — counted by the viewport assertion. */
export const ACCENT_PRIMARY_ATTR = 'data-acx-accent-primary';
