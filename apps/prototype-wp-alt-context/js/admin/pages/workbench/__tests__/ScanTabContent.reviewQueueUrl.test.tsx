/**
 * UXW2-1 — review-queue filter chips own exactly one truth: the `rq=` URL param.
 *
 * REAL MemoryRouter + REAL (unmocked) useWorkbenchFilters + REAL ReviewQueue.
 * Only non-domain seams are mocked (TEST-19): REST API layer, job-pipeline /
 * cluster-panel / media / review-surface contexts, and the sibling panels.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import React from 'react';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { QUEUE_ACTION, useWorkbenchFilters } from '../../../hooks/useWorkbenchFilters';

import {
  fetchPendingMergeSuggestions,
  fetchPendingNameSuggestions,
  fetchPendingSuggestions,
  fetchTopUnlabeledClusters,
} from '../../../api/recognition';
import { DATA_SOURCE } from '../../../api/recognition/types';
import { resetConfigCache } from '../../../api/config';
import { listRosterEntries } from '../../../api/rosterApi';
import { MergeSurvivorProvider } from '../identity-clusters/MergeSurvivorContext';
import { ScanTabContent } from '../ScanTabContent';

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
  _n: (single: string, plural: string, number: number) => (number === 1 ? single : plural),
  sprintf: (format: string, ...args: (string | number)[]) => {
    let i = 0;
    return format.replace(/%(\d+)\$[sd]|%[sd]/g, () => String(args[i++]));
  },
}));

vi.mock('@radix-ui/react-avatar', async () => {
  const ReactMod = await import('react');
  return {
    Root: ReactMod.forwardRef(function MockRoot({ children, ...props }: Record<string, unknown>, ref: unknown) {
      return ReactMod.createElement(
        'span',
        { ...props, ref } as React.HTMLAttributes<HTMLSpanElement>,
        children as React.ReactNode,
      );
    }),
    Image: ReactMod.forwardRef(function MockImage(props: Record<string, unknown>, ref: unknown) {
      return ReactMod.createElement('img', { ...props, ref } as React.ImgHTMLAttributes<HTMLImageElement>);
    }),
    Fallback: ReactMod.forwardRef(function MockFallback() {
      return null;
    }),
  };
});

vi.mock('../../../api/recognition', async () => {
  const actual = await vi.importActual<typeof import('../../../api/recognition')>('../../../api/recognition');
  return {
    ...actual,
    fetchPendingSuggestions: vi.fn(),
    fetchPendingMergeSuggestions: vi.fn(),
    fetchPendingNameSuggestions: vi.fn(),
    acceptSuggestion: vi.fn(),
    acceptMergeSuggestion: vi.fn(),
    acceptNameSuggestion: vi.fn(),
    rejectSuggestion: vi.fn(),
    rejectMergeSuggestion: vi.fn(),
    rejectNameSuggestion: vi.fn(),
    bulkAcceptSuggestions: vi.fn(),
    fetchClusterMembers: vi.fn().mockResolvedValue({ members: [], limit: 25, total: 0, truncated: false }),
    fetchTopUnlabeledClusters: vi.fn(),
    dismissCluster: vi.fn().mockResolvedValue(undefined),
    mergeCluster: vi.fn().mockResolvedValue(undefined),
    updateClusterLabel: vi.fn().mockResolvedValue(undefined),
  };
});

vi.mock('../../../api/rosterApi', () => ({
  commitClusterToRosterEntry: vi.fn(),
  listRosterEntries: vi.fn().mockResolvedValue([]),
}));

vi.mock('../../../hooks/useScrollRestoration', () => ({
  useScrollRestoration: () => undefined,
}));

vi.mock('../Panels', () => ({
  ScanActionPanel: () => <div data-testid="scan-action-panel" />,
  isClusteringActive: () => false,
}));

vi.mock('../JobTimeline', () => ({
  JobTimeline: () => <div data-testid="job-timeline" />,
}));

// Keep the REAL ReviewQueue; stub only the sibling panels (non-domain seams here).
vi.mock('../identity-clusters', async () => {
  const actual = await vi.importActual<typeof import('../identity-clusters')>('../identity-clusters');
  return {
    ...actual,
    ClusterLabelingPanel: () => <div data-testid="label-panel" />,
    ClusterReviewPanel: () => <div data-testid="review-panel" />,
    WorkbenchFindingsPanel: () => <div data-testid="findings-panel" />,
  };
});

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
    clusterPanel: { mode: 'none', clusterId: null },
    dispatchClusterPanel: vi.fn(),
  }),
}));

vi.mock('../WorkbenchMediaContext', () => ({
  useWorkbenchMediaContext: () => ({ mediaQueue: { hasIdentities: true } }),
}));

vi.mock('../ReviewSurfaceContext', () => ({
  useReviewSurface: () => ({ cardPrimaryPresent: false, setCardPrimaryPresent: vi.fn() }),
}));

const ASSIGNMENT_SUGGESTIONS = [
  {
    id: 'sugg-1',
    identity_id: 'identity-1',
    suggested_cluster_id: 'cluster-1',
    representative_similarity: 0.9,
    avg_member_similarity: 0.85,
    cluster_label: 'Alex',
    cluster_identity_count: 3,
  },
  {
    id: 'sugg-2',
    identity_id: 'identity-2',
    suggested_cluster_id: 'cluster-2',
    representative_similarity: 0.8,
    avg_member_similarity: 0.75,
    cluster_label: 'Jordan',
    cluster_identity_count: 2,
  },
];

const MERGE_SUGGESTIONS = [
  {
    id: 'merge-1',
    cluster_a_id: 'a',
    cluster_b_id: 'b',
    similarity: 0.88,
    status: 'pending',
    cluster_a_label: 'Alex',
    cluster_b_label: 'Jordan',
  },
  {
    id: 'merge-2',
    cluster_a_id: 'c',
    cluster_b_id: 'd',
    similarity: 0.8,
    status: 'pending',
    cluster_a_label: 'Casey',
    cluster_b_label: 'Drew',
  },
];

const LocationProbe = (): React.JSX.Element => {
  const loc = useLocation();
  return <output data-testid="loc">{loc.search}</output>;
};

const mountScanTab = (url: string) => {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, retryDelay: 0 } },
  });
  return render(
    <MemoryRouter initialEntries={[url]}>
      <QueryClientProvider client={queryClient}>
        <MergeSurvivorProvider>
          <ScanTabContent />
          <LocationProbe />
        </MergeSurvivorProvider>
      </QueryClientProvider>
    </MemoryRouter>,
  );
};

const locSearch = (): string => screen.getByTestId('loc').textContent ?? '';

/** Minimal real `p` writer (second useWorkbenchFilters instance = WorkbenchMediaProvider). */
const DualSearchParamWriter = (): React.JSX.Element => {
  const queue = useWorkbenchFilters();
  const media = useWorkbenchFilters();
  const loc = useLocation();
  return (
    <div>
      <button
        type="button"
        onClick={() => {
          queue.dispatchQueue({ type: QUEUE_ACTION.SET_KIND, kind: 'assignment' });
          queue.dispatchQueue({ type: QUEUE_ACTION.SET_INDEX, index: 1 });
          media.setCurrentPage(2);
        }}
      >
        collide
      </button>
      <output data-testid="loc">{loc.search}</output>
    </div>
  );
};

