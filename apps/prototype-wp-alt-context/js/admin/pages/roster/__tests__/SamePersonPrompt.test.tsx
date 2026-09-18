import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
  acceptMergeSuggestion,
  fetchPendingMergeSuggestions,
  rejectMergeSuggestion,
  type BatchAnalyzeResponse,
  type ClusterSummary,
  type PendingMergeSuggestion,
} from '../../../api/recognition';
import type { RosterClusterCommitResponse, RosterEntry } from '../../../api/rosterApi';
import { useRecognitionCluster } from '../../../hooks/useRecognitionHooks';
import { useCreatePerson, useDeletePerson, useRosterEntries, useUpdatePerson } from '../../../hooks/useRosterHooks';
import { createMockMutation, createMockQuery } from '../../../test-utils/mockHooks';
import { RosterPage } from '../../RosterPage';
import { SAME_PERSON_PROMPT_SESSION_KEY, SamePersonPrompt } from '../SamePersonPrompt';
import { useClusterActions } from '../hooks/useClusterActions';
import { useClusterDragDrop } from '../hooks/useClusterDragDrop';
import { useClusterMediaMap } from '../hooks/useClusterMediaMap';
import { useTopUnlabeledTotal } from '../hooks/useTopUnlabeledTotal';

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
  _n: (single: string, plural: string, count: number) => (count === 1 ? single : plural),
  sprintf: (format: string, ...args: (string | number)[]) => {
    let index = 0;
    return format.replace(/%(s|d)/g, () => String(args[index++]));
  },
}));

vi.mock('../../../api/config', () => ({
  getEndpoint: vi.fn(() => '/acx/v1/recognition/suggestions/merge'),
  getConfig: vi.fn(() => ({
    nonce: 'test-nonce',
    ajaxUrl: '/wp-admin/admin-ajax.php',
    endpoints: { recognitionMergeSuggestions: '/acx/v1/recognition/suggestions/merge' },
    tenant_id: 'tenant-1',
  })),
}));

vi.mock('../../../api/recognition', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../../api/recognition')>();
  return {
    ...actual,
    fetchPendingMergeSuggestions: vi.fn(),
    acceptMergeSuggestion: vi.fn(),
    rejectMergeSuggestion: vi.fn(),
  };
});

vi.mock('../../../hooks/useRecognitionHooks', () => ({
  useRecognitionCluster: vi.fn(),
}));

vi.mock('../../../hooks/useRosterHooks', () => ({
  useRosterEntries: vi.fn(),
  useCreatePerson: vi.fn(),
  useUpdatePerson: vi.fn(),
  useDeletePerson: vi.fn(),
}));

vi.mock('../hooks/useClusterMediaMap', () => ({
  useClusterMediaMap: vi.fn(),
}));

vi.mock('../hooks/useClusterDragDrop', () => ({
  useClusterDragDrop: vi.fn(),
}));

vi.mock('../hooks/useClusterActions', () => ({
  useClusterActions: vi.fn(),
}));

vi.mock('../hooks/useTopUnlabeledTotal', () => ({
  useTopUnlabeledTotal: vi.fn(),
}));

vi.mock('../PersonWorkspacePanel', () => ({
  PersonWorkspacePanel: () => null,
}));

vi.mock('../../../../components/ui/FaceThumbnail', () => ({
  FaceThumbnail: ({ alt, mediaUrl }: { alt?: string; mediaUrl: string }) => <img alt={alt ?? ''} src={mediaUrl} />,
}));

const FACE_BBOX = { x: 10, y: 20, width: 80, height: 90 };

const makeSuggestion = (overrides: Partial<PendingMergeSuggestion> = {}): PendingMergeSuggestion => ({
  id: 'merge-1',
  cluster_a_id: 'cluster-a',
  cluster_b_id: 'cluster-b',
  similarity: 0.87,
  status: 'pending',
  cluster_a_label: 'Alex',
  cluster_b_label: 'Jordan',
  cluster_a_identity_count: 3,
  cluster_b_identity_count: 4,
  cluster_a_representative_media_url: 'http://example.test/a.jpg',
  cluster_a_representative_bbox: FACE_BBOX,
  cluster_b_representative_media_url: 'http://example.test/b.jpg',
  cluster_b_representative_bbox: FACE_BBOX,
  ...overrides,
});

const namedEntry = (overrides: Partial<RosterEntry> = {}): RosterEntry => ({
  id: 7,
  person_uuid: 'person-uuid-alice',
  name: 'Alice Anderson',
  tags: ['family'],
  cluster_count: 1,
  clusters: [],
  queue_memberships: [],
  updated_at: '2026-01-01T00:00:00Z',
  source_version: 1,
  projection_status: 'current',
  projection_refreshed_at: '2026-01-01T00:00:00Z',
  ...overrides,
});

