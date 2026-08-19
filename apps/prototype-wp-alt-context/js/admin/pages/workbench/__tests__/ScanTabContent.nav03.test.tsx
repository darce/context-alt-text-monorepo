import React from 'react';
import { cleanup, render } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { ScanTabContent } from '../ScanTabContent';

/**
 * E21-5 Slice 8 — NAV-03 rider: stable panel-mode chrome.
 *
 * Entering/leaving the `label`/`review` panel modes swaps only the anchor's
 * content — it must NOT restyle or relocate the surrounding queue chrome (the
 * findings anchor, the findings panel, the media footer). This is the layout
 * probe: the surrounding chrome signature is identical across all three modes and
 * only the anchor's single child differs.
 *
 * BR-79 scope note: the real, un-mocked chrome whose stability this asserts is the
 * queue-shell anchor (`.acx-findings-detail-anchor`) rendered by ScanTabContent
 * itself — its className, tabindex, and stable-order position are checked below
 * against the live DOM. The swappable children (queue/panels) and the peripheral
 * panels (findings panel, action panel) are stubbed because this probe is about
 * POSITION/IDENTITY stability, not their internals. (WBUX-5 S1c-2: the media footer
 * moved out of ScanTabContent into the sibling library host, so it is no longer part
 * of this subtree's chrome signature.)
 * JSDOM has no layout/computed-style engine, so a *restyle* (a CSS change that keeps
 * the same class names) cannot be detected here — that check belongs to the operator
 * visual re-baseline. This test guards the structural contract; it does not (and in
 * JSDOM cannot) guard pixels.
 */

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
}));

// Mutable panel state read by the mocked context hooks; each render reads current.
const panelState = { mode: 'none' as 'none' | 'label' | 'review', clusterId: null as string | null };
const lifecycleState = { reviewClusterId: null as string | null };

vi.mock('../../../../components/ErrorBoundary', () => ({
  ErrorBoundary: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

vi.mock('../../../hooks/useScrollRestoration', () => ({
  useScrollRestoration: () => undefined,
}));

vi.mock('../../../hooks/useWorkbenchFilters', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../../hooks/useWorkbenchFilters')>();
  return {
    ...actual,
    useWorkbenchFilters: () => ({
      queueState: { index: 0, kind: 'all', band: 'all' },
      dispatchQueue: vi.fn(),
    }),
  };
});

vi.mock('../Panels', () => ({
  ScanActionPanel: () => <div data-testid="scan-action-panel" />,
  isClusteringActive: () => false,
}));

vi.mock('../JobTimeline', () => ({
  JobTimeline: () => <div data-testid="job-timeline" />,
}));

vi.mock('../identity-clusters', () => ({
  ClusterLabelingPanel: () => <div data-testid="label-panel" />,
  ClusterReviewPanel: () => <div data-testid="review-panel" />,
  ReviewQueue: React.forwardRef<unknown, Record<string, unknown>>(function ReviewQueueStub() {
    return <div data-testid="review-queue" />;
  }),
  WorkbenchFindingsPanel: () => <div data-testid="findings-panel" />,
}));

vi.mock('../identity-clusters/useWorkbenchFindings', () => ({
  useWorkbenchFindings: () => ({
    hasFindings: true,
    isLoading: false,
    isError: false,
    isUnavailable: false,
  }),
}));

vi.mock('../identity-clusters/useAriaAnnounce', () => ({
  useAriaAnnounce: () => ({ message: '', seq: 0, announce: vi.fn() }),
}));

vi.mock('../identity-clusters/useOpenReviewTargetLifecycle', () => ({
  useOpenReviewTargetLifecycle: () => ({ reviewClusterId: lifecycleState.reviewClusterId }),
}));

vi.mock('../JobPipelineContext', () => ({
  useJobPipeline: () => ({
    scanRun: { isScanning: false, progress: null },
    status: {
      scanProgress: null,
      clusterProgress: null,
      currentPhase: 'idle',
      projectionSyncState: 'idle',
    },
    history: { activeJobIds: [], jobId: null },
    cancelScan: vi.fn(),
    retryScanStream: vi.fn(),
  }),
}));

vi.mock('../ClusterPanelContext', () => ({
  useClusterPanel: () => ({
    clusterPanel: panelState,
    dispatchClusterPanel: vi.fn(),
  }),
}));

vi.mock('../WorkbenchMediaContext', () => ({
  useWorkbenchMediaContext: () => ({ mediaQueue: { hasIdentities: true } }),
}));

vi.mock('../ReviewSurfaceContext', () => ({
  useReviewSurface: () => ({ cardPrimaryPresent: false, setCardPrimaryPresent: vi.fn() }),
}));

const SWAPPABLE = new Set(['review-queue', 'review-panel', 'label-panel']);

interface ChromeSignature {
  anchorClass: string;
  anchorTabIndex: string | null;
  stableOrder: string;
}

const chromeSignature = (container: HTMLElement): ChromeSignature => {
  const anchor = container.querySelector('.acx-findings-detail-anchor');
  if (!anchor) {
    throw new Error('findings-detail anchor missing');
  }
  const stableOrder = Array.from(container.querySelectorAll('[data-testid]'))
    .map((el) => (el as HTMLElement).dataset.testid ?? '')
    .filter((id) => !SWAPPABLE.has(id))
    .join(',');
  return {
    anchorClass: anchor.className,
    anchorTabIndex: anchor.getAttribute('tabindex'),
    stableOrder,
  };
};

const anchorContentTestId = (container: HTMLElement): string | undefined => {
  const anchor = container.querySelector('.acx-findings-detail-anchor');
  const child = anchor?.querySelector('[data-testid]') as HTMLElement | null;
  return child?.dataset.testid;
};

describe('ScanTabContent — NAV-03 stable panel-mode chrome (§2 rider)', () => {
  afterEach(cleanup);

  it('keeps the surrounding queue chrome identical across none/label/review modes', () => {
    panelState.mode = 'none';
    panelState.clusterId = null;
    lifecycleState.reviewClusterId = null;
    const queue = render(<ScanTabContent />);
    const queueSig = chromeSignature(queue.container);
    expect(anchorContentTestId(queue.container)).toBe('review-queue');
    cleanup();

    panelState.mode = 'label';
    panelState.clusterId = 'c1';
    lifecycleState.reviewClusterId = null;
    const label = render(<ScanTabContent />);
    const labelSig = chromeSignature(label.container);
    expect(anchorContentTestId(label.container)).toBe('label-panel');
    cleanup();

    panelState.mode = 'review';
    panelState.clusterId = 'c1';
    lifecycleState.reviewClusterId = 'c1';
    const review = render(<ScanTabContent />);
    const reviewSig = chromeSignature(review.container);
    expect(anchorContentTestId(review.container)).toBe('review-panel');

    // Only the anchor content swaps; the surrounding chrome is byte-identical.
    expect(labelSig).toEqual(queueSig);
    expect(reviewSig).toEqual(queueSig);
    // Real-chrome class-level assertions (BR-79): the queue-shell anchor is rendered
    // by ScanTabContent (not a stub), so its className/tabindex are the live DOM. A
    // class change here WOULD fail; a pure CSS restyle would not (JSDOM has no
    // computed styles) — that is the operator visual re-baseline's job, per the note.
    expect(queueSig.anchorClass).toBe('acx-findings-detail-anchor');
    expect(labelSig.anchorClass).toBe('acx-findings-detail-anchor');
    expect(reviewSig.anchorClass).toBe('acx-findings-detail-anchor');
    expect(queueSig.anchorTabIndex).toBe('-1');
  });
});
