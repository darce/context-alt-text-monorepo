import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { WorkbenchPage } from '../WorkbenchPage';

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
  sprintf: (format: string, ...args: (string | number)[]) => {
    let index = 0;
    return format.replace(/%(s|d)/g, () => String(args[index++]));
  },
}));

const { pipeline } = vi.hoisted(() => ({
  pipeline: {
    scanRun: {
      isSynced: false,
      isScanning: false,
      progress: undefined as { clusters_created?: number } | undefined,
    },
    status: {
      isOnline: true,
      projectionSyncState: 'idle' as string,
      projectionError: null as string | null,
      currentPhase: 'idle' as string,
      scanProgress: null as { clusters_created?: number } | null,
      clusterProgress: null as { clusters_created?: number } | null,
    },
    retryProjectionSync: vi.fn(),
  },
}));

vi.mock('../workbench/WorkbenchContext', () => ({
  WorkbenchProvider: ({ children }: { children: React.ReactNode }) => children,
}));

vi.mock('../workbench/WorkbenchNavContext', () => ({
  useWorkbenchNav: () => ({
    activeSection: 'scan',
    recognitionSource: 'hosted',
    effectiveTargetUrl: '',
    activeOverlay: null,
    setActiveOverlay: vi.fn(),
    isAdvancedOpen: false,
    setAdvancedOpen: vi.fn(),
  }),
}));

vi.mock('../workbench/ClusterPanelContext', () => ({
  useClusterPanel: () => ({
    clusterPanel: { mode: 'none', clusterId: null },
    dispatchClusterPanel: vi.fn(),
  }),
}));

vi.mock('../workbench/JobPipelineContext', () => ({
  useJobPipeline: () => pipeline,
}));

vi.mock('../workbench/WorkbenchMediaContext', () => ({
  useWorkbenchMediaContext: () => ({
    mediaQueue: { detailTruncationNotice: null },
  }),
}));

vi.mock('../workbench/ReviewSurfaceContext', () => ({
  useReviewSurface: () => ({ cardPrimaryPresent: false }),
}));

vi.mock('../../hooks/usePanesParam', () => ({
  usePanesParam: () => ['both', vi.fn()],
}));

vi.mock('../workbench/ScanTabContent', () => ({
  ScanTabContent: () => <div data-testid="scan-tab-stub" />,
}));

vi.mock('../workbench/MediaSelection', () => ({
  MediaSelection: () => <div data-testid="media-selection-stub" />,
}));

vi.mock('../workbench/AdvancedDrawer', () => ({
  AdvancedDrawer: () => null,
}));

vi.mock('../workbench/ConflictInbox', () => ({
  ConflictInbox: () => null,
}));

vi.mock('../workbench/DeadLetterPanel', () => ({
  DeadLetterPanel: () => null,
}));

vi.mock('../workbench/SyncStatusIndicator', () => ({
  SyncStatusIndicator: () => null,
}));

const resetPipeline = (): void => {
  pipeline.scanRun.isSynced = false;
  pipeline.scanRun.isScanning = false;
  pipeline.scanRun.progress = undefined;
  pipeline.status.isOnline = true;
  pipeline.status.projectionSyncState = 'idle';
  pipeline.status.projectionError = null;
  pipeline.status.currentPhase = 'idle';
  pipeline.status.scanProgress = null;
  pipeline.status.clusterProgress = null;
  pipeline.retryProjectionSync.mockReset();
};

describe('W3-C-01 WorkbenchPage face-group status region', () => {
  beforeEach(() => {
    resetPipeline();
  });

  it('mounts the status region from WorkbenchPage (deleting the mount goes red)', () => {
    render(<WorkbenchPage />);
    expect(screen.getByTestId('acx-zone-z-cluster-umap')).toBeInTheDocument();
    expect(screen.getByRole('region', { name: 'Face-group status' })).toBeInTheDocument();
  });

  it('wires projectionSyncState=error to the error copy and Retry', async () => {
    pipeline.status.projectionSyncState = 'error';
    pipeline.status.projectionError = 'sync failed';
    render(<WorkbenchPage />);

    const zone = screen.getByTestId('acx-zone-z-cluster-umap');
    expect(zone).toHaveAttribute('data-acx-zone-state', 'error');
    expect(screen.getByRole('alert')).toHaveTextContent('Unable to load face-group status.');
    await userEvent.click(screen.getByRole('button', { name: 'Retry' }));
    expect(pipeline.retryProjectionSync).toHaveBeenCalledTimes(1);
  });

  it('wires zero face groups from scanRun.progress to empty', () => {
    pipeline.scanRun.progress = { clusters_created: 0 };
    render(<WorkbenchPage />);

    expect(screen.getByTestId('acx-zone-z-cluster-umap')).toHaveAttribute('data-acx-zone-state', 'empty');
    expect(screen.getByText('No face groups yet.')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Go to Scan' })).toHaveAttribute('href', '#/workbench?tab=scan');
  });

  it('wires isSynced loading with a live status region', () => {
    pipeline.scanRun.isSynced = true;
    render(<WorkbenchPage />);

    const zone = screen.getByTestId('acx-zone-z-cluster-umap');
    expect(zone).toHaveAttribute('data-acx-zone-state', 'loading');
    const status = within(zone).getByRole('status');
    expect(status).toHaveTextContent('Loading face-group status…');
    expect(status).toHaveAttribute('aria-live', 'polite');
  });

  it('wires offline to degraded', () => {
    pipeline.status.isOnline = false;
    render(<WorkbenchPage />);

    expect(screen.getByTestId('acx-zone-z-cluster-umap')).toHaveAttribute('data-acx-zone-state', 'degraded');
    expect(screen.getByText('Face-group status is running with reduced data.')).toBeInTheDocument();
  });

  it('wires idle with no cluster count to first_time', () => {
    render(<WorkbenchPage />);

    expect(screen.getByTestId('acx-zone-z-cluster-umap')).toHaveAttribute('data-acx-zone-state', 'first_time');
    expect(screen.getByText('Scan media to find face groups.')).toBeInTheDocument();
  });
});