const dragDropState = {
  dragPayload: null,
  dropTarget: null,
  isDragging: false,
  handleFaceDragStart: vi.fn(),
  handleFaceDragEnd: vi.fn(),
  handleDropTargetChange: vi.fn(),
  resetDragState: vi.fn(),
};

const clusterActionState = {
  reassignMutation: createMockMutation<void, Error, { faceId: string; targetClusterId: string | null }>({
    mutate: vi.fn(),
  }),
  rescanMutation: createMockMutation<
    BatchAnalyzeResponse,
    Error,
    { cluster: { id: string; sample_identities: { media_id: number }[] }; mediaIds: number[] }
  >({
    mutate: vi.fn(),
    isPending: false,
  }),
  commitMutation: createMockMutation<
    RosterClusterCommitResponse,
    Error,
    { clusterId: string; rosterEntryId?: number; newEntryName?: string }
  >({
    mutate: vi.fn(),
    isPending: false,
  }),
  rescanGate: {
    disabled: false,
    'aria-disabled': undefined as true | undefined,
    title: undefined as string | undefined,
  },
  errorMessage: null,
  resetAll: vi.fn(),
};

let queryClient: QueryClient | null = null;
let getItemSpy: ReturnType<typeof vi.spyOn>;
let setItemSpy: ReturnType<typeof vi.spyOn>;

const renderPrompt = (): ReturnType<typeof render> => {
  queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <SamePersonPrompt />
    </QueryClientProvider>,
  );
};

const stubPending = (suggestions: PendingMergeSuggestion[]): void => {
  vi.mocked(fetchPendingMergeSuggestions).mockResolvedValue({
    suggestions,
    limit: 10,
    offset: 0,
  });
};

describe('SamePersonPrompt', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    getItemSpy = vi.spyOn(Storage.prototype, 'getItem').mockReturnValue(null);
    setItemSpy = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => undefined);
    stubPending([makeSuggestion()]);
    vi.mocked(acceptMergeSuggestion).mockResolvedValue({
      ...makeSuggestion(),
      source_cluster_id: 'cluster-a',
      target_cluster_id: 'cluster-b',
      moved_identity_ids: [],
    });
    vi.mocked(rejectMergeSuggestion).mockResolvedValue(makeSuggestion({ status: 'rejected' }));
  });

  afterEach(() => {
    void queryClient?.cancelQueries();
    queryClient?.clear();
    queryClient = null;
    cleanup();
    vi.restoreAllMocks();
  });

  it('renders two face crops and names without a similarity percent as the primary signal', async () => {
    renderPrompt();

    expect(await screen.findByRole('heading', { name: 'Same or different person?' })).toBeInTheDocument();
    expect(screen.getByRole('img', { name: 'Alex' })).toHaveAttribute('src', 'http://example.test/a.jpg');
    expect(screen.getByRole('img', { name: 'Jordan' })).toHaveAttribute('src', 'http://example.test/b.jpg');
    expect(screen.getByText('Alex')).toBeInTheDocument();
    expect(screen.getByText('Jordan')).toBeInTheDocument();
    expect(screen.queryByText('87%')).not.toBeInTheDocument();
    expect(screen.queryByText(/87%\s*match/i)).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Yes' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'No' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Skip' })).toBeInTheDocument();
    expect(acceptMergeSuggestion).not.toHaveBeenCalled();
    expect(rejectMergeSuggestion).not.toHaveBeenCalled();
  });

  it('shows only the first pending suggestion', async () => {
    stubPending([
      makeSuggestion(),
      makeSuggestion({
        id: 'merge-2',
        cluster_a_label: 'Riley',
        cluster_b_label: 'Sam',
      }),
    ]);
    renderPrompt();

    expect(await screen.findByText('Alex')).toBeInTheDocument();
    expect(screen.getByText('Jordan')).toBeInTheDocument();
    expect(screen.queryByText('Riley')).not.toBeInTheDocument();
    expect(screen.queryByText('Sam')).not.toBeInTheDocument();
    expect(screen.getAllByTestId('acx-same-person-prompt')).toHaveLength(1);
  });

  it('does not present reserved cluster labels as names', async () => {
    stubPending([
      makeSuggestion({
        cluster_a_label: 'cluster-42',
        cluster_b_label: 'cluster_auto',
      }),
    ]);
    renderPrompt();

    expect(await screen.findByRole('heading', { name: 'Same or different person?' })).toBeInTheDocument();
    expect(screen.getAllByText('Unnamed person')).toHaveLength(2);
    expect(screen.queryByText('cluster-42')).not.toBeInTheDocument();
    expect(screen.queryByText('cluster_auto')).not.toBeInTheDocument();
  });

  it('merges through the verified accept route on Yes', async () => {
    const user = userEvent.setup();
    renderPrompt();
    await screen.findByRole('button', { name: 'Yes' });

    expect(acceptMergeSuggestion).not.toHaveBeenCalled();
    await user.click(screen.getByRole('button', { name: 'Yes' }));

    await waitFor(() => {
      expect(vi.mocked(acceptMergeSuggestion).mock.calls[0]?.[0]).toBe('merge-1');
    });
    expect(rejectMergeSuggestion).not.toHaveBeenCalled();
    await waitFor(() => {
      expect(screen.queryByTestId('acx-same-person-prompt')).not.toBeInTheDocument();
    });
    expect(setItemSpy).toHaveBeenCalledWith(SAME_PERSON_PROMPT_SESSION_KEY, '1');
  });

  it('rejects through the cannot-link route on No', async () => {
    const user = userEvent.setup();
    renderPrompt();
    await screen.findByRole('button', { name: 'No' });

    await user.click(screen.getByRole('button', { name: 'No' }));

    await waitFor(() => {
      expect(vi.mocked(rejectMergeSuggestion).mock.calls[0]?.[0]).toBe('merge-1');
    });
    expect(acceptMergeSuggestion).not.toHaveBeenCalled();
    await waitFor(() => {
      expect(screen.queryByTestId('acx-same-person-prompt')).not.toBeInTheDocument();
    });
    expect(setItemSpy).toHaveBeenCalledWith(SAME_PERSON_PROMPT_SESSION_KEY, '1');
  });

  it('skips without calling accept or reject and records the session flag', async () => {
    const user = userEvent.setup();
    renderPrompt();
    await screen.findByRole('button', { name: 'Skip' });

    await user.click(screen.getByRole('button', { name: 'Skip' }));

    expect(acceptMergeSuggestion).not.toHaveBeenCalled();
    expect(rejectMergeSuggestion).not.toHaveBeenCalled();
    expect(screen.queryByTestId('acx-same-person-prompt')).not.toBeInTheDocument();
    expect(setItemSpy).toHaveBeenCalledWith(SAME_PERSON_PROMPT_SESSION_KEY, '1');
  });

  it('does not show a prompt when the session flag is already set', async () => {
    getItemSpy.mockReturnValue('1');
    renderPrompt();

    await waitFor(() => {
      expect(getItemSpy).toHaveBeenCalled();
    });
    expect(screen.queryByTestId('acx-same-person-prompt')).not.toBeInTheDocument();
    expect(fetchPendingMergeSuggestions).not.toHaveBeenCalled();
    expect(acceptMergeSuggestion).not.toHaveBeenCalled();
  });
});

