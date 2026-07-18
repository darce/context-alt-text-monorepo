import { describe, expect, it } from 'vitest';

import {
  footerAccentPrimaryCount,
  selectMediaFooterCtaState,
  viewportAccentPrimaryCount,
  type MediaFooterCtaInputs,
} from '../mediaFooterCtaState';

/**
 * §7 media-footer CTA hierarchy + the viewport single-accent-primary invariant.
 * Walks every screen state and reconciles the footer against the review card:
 * EXACTLY ONE accent-carrying primary survives per rendered viewport state
 * (COL-03/COL-09). `--acx-color-accent-soft` selection/focus tints are exempt and
 * are not modelled by the selector.
 */
describe('selectMediaFooterCtaState (§7)', () => {
  it('select state → Analyze is the single accent primary, Describe secondary', () => {
    const state = selectMediaFooterCtaState({ reviewActive: false, describeRunning: false });
    expect(state).toEqual({ accentOwner: 'analyze', analyzeVariant: 'primary', describeVariant: 'secondary' });
  });

  it('describe run in flight → its progress owns the surface; Analyze steps down', () => {
    const state = selectMediaFooterCtaState({ reviewActive: false, describeRunning: true });
    expect(state).toEqual({ accentOwner: 'describe', analyzeVariant: 'secondary', describeVariant: 'secondary' });
  });

  it('review active → the card primary owns the accent; both footer CTAs secondary', () => {
    const state = selectMediaFooterCtaState({ reviewActive: true, describeRunning: false });
    expect(state).toEqual({ accentOwner: 'card', analyzeVariant: 'secondary', describeVariant: 'secondary' });
  });

  it('review active outranks a describe run for accent ownership (no doubled accent)', () => {
    const state = selectMediaFooterCtaState({ reviewActive: true, describeRunning: true });
    expect(state.accentOwner).toBe('card');
    expect(state.analyzeVariant).toBe('secondary');
    expect(state.describeVariant).toBe('secondary');
  });
});

describe('viewport single-accent-primary invariant (§7 / COL-03)', () => {
  // Every combination of the two orthogonal footer inputs is a screen state.
  const allStates: MediaFooterCtaInputs[] = [
    { reviewActive: false, describeRunning: false },
    { reviewActive: false, describeRunning: true },
    { reviewActive: true, describeRunning: false },
    { reviewActive: true, describeRunning: true },
  ];

  it.each(allStates)(
    'counts EXACTLY ONE accent primary (footer reconciled against the card) for %o',
    (inputs) => {
      const state = selectMediaFooterCtaState(inputs);
      // Footer contributes its accent element; the card contributes 1 iff review
      // is active (asserted structurally by ReviewQueue's single-primary tests).
      expect(footerAccentPrimaryCount(state)).toBe(inputs.reviewActive ? 0 : 1);
      expect(viewportAccentPrimaryCount(state, inputs.reviewActive)).toBe(1);
    },
  );
});
