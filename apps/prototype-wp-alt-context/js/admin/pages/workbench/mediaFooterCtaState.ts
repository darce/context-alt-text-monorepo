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
 *    marker); the footer Describe CTA renders secondary (reconciled to a single
 *    viewport accent primary).
 *  - describe run in flight → its progress owns the footer surface.
 *  - select (default) → Describe is the single accent primary (WBUX-6 L2c).
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
      describeVariant: FOOTER_CTA_VARIANT.SECONDARY,
    };
  }
  if (describeRunning) {
    return {
      accentOwner: FOOTER_ACCENT_OWNER.DESCRIBE,
      describeVariant: FOOTER_CTA_VARIANT.SECONDARY,
    };
  }
  return {
    accentOwner: FOOTER_ACCENT_OWNER.DESCRIBE,
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

/**
 * Recognition-policy state for the footer primary (WBUX6-MRG-05).
 *
 * `GET /acx/v1/settings` is an I/O point on the primary action's path. Modelling it
 * as `boolean | undefined` overloaded "still loading" and "the fetch failed" into the
 * same value, and because that query runs with `retry: false`, a single failed fetch
 * left the primary held on `Loading settings…` with no timeout, no containment
 * boundary, and no degradation path — an unbounded wait on an integration point
 * [RES-13 lexicons/engineering.md:124], an undesigned state [RLSE-04 :695], and an
 * unreachable step that de-conforms the whole flow [A11Y-24 lexicons/accessibility.md:154].
 *
 * The four members make the states explicit. Note the asymmetry: a guard gating a
 * WRITE must fail closed, but this is a PROBE that only chooses whether to run an
 * optional enrichment pass; failing it closed strands the operator's primary action.
 * So `UNAVAILABLE` is a designed degraded outcome that RELEASES the hold and describes
 * with recognition treated as off — a reserved cheaper fallback path rather than a
 * breach turning into an outage [COST-10 lexicons/ml-systems.md:553], and a designed
 * secondary outcome instead of a forced answer [CAL-02 lexicons/ml-systems.md:322].
 * It is a STATE, not a hold; only `LOADING` holds.
 *
 * sr-007: centralized as an `as const` object so no caller compares bare strings.
 */
export const RECOGNITION_POLICY = {
  /** GET /settings has not resolved and has not failed — the only policy that holds. */
  LOADING: 'loading',
  ON: 'on',
  OFF: 'off',
  /** GET /settings failed with no usable policy — degrade, do not hold. */
  UNAVAILABLE: 'unavailable',
} as const;
export type RecognitionPolicy = (typeof RECOGNITION_POLICY)[keyof typeof RECOGNITION_POLICY];

export interface RecognitionPolicyInputs {
  /** React Query reported the settings fetch failed (with `retry: false`, terminally). */
  isError: boolean;
  /** `recognition_enabled` off the envelope. Boundary data — validated, never asserted (sr-005). */
  recognitionEnabled: unknown;
}

/**
 * Collapse (query error × envelope value) into one explicit policy.
 *
 * Ordering mirrors `deriveIdentitiesPresentationSource`: retained data outranks an
 * error, so a background refetch failing over a good cached policy keeps the real
 * policy rather than degrading a surface that already knows the answer. Only an
 * error with no usable boolean becomes `UNAVAILABLE`.
 *
 * The envelope value is validated explicitly against both booleans (sr-005) — any
 * other shape is "not a policy", never coerced.
 */
export const deriveRecognitionPolicy = ({
  isError,
  recognitionEnabled,
}: RecognitionPolicyInputs): RecognitionPolicy => {
  if (recognitionEnabled === true) {
    return RECOGNITION_POLICY.ON;
  }
  if (recognitionEnabled === false) {
    return RECOGNITION_POLICY.OFF;
  }
  return isError ? RECOGNITION_POLICY.UNAVAILABLE : RECOGNITION_POLICY.LOADING;
};

/**
 * The policy holds the primary only while it is genuinely unresolved. `UNAVAILABLE`
 * deliberately returns false: the hold releases and Describe proceeds.
 */
export const isRecognitionPolicyHolding = (policy: RecognitionPolicy): boolean =>
  policy === RECOGNITION_POLICY.LOADING;

/** Whether the identify pass runs before describe. Only a KNOWN-on policy triggers it. */
export const shouldIdentifyBeforeDescribe = (policy: RecognitionPolicy): boolean =>
  policy === RECOGNITION_POLICY.ON;

/**
 * What a click on the footer primary must actually do (WBUX6-W4-R-01).
 *
 * The container previously repeated the presentational hold conditions inline, so the
 * belt was unreachable behind the presentational buckle: deleting a term left every
 * test green because `submitHeld` blocked the click first — a guard that cannot be
 * driven red is a guard that certifies nothing [TEST-15 lexicons/engineering.md:396].
 * Naming the decision makes the container's own contract directly assertable, and the
 * effector stays a thin dispatcher over an exhaustive switch (sr-007).
 */
export const DESCRIBE_SUBMIT_ACTION = {
  /** Do nothing: a hold is in force. */
  HOLD: 'hold',
  /** Start the describe run immediately (recognition off, or its policy unavailable). */
  DESCRIBE: 'describe',
  /** Run the identify pass first, then describe (recognition known on). */
  IDENTIFY_THEN_DESCRIBE: 'identify_then_describe',
} as const;
export type DescribeSubmitAction = (typeof DESCRIBE_SUBMIT_ACTION)[keyof typeof DESCRIBE_SUBMIT_ACTION];

export interface DescribeSubmitInputs {
  offline: boolean;
  isIdentifying: boolean;
  recognitionPolicy: RecognitionPolicy;
  selectedCount: number;
}

export const resolveDescribeSubmitAction = ({
  offline,
  isIdentifying,
  recognitionPolicy,
  selectedCount,
}: DescribeSubmitInputs): DescribeSubmitAction => {
  if (offline || isIdentifying || selectedCount === 0 || isRecognitionPolicyHolding(recognitionPolicy)) {
    return DESCRIBE_SUBMIT_ACTION.HOLD;
  }
  return shouldIdentifyBeforeDescribe(recognitionPolicy)
    ? DESCRIBE_SUBMIT_ACTION.IDENTIFY_THEN_DESCRIBE
    : DESCRIBE_SUBMIT_ACTION.DESCRIBE;
};
