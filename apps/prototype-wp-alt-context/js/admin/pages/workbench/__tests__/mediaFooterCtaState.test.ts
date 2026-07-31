import { describe, expect, it } from 'vitest';

import { deriveReviewSurfaceActive, selectMediaFooterCtaState } from '../mediaFooterCtaState';

/**
 * §7 media-footer CTA hierarchy selector. This unit only fixes WHICH surface may
 * own the accent per state; the single-accent-primary invariant itself is proven
 * against the rendered DOM in `mediaFooterSinglePrimary.dom.test.tsx` (counting
 * `[data-acx-accent-primary]`), not by arithmetic over the selector's own output.
 * `--acx-color-accent-soft` selection/focus tints are exempt from that count.
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
