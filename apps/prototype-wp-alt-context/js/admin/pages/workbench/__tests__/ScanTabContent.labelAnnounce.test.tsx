import React from 'react';
import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { REVIEW_QUEUE_LABEL_SAVED_ANNOUNCE } from '../identity-clusters/ReviewQueue';
import { ScanTabContent } from '../ScanTabContent';

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
}));

const panelState = { mode: 'label' as 'none' | 'label' | 'review', clusterId: 'cluster-1' as string | null };

vi.mock('../../../../components/ErrorBoundary', () => ({
  ErrorBoundary: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

vi.mock('../../../hooks/useScrollRestoration', () => ({
  useScrollRestoration: () => undefined,
}));

vi.mock('../../../hooks/useWorkbenchFilters', () => ({
  useWorkbenchFilters: () => ({
    queueState: { index: 0, kind: 'all', band: 'all' },
    dispatchQueue: vi.fn(),
  }),
}));

vi.mock('../Panels', () => ({
  ScanActionPanel: () => <div data-testid="scan-action-panel" />,
  isClusteringActive: () => false,
}));

vi.mock('../JobTimeline', () => ({
  JobTimeline: () => <div data-testid="job-timeline" />,
}));

vi.mock('../identity-clusters', () => ({
  ClusterLabelingPanel: ({ onLabel }: { onLabel: () => void }) => (
    <button type="button" onClick={() => onLabel()}>
      Save name
    </button>
  ),
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

vi.mock('../identity-clusters/useOpenReviewTargetLifecycle', () => ({
  useOpenReviewTargetLifecycle: () => ({ reviewClusterId: null }),
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

describe('ScanTabContent — R1-29 label announce + focus', () => {
  afterEach(cleanup);

  it('announces name-saved copy and focuses the queue root after a label commit', async () => {
    const user = userEvent.setup();
    const { container } = render(<ScanTabContent />);

    const live = container.querySelector('.acx-review-lifecycle-announce');
    expect(live).not.toBeNull();

    await user.click(screen.getByRole('button', { name: 'Save name' }));

    // DUX-W2R1-RV-01: no seq key — announce mutates the already-mounted region.
    expect(container.querySelector('.acx-review-lifecycle-announce')).toBe(live);
    expect(live?.textContent).toBe(REVIEW_QUEUE_LABEL_SAVED_ANNOUNCE);
    expect(container.querySelector('.acx-findings-detail-anchor')).toBe(document.activeElement);
  });
});
