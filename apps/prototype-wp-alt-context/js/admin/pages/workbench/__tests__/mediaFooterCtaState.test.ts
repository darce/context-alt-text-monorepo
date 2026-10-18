import { describe, expect, it } from 'vitest';

import {
  DESCRIBE_SUBMIT_ACTION,
  RECOGNITION_POLICY,
  deriveRecognitionPolicy,
  deriveReviewSurfaceActive,
  isRecognitionPolicyHolding,
  resolveDescribeSubmitAction,
  selectMediaFooterCtaState,
  shouldIdentifyBeforeDescribe,
} from '../mediaFooterCtaState';

/**
 * §7 media-footer CTA hierarchy selector. This unit only fixes WHICH surface may
 * own the accent per state; the single-accent-primary invariant itself is proven
 * against the rendered DOM in `mediaFooterSinglePrimary.dom.test.tsx` (counting
 * `[data-acx-accent-primary]`), not by arithmetic over the selector's own output.
 * `--acx-color-accent-soft` selection/focus tints are exempt from that count.
 */
describe('selectMediaFooterCtaState (§7)', () => {
  it('select state: Describe is the single accent primary', () => {
    const state = selectMediaFooterCtaState({ reviewActive: false, describeRunning: false });
    expect(state).toEqual({ accentOwner: 'describe', describeVariant: 'primary' });
  });

  it('describe run in flight → its progress owns the surface', () => {
    const state = selectMediaFooterCtaState({ reviewActive: false, describeRunning: true });
    expect(state).toEqual({ accentOwner: 'describe', describeVariant: 'secondary' });
  });

  it('review active → the card primary owns the accent; footer CTA secondary', () => {
    const state = selectMediaFooterCtaState({ reviewActive: true, describeRunning: false });
    expect(state).toEqual({ accentOwner: 'card', describeVariant: 'secondary' });
  });

  it('review active outranks a describe run for accent ownership (no doubled accent)', () => {
    const state = selectMediaFooterCtaState({ reviewActive: true, describeRunning: true });
    expect(state.accentOwner).toBe('card');
    expect(state.describeVariant).toBe('secondary');
  });
});

/**
 * WBUX-5 S1c-2 collapse-aware reconciliation: the queue's accent primary lives in the
 * control pane. When that pane is collapsed its card marker is `hidden` but still mounted
 * (so `cardPrimaryPresent` stays true), so the footer must reclaim its accent primary or
 * the viewport shows ZERO accent primaries. `deriveReviewSurfaceActive` gates the footer's
 * `reviewActive` on the control pane actually being visible.
 */
describe('deriveReviewSurfaceActive (collapse-aware accent reconciliation)', () => {
  it('queue accent visible → footer defers (reviewActive true)', () => {
    expect(deriveReviewSurfaceActive({ cardPrimaryPresent: true, controlCollapsed: false })).toBe(true);
  });

  it('control pane collapsed → queue accent hidden → footer reclaims (reviewActive false)', () => {
    expect(deriveReviewSurfaceActive({ cardPrimaryPresent: true, controlCollapsed: true })).toBe(false);
  });

  it('no card primary → footer keeps its accent regardless of collapse', () => {
    expect(deriveReviewSurfaceActive({ cardPrimaryPresent: false, controlCollapsed: false })).toBe(false);
    expect(deriveReviewSurfaceActive({ cardPrimaryPresent: false, controlCollapsed: true })).toBe(false);
  });
});

/**
 * WBUX6-MRG-05. The settings probe runs with `retry: false`, so its failure is
 * terminal. Overloading `undefined` for "loading" and "failed" made the failure
 * indistinguishable from the wait, and the primary held forever — an I/O point with
 * no degradation path [RES-13 lexicons/engineering.md:124] and an undesigned state
 * [RLSE-04 :695]. These cases pin the asymmetry: LOADING holds; UNAVAILABLE releases.
 */
describe('deriveRecognitionPolicy (settings probe: loading vs failed)', () => {
  it('resolved true → ON', () => {
    expect(deriveRecognitionPolicy({ isError: false, recognitionEnabled: true })).toBe(
      RECOGNITION_POLICY.ON,
    );
  });

  it('resolved false → OFF (a real answer, not a fallback)', () => {
    expect(deriveRecognitionPolicy({ isError: false, recognitionEnabled: false })).toBe(
      RECOGNITION_POLICY.OFF,
    );
  });

  it('unresolved and not failed → LOADING', () => {
    expect(deriveRecognitionPolicy({ isError: false, recognitionEnabled: undefined })).toBe(
      RECOGNITION_POLICY.LOADING,
    );
  });

  it('failed with no usable policy → UNAVAILABLE, NOT LOADING (the whole point)', () => {
    const policy = deriveRecognitionPolicy({ isError: true, recognitionEnabled: undefined });
    expect(policy).toBe(RECOGNITION_POLICY.UNAVAILABLE);
    // Discrimination guard: collapsing the error back into the wait is the bug.
    expect(policy).not.toBe(RECOGNITION_POLICY.LOADING);
  });

  it('retained policy outranks a failed background refetch (cached answer is still an answer)', () => {
    expect(deriveRecognitionPolicy({ isError: true, recognitionEnabled: true })).toBe(
      RECOGNITION_POLICY.ON,
    );
    expect(deriveRecognitionPolicy({ isError: true, recognitionEnabled: false })).toBe(
      RECOGNITION_POLICY.OFF,
    );
  });

  it('validates the envelope value explicitly — non-boolean shapes are not a policy (sr-005)', () => {
    for (const value of ['true', 1, 0, null, {}, []]) {
      expect(deriveRecognitionPolicy({ isError: false, recognitionEnabled: value })).toBe(
        RECOGNITION_POLICY.LOADING,
      );
      expect(deriveRecognitionPolicy({ isError: true, recognitionEnabled: value })).toBe(
        RECOGNITION_POLICY.UNAVAILABLE,
      );
    }
  });
});