describe('RosterPage mounts SamePersonPrompt', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.spyOn(Storage.prototype, 'getItem').mockReturnValue(null);
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => undefined);
    stubPending([makeSuggestion()]);
    vi.mocked(useRecognitionCluster).mockReturnValue(
      createMockQuery<ClusterSummary, Error>({ data: undefined, isLoading: false, isError: false }),
    );
    vi.mocked(useRosterEntries).mockReturnValue(
      createMockQuery<RosterEntry[], Error>({
        data: [namedEntry(), namedEntry({ id: 8, person_uuid: 'person-uuid-bob', name: 'Bob' })],
        isLoading: false,
        isError: false,
        refetch: vi.fn(),
      }),
    );
    vi.mocked(useTopUnlabeledTotal).mockReturnValue(null);
    vi.mocked(useCreatePerson).mockReturnValue(createMockMutation({ mutate: vi.fn(), isPending: false }));
    vi.mocked(useUpdatePerson).mockReturnValue(createMockMutation({ mutate: vi.fn(), isPending: false }));
    vi.mocked(useDeletePerson).mockReturnValue(createMockMutation({ mutate: vi.fn(), isPending: false }));
    vi.mocked(useClusterMediaMap).mockReturnValue({});
    vi.mocked(useClusterDragDrop).mockReturnValue(dragDropState);
    vi.mocked(useClusterActions).mockReturnValue(clusterActionState);
  });

  afterEach(() => {
    void queryClient?.cancelQueries();
    queryClient?.clear();
    queryClient = null;
    cleanup();
    vi.restoreAllMocks();
  });

  it('places the non-modal prompt at the top of the roster panel', async () => {
    queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    render(
      <MemoryRouter initialEntries={['/']}>
        <QueryClientProvider client={queryClient}>
          <RosterPage />
        </QueryClientProvider>
      </MemoryRouter>,
    );

    const prompt = await screen.findByTestId('acx-same-person-prompt');
    const panel = document.querySelector('.acx-roster__panel');
    expect(panel?.firstElementChild).toBe(prompt);
    expect(prompt.getAttribute('role')).not.toBe('dialog');
    expect(screen.getByRole('heading', { name: 'Same or different person?' })).toBeInTheDocument();
    expect(acceptMergeSuggestion).not.toHaveBeenCalled();
  });
});
