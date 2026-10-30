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
      projectionSyncState: 'idle',
      projectionError: null as string | null,
      currentPhase: 'idle',
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

const panelState = { mode: 'none', clusterId: null as string | null };

vi.mock('../workbench/ClusterPanelContext', () => ({
  useClusterPanel: () => ({
    clusterPanel: panelState,
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
  MediaSelection: () => (
    <div data-testid="media-selection-stub">
      <input id="acx-media-search" type="search" aria-label="Search media" />
    </div>
  ),
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

describe('UXREC-1 WB_CONTROL composition', () => {
  beforeEach(() => {
    resetPipeline();
    panelState.mode = 'none';
    panelState.clusterId = null;
    window.matchMedia = vi.fn().mockImplementation((query: string) => ({
      matches: Number(/max-width: (\d+)/.exec(query)?.[1]) >= 719,
      media: query,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    }));
  });

  it('places compact beta expectations below the title and before the existing panels', () => {
    render(<WorkbenchPage />);
    const h1 = screen.getByRole('heading', { level: 1, name: 'Review Queue' });
    const notice = screen.getByTestId('beta-expectations-notice');
    expect(h1.nextElementSibling).toBe(notice);
    expect(notice.nextElementSibling).toHaveClass('acx-workbench__panels');
    expect(notice.querySelector('details')).not.toHaveAttribute('open');
  });

  it('removes the redundant library heading and paragraph from recognition controls', () => {
    render(<WorkbenchPage />);
    const control = screen.getByRole('region', { name: 'Control' });
    expect(within(control).queryByRole('heading', { name: 'Scan Media Queue' })).toBeNull();
    expect(within(control).queryByText(/Scan your library for images/)).toBeNull();
    expect(within(control).getByRole('heading', { name: 'Recognition evidence' })).toBeInTheDocument();
  });

  it('labels the existing selected face-group review without treating media selection as recognition', () => {
    panelState.mode = 'review';
    panelState.clusterId = 'group-42';
    render(<WorkbenchPage />);
    expect(screen.getByText('Reviewing face group: group-42')).toBeInTheDocument();
    expect(screen.getByText('Selected images and description runs are in Library.')).toBeInTheDocument();
  });

  it('stacks the actual pane host with Library first at the accepted narrow width', () => {
    render(<WorkbenchPage />);
    const shell = screen.getByTestId('workbench-two-pane');
    expect(shell).toHaveAttribute('data-layout', 'stacked');
    expect(shell.firstElementChild).toBe(screen.getByRole('region', { name: 'Library' }));
  });

  it('puts review evidence before the secondary site policy', () => {
    render(<WorkbenchPage />);
    const evidence = screen.getByTestId('scan-tab-stub');
    const policy = screen.getByRole('group', { name: 'Facial recognition' });
    expect(evidence.compareDocumentPosition(policy) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it('makes the one empty next step focus the real Library selection entry', async () => {
    render(<WorkbenchPage />);
    await userEvent.click(screen.getByRole('link', { name: 'Go to Scan' }));
    expect(screen.getByRole('searchbox', { name: 'Search media' })).toHaveFocus();
  });

  it('keeps projection failures and their existing retry visible', async () => {
    pipeline.status.projectionSyncState = 'error';
    render(<WorkbenchPage />);
    expect(screen.getByRole('alert')).toHaveTextContent('Unable to load face-group status.');
    await userEvent.click(screen.getByRole('button', { name: 'Retry' }));
    expect(pipeline.retryProjectionSync).toHaveBeenCalledOnce();
    expect(screen.getByTestId('scan-tab-stub')).toBeInTheDocument();
  });

  it('keeps offline observations separate from unknown or empty recognition evidence', () => {
    pipeline.status.isOnline = false;
    render(<WorkbenchPage />);
    expect(screen.getByText('Network connection lost. Reconnecting…')).toBeInTheDocument();
    expect(screen.getByText('Face-group status is running with reduced data.')).toBeInTheDocument();
    expect(screen.getByTestId('media-selection-stub')).toBeInTheDocument();
  });
});
