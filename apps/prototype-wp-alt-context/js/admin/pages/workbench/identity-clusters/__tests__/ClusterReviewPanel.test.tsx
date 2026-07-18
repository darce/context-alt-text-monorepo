import React from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { fetchClusterMembers, removeClusterMember } from '../../../../api/recognition';
import { queryKeys } from '../../../../api/queryKeys';
import type { ClusterMembersResponse } from '../../../../api/recognition';
import { HTTPError } from '../../../../utils/http';
import { ClusterPanelProvider, useClusterPanel } from '../../ClusterPanelContext';
import { ClusterReviewPanel } from '../ClusterReviewPanel';
import { MergeSurvivorProvider, useMergeSurvivors } from '../MergeSurvivorContext';
import {
  LIVE_TARGET_CLOSE_ANNOUNCE,
  LIVE_TARGET_REBIND_ANNOUNCE,
} from '../useLiveReviewTarget';

const membersNotFound = (clusterId = 'x'): HTTPError =>
  new HTTPError({
    status: 404,
    retryAfterSeconds: undefined,
    endpoint: `/acx/v1/recognition/clusters/${clusterId}/members`,
    bodyPreview: 'cluster_not_found',
    message: 'cluster not found',
  });

const reactQueryState = vi.hoisted(() => ({
  useQueryOverride: null as Record<string, unknown> | null,
}));

vi.mock('@tanstack/react-query', async () => {
  const actual = await vi.importActual<typeof import('@tanstack/react-query')>('@tanstack/react-query');
  return {
    ...actual,
    useQuery: (options: unknown) => {
      const result = (actual as { useQuery: (arg: unknown) => unknown }).useQuery(options);
      if (!reactQueryState.useQueryOverride) {
        return result;
      }
      return { ...(result as object), ...reactQueryState.useQueryOverride };
    },
  };
});

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
  sprintf: (text: string, ...values: (string | number)[]) => {
    let index = 0;
    return text
      .replace(/%(\d+)\$[sd]/g, (_match, group: string) => String(values[Number(group) - 1] ?? ''))
      .replace(/%[sd]/g, () => String(values[index++] ?? ''));
  },
}));

vi.mock('../../../../api/recognition', async () => {
  const actual = await vi.importActual<typeof import('../../../../api/recognition')>('../../../../api/recognition');
  return {
    ...actual,
    fetchClusterMembers: vi.fn(),
    removeClusterMember: vi.fn(),
  };
});

const PanelProviders = ({ children }: { children: React.ReactNode }) => (
  <ClusterPanelProvider>
    <MergeSurvivorProvider>{children}</MergeSurvivorProvider>
  </ClusterPanelProvider>
);

const renderPanel = (
  clusterId = 'cluster-123',
  onClose: () => void = () => undefined,
  onFocusQueueRoot?: () => void,
) => {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
    },
  });

  const utils = render(
    <QueryClientProvider client={queryClient}>
      <PanelProviders>
        <ClusterReviewPanel
          clusterId={clusterId}
          onClose={onClose}
          onFocusQueueRoot={onFocusQueueRoot}
        />
      </PanelProviders>
    </QueryClientProvider>,
  );

  return { queryClient, ...utils };
};

/** Mirrors ScanTabContent ownership: panel keyed by clusterPanel.clusterId. */
const OwnedReviewHarness = ({
  initialClusterId,
  onFocusQueueRoot,
  seedSurvivor,
}: {
  initialClusterId: string;
  onFocusQueueRoot?: () => void;
  seedSurvivor?: { retiredId: string; survivorId: string };
}) => {
  const { clusterPanel, dispatchClusterPanel } = useClusterPanel();
  const { recordMergeSurvivor } = useMergeSurvivors();
  const seeded = React.useRef(false);

  React.useEffect(() => {
    if (!seeded.current) {
      seeded.current = true;
      if (seedSurvivor) {
        recordMergeSurvivor(seedSurvivor.retiredId, seedSurvivor.survivorId);
      }
      dispatchClusterPanel({ type: 'open_review', clusterId: initialClusterId });
    }
  }, [dispatchClusterPanel, initialClusterId, recordMergeSurvivor, seedSurvivor]);

  if (clusterPanel.mode !== 'review' || !clusterPanel.clusterId) {
    return <div data-testid="review-closed">closed</div>;
  }

  return (
    <ClusterReviewPanel
      key={clusterPanel.clusterId}
      clusterId={clusterPanel.clusterId}
      onClose={() => dispatchClusterPanel({ type: 'close' })}
      onFocusQueueRoot={onFocusQueueRoot}
    />
  );
};

const makeClusterMembersResponse = (members: ClusterMembersResponse['members'] = []): ClusterMembersResponse => ({
  members,
  limit: 500,
  total: members.length,
  truncated: false,
});

