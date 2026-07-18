import { describe, expect, it } from 'vitest';

import { selectMediaFooterCtaState } from '../mediaFooterCtaState';

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
