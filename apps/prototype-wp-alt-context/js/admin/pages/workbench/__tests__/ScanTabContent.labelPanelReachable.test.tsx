import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import React from 'react';
import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { ClusterPanelProvider } from '../ClusterPanelContext';
import { ScanTabContent } from '../ScanTabContent';

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
}));

const lifecycleState = { reviewClusterId: null as string | null };
const pipelineState = {
  isScanning: false,
  currentPhase: 'idle' as string,
};

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
  ClusterLabelingPanel: () => (
    <div data-testid="label-panel">
      <input role="combobox" aria-label="Name" />
    </div>
  ),
  ClusterReviewPanel: () => <div data-testid="review-panel" />,
  ReviewQueue: React.forwardRef<unknown, { onLabel?: (clusterId: string) => void }>(
    function ReviewQueueStub({ onLabel }) {
      return (
        <div data-testid="review-queue">
          <h3 id="acx-workbench-queue-heading">Review Suggestions</h3>
          <button type="button" onClick={() => onLabel?.('cluster-name-1')}>
            Merge or split this group
          </button>
        </div>
      );
    },
  ),
  WorkbenchFindingsPanel: () => (
    <div data-testid="findings-panel">
      <h3 id="acx-workbench-findings-heading">Recognition findings</h3>
    </div>
  ),
}));

vi.mock('../identity-clusters/useAriaAnnounce', () => ({
  useAriaAnnounce: () => ({ message: '', seq: 0, announce: vi.fn() }),
}));

vi.mock('../identity-clusters/useOpenReviewTargetLifecycle', () => ({
  useOpenReviewTargetLifecycle: () => ({ reviewClusterId: lifecycleState.reviewClusterId }),
}));

vi.mock('../JobPipelineContext', () => ({
  useJobPipeline: () => ({
    scanRun: { isScanning: pipelineState.isScanning, progress: null },
    status: {
      scanProgress: null,
      clusterProgress: null,
      currentPhase: pipelineState.currentPhase,
      projectionSyncState: 'idle',
    },
    history: { activeJobIds: [], jobId: null },
    cancelScan: vi.fn(),
    retryScanStream: vi.fn(),
  }),
}));

vi.mock('../WorkbenchMediaContext', () => ({
  useWorkbenchMediaContext: () => ({ mediaQueue: { hasIdentities: true } }),
}));

vi.mock('../ReviewSurfaceContext', () => ({
  useReviewSurface: () => ({ cardPrimaryPresent: false, setCardPrimaryPresent: vi.fn() }),
}));

describe('ScanTabContent labeling panel reachability (UXW2-3-R3-01)', () => {
  beforeEach(() => {
    lifecycleState.reviewClusterId = null;
    pipelineState.isScanning = false;
    pipelineState.currentPhase = 'idle';
  });

  afterEach(cleanup);

  it('curate control mounts the labeling panel Name combobox', async () => {
    render(
      <MemoryRouter>
        <ClusterPanelProvider>
          <ScanTabContent />
        </ClusterPanelProvider>
      </MemoryRouter>,
    );

    await userEvent.setup().click(screen.getByRole('button', { name: 'Merge or split this group' }));
    expect(await screen.findByRole('combobox', { name: 'Name' })).toBeInTheDocument();
  });

  it('ScanTabContent source dispatches open_label', () => {
    const here = path.dirname(fileURLToPath(import.meta.url));
    const scan = readFileSync(path.resolve(here, '../ScanTabContent.tsx'), 'utf8');
    expect(scan).toMatch(/type:\s*'open_label'/);
  });
});