describe('ClusterReviewPanel', () => {
  afterEach(() => {
    reactQueryState.useQueryOverride = null;
    vi.resetAllMocks();
  });

  it('renders members from the cluster-members envelope', async () => {
    const fetchClusterMembersMock = vi.mocked(fetchClusterMembers);

    fetchClusterMembersMock.mockResolvedValue(
      makeClusterMembersResponse([
        {
          identity_id: 'identity-envelope-1',
          media_id: 11,
          similarity: 0.95,
          confidence: 0.99,
          bbox: { x: 0, y: 0, width: 10, height: 10 },
          thumb_url: 'http://example.test/thumb-envelope.jpg',
        },
      ]),
    );

    renderPanel('cluster-envelope');

    await waitFor(() => {
      expect(fetchClusterMembersMock).toHaveBeenCalledWith('cluster-envelope');
    });

    expect(screen.getByRole('img', { name: 'Cluster member' })).toHaveAttribute(
      'src',
      'http://example.test/thumb-envelope.jpg',
    );
    expect(screen.queryByText('No members found.')).not.toBeInTheDocument();
  });

  it('pages through show-all when the members envelope is truncated', async () => {
    const fetchClusterMembersMock = vi.mocked(fetchClusterMembers);
    const user = userEvent.setup();

    fetchClusterMembersMock.mockImplementation((_clusterId, params = {}) => {
      if ((params.offset ?? 0) === 0) {
        return Promise.resolve({
          members: [
            {
              identity_id: 'identity-1',
              media_id: 1,
              similarity: 0.95,
              confidence: 0.99,
              bbox: { x: 0, y: 0, width: 10, height: 10 },
              thumb_url: 'http://example.test/thumb-1.jpg',
            },
          ],
          limit: 1,
          total: 2,
          truncated: true,
        });
      }
      return Promise.resolve({
        members: [
          {
            identity_id: 'identity-2',
            media_id: 2,
            similarity: 0.9,
            confidence: 0.9,
            bbox: { x: 0, y: 0, width: 10, height: 10 },
            thumb_url: 'http://example.test/thumb-2.jpg',
          },
        ],
        limit: 1,
        total: 2,
        truncated: false,
      });
    });

    const { container } = renderPanel('cluster-truncated');

    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Show all (2)' })).toBeInTheDocument();
    });

    const showAll = screen.getByRole('button', { name: 'Show all (2)' });
    expect(showAll).toHaveAttribute('data-truncated', 'true');
    expect(showAll).toHaveAttribute('data-total', '2');

    await user.click(showAll);

    await waitFor(() => {
      expect(screen.getAllByRole('img', { name: 'Cluster member' })).toHaveLength(2);
    });
    expect(screen.queryByRole('button', { name: 'Show all (2)' })).not.toBeInTheDocument();
    expect(fetchClusterMembersMock).toHaveBeenCalledWith('cluster-truncated', {
      limit: 1,
      offset: 1,
    });

    // AT affordance: completion is announced and focus lands on the member
    // grid because the show-all button just unmounted.
    expect(screen.getByText('All 2 members shown')).toHaveAttribute('role', 'status');
    expect(container.querySelector('.acx-cluster-review-panel__grid')).toHaveFocus();
  });

  it('removes a cluster member and invalidates related queries', async () => {
    const fetchClusterMembersMock = vi.mocked(fetchClusterMembers);
    const removeClusterMemberMock = vi.mocked(removeClusterMember);
    const clusterId = 'cluster-123';

    fetchClusterMembersMock.mockResolvedValue(
      makeClusterMembersResponse([
        {
          identity_id: 'identity-1',
          media_id: 1,
          similarity: 0.95,
          confidence: 0.99,
          bbox: { x: 0, y: 0, width: 10, height: 10 },
          thumb_url: 'http://example.test/thumb.jpg',
        },
      ]),
    );
    removeClusterMemberMock.mockResolvedValue(undefined);

    const { queryClient } = renderPanel(clusterId);
    const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries');

    await waitFor(() => {
      expect(fetchClusterMembersMock).toHaveBeenCalledWith(clusterId);
    });

    expect(screen.getByRole('img', { name: 'Cluster member' })).toHaveClass('acx-cluster-member-card__image');

    const user = userEvent.setup();
    await user.click(screen.getByLabelText('Remove from cluster'));
    await user.click(screen.getByRole('button', { name: 'Remove member' }));

    await waitFor(() => {
      expect(removeClusterMemberMock).toHaveBeenCalledWith('identity-1', true);
    });

    await waitFor(() => {
      expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: queryKeys.clusters.memberList(clusterId) });
      expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: queryKeys.clusters.all });
      expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: queryKeys.suggestions.projection.all });
    });
  });

  it('renders cropped face fallback when thumbnail URL is missing', async () => {
    const fetchClusterMembersMock = vi.mocked(fetchClusterMembers);

    fetchClusterMembersMock.mockResolvedValue(
      makeClusterMembersResponse([
        {
          identity_id: 'identity-2',
          media_id: 2,
          similarity: 0.91,
          confidence: 0.98,
          bbox: { x: 12, y: 24, width: 48, height: 48 },
          thumb_url: null,
          media_url: 'http://example.test/media/member-2.jpg',
        },
      ]),
    );

    renderPanel('cluster-456');

    await waitFor(() => {
      expect(fetchClusterMembersMock).toHaveBeenCalledWith('cluster-456');
    });

    expect(screen.getByRole('img', { name: 'Cluster member' })).toHaveAttribute(
      'src',
      'http://example.test/media/member-2.jpg',
    );
    expect(screen.getByRole('img', { name: 'Cluster member' })).not.toHaveClass('acx-cluster-member-card__image');
  });

  it('prefers a face crop over a generic media thumbnail when bbox data is available', async () => {
    const fetchClusterMembersMock = vi.mocked(fetchClusterMembers);

    fetchClusterMembersMock.mockResolvedValue(
      makeClusterMembersResponse([
        {
          identity_id: 'identity-2b',
          media_id: 22,
          similarity: 0.9,
          confidence: 0.97,
          bbox: { x: 8, y: 12, width: 44, height: 44 },
          thumb_url: 'http://example.test/uploads/member-2b.jpg',
          media_url: 'http://example.test/media/member-2b.jpg',
        },
      ]),
    );

    const { container } = renderPanel('cluster-456b');

    await waitFor(() => {
      expect(fetchClusterMembersMock).toHaveBeenCalledWith('cluster-456b');
    });

    expect(container.querySelector('.acx-face-thumbnail')).not.toBeNull();
    expect(screen.getByRole('img', { name: 'Cluster member' })).toHaveAttribute(
      'src',
      'http://example.test/media/member-2b.jpg',
    );
    expect(container.querySelector('.acx-cluster-member-card__image')).toBeNull();
  });

  it('shows loading state while fetching members', () => {
    const fetchClusterMembersMock = vi.mocked(fetchClusterMembers);
    fetchClusterMembersMock.mockReturnValue(new Promise(() => undefined));

    renderPanel('cluster-loading');

    expect(screen.getByText('Loading members...')).toBeInTheDocument();
  });

  it('shows error message when members cannot be loaded', () => {
    const fetchClusterMembersMock = vi.mocked(fetchClusterMembers);
    fetchClusterMembersMock.mockResolvedValue(makeClusterMembersResponse());
    reactQueryState.useQueryOverride = {
      data: undefined,
      isLoading: false,
      isError: true,
    };

    renderPanel('cluster-error');

    expect(screen.getByText('Unable to load cluster members.')).toBeInTheDocument();
  });

  it('does not remove member when user cancels confirmation dialog', async () => {
    const fetchClusterMembersMock = vi.mocked(fetchClusterMembers);
    const removeClusterMemberMock = vi.mocked(removeClusterMember);
    fetchClusterMembersMock.mockResolvedValue(
      makeClusterMembersResponse([
        {
          identity_id: 'identity-3',
          media_id: 3,
          similarity: 0.88,
          confidence: 0.92,
          bbox: { x: 2, y: 2, width: 20, height: 20 },
          thumb_url: 'http://example.test/thumb-3.jpg',
        },
      ]),
    );

    renderPanel('cluster-cancel');
    const user = userEvent.setup();

    await waitFor(() => {
      expect(fetchClusterMembersMock).toHaveBeenCalledWith('cluster-cancel');
    });

    await user.click(screen.getByLabelText('Remove from cluster'));
    await user.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(removeClusterMemberMock).not.toHaveBeenCalled();
  });

  it('calls onClose when close button is clicked', async () => {
    const fetchClusterMembersMock = vi.mocked(fetchClusterMembers);
    const onClose = vi.fn();
    fetchClusterMembersMock.mockResolvedValue(makeClusterMembersResponse());

    renderPanel('cluster-close', onClose);
    const user = userEvent.setup();

    await user.click(screen.getByLabelText('Close'));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  /**
   * Flipped characterization (E21-5 Slice 7 / FBT-1 ⑤): members 404 is retirement.
   * No recorded survivor → branch (A) close + announce + focus queue root.
   */
  it('retire-no-survivor: members 404 closes panel, announces, and focuses queue root', async () => {
    const fetchClusterMembersMock = vi.mocked(fetchClusterMembers);
    const onClose = vi.fn();
    const onFocusQueueRoot = vi.fn();
    fetchClusterMembersMock.mockRejectedValue(membersNotFound('cluster-retired-x'));

    renderPanel('cluster-retired-x', onClose, onFocusQueueRoot);

    await waitFor(() => {
      expect(onClose).toHaveBeenCalledTimes(1);
    });
    expect(onFocusQueueRoot).toHaveBeenCalledTimes(1);
    expect(screen.getByRole('status')).toHaveTextContent(LIVE_TARGET_CLOSE_ANNOUNCE);
    // Criterion 4: no member faces painted for the retired cluster.
    expect(screen.queryByRole('img', { name: 'Cluster member' })).not.toBeInTheDocument();
  });

  it('retire-while-open with recorded survivor rebinds panel to survivor and announces', async () => {
    const fetchClusterMembersMock = vi.mocked(fetchClusterMembers);
    fetchClusterMembersMock.mockImplementation((clusterId) => {
      if (clusterId === 'cluster-retired') {
        return Promise.reject(membersNotFound(clusterId));
      }
      return Promise.resolve(
        makeClusterMembersResponse([
          {
            identity_id: 'surv-1',
            media_id: 9,
            similarity: 0.9,
            confidence: 0.9,
            bbox: { x: 0, y: 0, width: 10, height: 10 },
            thumb_url: 'http://example.test/survivor.jpg',
          },
        ]),
      );
    });

    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });

    render(
      <QueryClientProvider client={queryClient}>
        <PanelProviders>
          <OwnedReviewHarness
            initialClusterId="cluster-retired"
            seedSurvivor={{ retiredId: 'cluster-retired', survivorId: 'cluster-survivor' }}
          />
        </PanelProviders>
      </QueryClientProvider>,
    );

    await waitFor(() => {
      expect(screen.getByRole('status')).toHaveTextContent(LIVE_TARGET_REBIND_ANNOUNCE);
    });
    // Remounted on survivor — live membership of the survivor, never the retired id.
    await waitFor(() => {
      expect(screen.getByRole('img', { name: 'Cluster member' })).toHaveAttribute(
        'src',
        'http://example.test/survivor.jpg',
      );
    });
    expect(fetchClusterMembersMock).toHaveBeenCalledWith('cluster-survivor');
  });

  it('wrong-survivor-guess self-heals: rebind then close when survivor also 404s', async () => {
    const fetchClusterMembersMock = vi.mocked(fetchClusterMembers);
    fetchClusterMembersMock.mockImplementation((clusterId) => Promise.reject(membersNotFound(clusterId)));

    const onFocusQueueRoot = vi.fn();
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });

    render(
      <QueryClientProvider client={queryClient}>
        <PanelProviders>
          <OwnedReviewHarness
            initialClusterId="cluster-retired"
            seedSurvivor={{ retiredId: 'cluster-retired', survivorId: 'cluster-wrong' }}
            onFocusQueueRoot={onFocusQueueRoot}
          />
        </PanelProviders>
      </QueryClientProvider>,
    );

    await waitFor(() => {
      expect(screen.getByTestId('review-closed')).toBeInTheDocument();
    });
    expect(onFocusQueueRoot).toHaveBeenCalled();
  });

  it('FBT-1 criterion 4: open pane never shows retired membership after merge 404', async () => {
    const fetchClusterMembersMock = vi.mocked(fetchClusterMembers);
    // First paint members, then retirement 404 on existence/refetch paths.
    let call = 0;
    fetchClusterMembersMock.mockImplementation(() => {
      call += 1;
      if (call <= 2) {
        // First page + live-target probe for initial open.
        return Promise.resolve(
          makeClusterMembersResponse([
            {
              identity_id: 'stale-face',
              media_id: 1,
              similarity: 0.9,
              confidence: 0.9,
              bbox: { x: 0, y: 0, width: 10, height: 10 },
              thumb_url: 'http://example.test/stale.jpg',
            },
          ]),
        );
      }
      return Promise.reject(membersNotFound('cluster-stale'));
    });

    const onClose = vi.fn();
    const { queryClient } = renderPanel('cluster-stale', onClose);

    await waitFor(() => {
      expect(screen.getByRole('img', { name: 'Cluster member' })).toBeInTheDocument();
    });

    // Simulate post-merge invalidation → members queries re-run as 404.
    await queryClient.invalidateQueries({ queryKey: queryKeys.clusters.memberList('cluster-stale') });

    await waitFor(() => {
      expect(onClose).toHaveBeenCalled();
    });
    expect(screen.queryByRole('img', { name: 'Cluster member' })).not.toBeInTheDocument();
    expect(screen.queryByText('stale')).not.toBeInTheDocument();
  });
});