describe('ScanTabContent review-queue chips → rq= URL (single owner)', () => {
  beforeEach(() => {
    window.AltContextAdmin = {
      nonce: 'test-nonce',
      ajaxUrl: '/wp-admin/admin-ajax.php',
      endpoints: {
        recognitionSuggestions: 'http://localhost/recognition/suggestions',
        recognitionMergeSuggestions: 'http://localhost/recognition/suggestions/merge',
        recognitionNameSuggestions: 'http://localhost/recognition/suggestions/name',
        recognitionBulkAcceptSuggestions: 'http://localhost/recognition/suggestions/bulk-accept',
        recognitionClusters: 'http://localhost/recognition/clusters',
      },
      tenant_id: 'test-tenant-id',
    };
    vi.mocked(fetchPendingSuggestions).mockResolvedValue({
      suggestions: ASSIGNMENT_SUGGESTIONS,
      limit: 10,
      offset: 0,
    });
    vi.mocked(fetchPendingMergeSuggestions).mockResolvedValue({
      suggestions: MERGE_SUGGESTIONS,
      limit: 10,
      offset: 0,
    });
    vi.mocked(fetchPendingNameSuggestions).mockResolvedValue({ suggestions: [], limit: 25, offset: 0 });
    vi.mocked(fetchTopUnlabeledClusters).mockResolvedValue({
      clusters: [],
      limit: 20,
      total: 0,
      truncated: false,
      singleton_count: 0,
      data_source: DATA_SOURCE.LOCAL_PROJECTION,
    });
    vi.mocked(listRosterEntries).mockResolvedValue([]);
    resetConfigCache();
  });

  it('chip click → aria-pressed=true AND rq=assignment.all.0; Next keeps it; chip again removes rq', async () => {
    const user = userEvent.setup();
    mountScanTab('/');

    const chip = await screen.findByRole('button', { name: 'Close matches' });
    await screen.findByText(/Is this/);

    await user.click(chip);
    await waitFor(() => {
      expect(locSearch()).toContain('rq=assignment.all.0');
    });
    expect(screen.getByRole('button', { name: 'Close matches' })).toHaveAttribute('aria-pressed', 'true');

    await user.click(screen.getByRole('button', { name: 'Next review item' }));
    await waitFor(() => {
      expect(locSearch()).toContain('rq=assignment.all.1');
    });
    expect(screen.getByRole('button', { name: 'Close matches' })).toHaveAttribute('aria-pressed', 'true');

    await user.click(screen.getByRole('button', { name: 'Close matches' }));
    await waitFor(() => {
      expect(locSearch()).not.toContain('rq=');
    });
    expect(screen.getByRole('button', { name: 'Close matches' })).toHaveAttribute('aria-pressed', 'false');
  });

  it('band + kind combine into rq=assignment.strong.0', async () => {
    const user = userEvent.setup();
    mountScanTab('/');
    await screen.findByText(/Is this/);

    await user.click(screen.getByRole('button', { name: 'Close matches' }));
    await user.click(screen.getByRole('button', { name: 'Strong matches' }));
    await waitFor(() => {
      expect(locSearch()).toContain('rq=assignment.strong.0');
    });
    expect(screen.getByRole('button', { name: 'Close matches' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByRole('button', { name: 'Strong matches' })).toHaveAttribute('aria-pressed', 'true');
  });

  it('Clear filters removes rq and unpresses both chip groups', async () => {
    vi.mocked(fetchPendingMergeSuggestions).mockResolvedValue({ suggestions: [], limit: 10, offset: 0 });
    const user = userEvent.setup();
    mountScanTab('/');
    await screen.findByText(/Is this/);

    await user.click(screen.getByRole('button', { name: 'Possible duplicates' }));
    await user.click(screen.getByRole('button', { name: 'Strong matches' }));
    await waitFor(() => {
      expect(locSearch()).toContain('rq=merge.strong.0');
    });

    const clearBtn = await screen.findByRole('button', { name: 'Clear filters' });
    await user.click(clearBtn);
    await waitFor(() => {
      expect(locSearch()).not.toContain('rq=');
    });
    expect(screen.getByRole('button', { name: 'Possible duplicates' })).toHaveAttribute('aria-pressed', 'false');
    expect(screen.getByRole('button', { name: 'Strong matches' })).toHaveAttribute('aria-pressed', 'false');
  });

  it('deep link rq=merge.all.1 survives Prev (kind) and Strong chip (band stays merge)', async () => {
    const user = userEvent.setup();
    mountScanTab('/?rq=merge.all.1');
    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Possible duplicates' })).toHaveAttribute('aria-pressed', 'true');
    });
    expect(await screen.findByText('2 of 2')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Previous review item' }));
    await waitFor(() => {
      expect(locSearch()).toContain('rq=merge.all.0');
    });
    expect(screen.getByRole('button', { name: 'Possible duplicates' })).toHaveAttribute('aria-pressed', 'true');

    await user.click(screen.getByRole('button', { name: 'Strong matches' }));
    await waitFor(() => {
      expect(locSearch()).toContain('rq=merge.strong');
    });
    expect(screen.getByRole('button', { name: 'Possible duplicates' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByRole('button', { name: 'Strong matches' })).toHaveAttribute('aria-pressed', 'true');
  });

  it('page-clamp p writer from a second hook instance does not drop pending rq (R1-01)', () => {
    render(
      <MemoryRouter initialEntries={['/']}>
        <Routes>
          <Route path="/" element={<DualSearchParamWriter />} />
        </Routes>
      </MemoryRouter>,
    );

    act(() => {
      screen.getByText('collide').click();
    });
    expect(screen.getByTestId('loc').textContent).toContain('rq=assignment.all.1');
    expect(screen.getByTestId('loc').textContent).toContain('p=2');
  });

  it('oversized rq index clamps to last visible assignment card (R1-03)', async () => {
    mountScanTab('/?rq=assignment.all.9');
    await screen.findByText(/Is this/);
    await waitFor(() => {
      expect(locSearch()).toContain('rq=assignment.all.1');
    });
    expect(screen.getByText('2 of 2')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Close matches' })).toHaveAttribute('aria-pressed', 'true');
  });
});