describe('recognition policy → primary-action consequences', () => {
  it('only LOADING holds the primary; UNAVAILABLE releases it (fail open on a probe)', () => {
    expect(isRecognitionPolicyHolding(RECOGNITION_POLICY.LOADING)).toBe(true);
    expect(isRecognitionPolicyHolding(RECOGNITION_POLICY.UNAVAILABLE)).toBe(false);
    expect(isRecognitionPolicyHolding(RECOGNITION_POLICY.ON)).toBe(false);
    expect(isRecognitionPolicyHolding(RECOGNITION_POLICY.OFF)).toBe(false);
  });

  it('only a KNOWN-on policy runs the identify pass — a failed probe never fabricates ON', () => {
    expect(shouldIdentifyBeforeDescribe(RECOGNITION_POLICY.ON)).toBe(true);
    expect(shouldIdentifyBeforeDescribe(RECOGNITION_POLICY.OFF)).toBe(false);
    expect(shouldIdentifyBeforeDescribe(RECOGNITION_POLICY.UNAVAILABLE)).toBe(false);
    expect(shouldIdentifyBeforeDescribe(RECOGNITION_POLICY.LOADING)).toBe(false);
  });
});

/**
 * WBUX6-W4-R-01. The container guard used to duplicate the presentational hold
 * conditions inline, where the presentational `submitHeld` blocked every click first —
 * so deleting a term left the whole suite green. A guard whose green cannot go red
 * certifies nothing [TEST-15 lexicons/engineering.md:396]. Naming the decision gives
 * the container's own contract a surface these cases can drive directly.
 */
describe('resolveDescribeSubmitAction (container submit guard)', () => {
  const base = {
    offline: false,
    isIdentifying: false,
    recognitionPolicy: RECOGNITION_POLICY.OFF,
    selectedCount: 2,
  };

  it('recognition OFF → describe immediately, no identify pass', () => {
    expect(resolveDescribeSubmitAction(base)).toBe(DESCRIBE_SUBMIT_ACTION.DESCRIBE);
  });

  it('recognition ON → identify first, then describe', () => {
    expect(
      resolveDescribeSubmitAction({ ...base, recognitionPolicy: RECOGNITION_POLICY.ON }),
    ).toBe(DESCRIBE_SUBMIT_ACTION.IDENTIFY_THEN_DESCRIBE);
  });

  it('settings probe UNAVAILABLE → describe anyway, recognition simply not applied', () => {
    expect(
      resolveDescribeSubmitAction({ ...base, recognitionPolicy: RECOGNITION_POLICY.UNAVAILABLE }),
    ).toBe(DESCRIBE_SUBMIT_ACTION.DESCRIBE);
  });

  it('settings probe still LOADING → HOLD (each hold term proven independently)', () => {
    expect(
      resolveDescribeSubmitAction({ ...base, recognitionPolicy: RECOGNITION_POLICY.LOADING }),
    ).toBe(DESCRIBE_SUBMIT_ACTION.HOLD);
  });

  it('offline → HOLD', () => {
    expect(resolveDescribeSubmitAction({ ...base, offline: true })).toBe(DESCRIBE_SUBMIT_ACTION.HOLD);
  });

  it('already identifying → HOLD (no double start)', () => {
    expect(resolveDescribeSubmitAction({ ...base, isIdentifying: true })).toBe(
      DESCRIBE_SUBMIT_ACTION.HOLD,
    );
  });

  it('zero selection → HOLD', () => {
    expect(resolveDescribeSubmitAction({ ...base, selectedCount: 0 })).toBe(
      DESCRIBE_SUBMIT_ACTION.HOLD,
    );
  });

  it('a hold outranks a KNOWN-on policy — an unresolved wait never starts an identify pass', () => {
    expect(
      resolveDescribeSubmitAction({
        ...base,
        offline: true,
        recognitionPolicy: RECOGNITION_POLICY.ON,
      }),
    ).toBe(DESCRIBE_SUBMIT_ACTION.HOLD);
  });
});
