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

/**
 * Which surface owns the single accent-primary in a given viewport state.
 * sr-007: values centralized as an `as const` object; the type derives from it so
 * comparisons import the member instead of scattering bare string literals.
 */
export const FOOTER_ACCENT_OWNER = {
  ANALYZE: 'analyze',
  DESCRIBE: 'describe',
  CARD: 'card',
} as const;
export type FooterAccentOwner = (typeof FOOTER_ACCENT_OWNER)[keyof typeof FOOTER_ACCENT_OWNER];

export const FOOTER_CTA_VARIANT = {
  PRIMARY: 'primary',
  SECONDARY: 'secondary',
} as const;
export type FooterCtaVariant = (typeof FOOTER_CTA_VARIANT)[keyof typeof FOOTER_CTA_VARIANT];

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
 *  - review active → the queue owns the accent (its card marker or its bulk-commit
 *    marker); both footer CTAs render secondary (reconciled to a single viewport
 *    accent primary).
 *  - describe run in flight → its progress owns the footer surface; Analyze steps
 *    down to secondary.
 *  - select (default) → Describe is the single accent primary, Analyze secondary (WBUX-6 L2a).
 *
 * Ordering matters: an active review surface outranks a describe run for accent
 * ownership so the queue's on-screen primary is never doubled by the footer.
 *
 * This selector only decides which surface MAY carry the accent token; the single
 * accent-primary invariant is NOT guaranteed by construction here. `reviewActive` is
 * the SAME signal the queue derives to place its own accent marker (ScanTabContent
 * wires ReviewQueue's accent-ownership report into it), so footer demotion tracks the
 * queue's marker across the modeled states — but only the rendered-DOM count
 * (`data-acx-accent-primary`, see `mediaFooterSinglePrimary.dom.test.tsx`) is
 * authoritative, not this arithmetic.
 */
export const selectMediaFooterCtaState = ({
  reviewActive,
  describeRunning,
}: MediaFooterCtaInputs): MediaFooterCtaState => {
  if (reviewActive) {
    return {
      accentOwner: FOOTER_ACCENT_OWNER.CARD,
      analyzeVariant: FOOTER_CTA_VARIANT.SECONDARY,
      describeVariant: FOOTER_CTA_VARIANT.SECONDARY,
    };
  }
  if (describeRunning) {
    return {
      accentOwner: FOOTER_ACCENT_OWNER.DESCRIBE,
      analyzeVariant: FOOTER_CTA_VARIANT.SECONDARY,
      describeVariant: FOOTER_CTA_VARIANT.SECONDARY,
    };
  }
  return {
    accentOwner: FOOTER_ACCENT_OWNER.DESCRIBE,
    analyzeVariant: FOOTER_CTA_VARIANT.SECONDARY,
    describeVariant: FOOTER_CTA_VARIANT.PRIMARY,
  };
};

/** DOM marker for the single accent-primary element — counted by the DOM invariant test. */
export const ACCENT_PRIMARY_ATTR = 'data-acx-accent-primary';

export interface ReviewSurfaceActiveInputs {
  /** The queue reports a card/label/review primary is mounted in its findings anchor. */
  cardPrimaryPresent: boolean;
  /** The control (queue) pane is collapsed, so its accent marker is rendered `hidden`. */
  controlCollapsed: boolean;
}

/**
 * The footer only steps its CTAs down when the QUEUE's accent primary is actually on
 * screen. The queue lives in the control pane; when that pane is collapsed its card
 * marker is `hidden` (still mounted, so `cardPrimaryPresent` stays true), so the footer
 * must RECLAIM its accent primary — otherwise the viewport shows ZERO accent primaries.
 * This preserves the single-accent-primary contract across the two-pane collapse states
 * [WBUX-5 S1c-2].
 */
export const deriveReviewSurfaceActive = ({
  cardPrimaryPresent,
  controlCollapsed,
}: ReviewSurfaceActiveInputs): boolean => cardPrimaryPresent && !controlCollapsed;
