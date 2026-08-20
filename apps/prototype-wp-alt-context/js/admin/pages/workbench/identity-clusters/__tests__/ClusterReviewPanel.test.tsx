import React from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { fetchClusterMembers, removeClusterMember } from '../../../../api/recognition';
import { queryKeys } from '../../../../api/queryKeys';
import type { ClusterMembersResponse } from '../../../../api/recognition';
import { HTTPError } from '../../../../utils/http';
import { ClusterPanelProvider, useClusterPanel } from '../../ClusterPanelContext';
import { ClusterReviewPanel } from '../ClusterReviewPanel';
import { MergeSurvivorProvider, useMergeSurvivors } from '../MergeSurvivorContext';
import { useAriaAnnounce } from '../useAriaAnnounce';
import { LIVE_TARGET_CLOSE_ANNOUNCE, LIVE_TARGET_REBIND_ANNOUNCE } from '../useLiveReviewTarget';
import { useOpenReviewTargetLifecycle } from '../useOpenReviewTargetLifecycle';

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
  _n: (single: string, plural: string, count: number) => (count === 1 ? single : plural),
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
  <MemoryRouter>
    <ClusterPanelProvider>
      <MergeSurvivorProvider>{children}</MergeSurvivorProvider>
    </ClusterPanelProvider>
  </MemoryRouter>
);

/** Always-mounted owner (mirrors ScanTabContent): opens the review via the panel
 * reducer, runs the retirement lifecycle through the PRODUCTION owner wiring
 * (`useOpenReviewTargetLifecycle`), owns the persistent seq-keyed `role=status`
 * live region (survives rebind remount / retirement unmount), and mounts the
 * panel on the returned `reviewClusterId` (null once retired). Retirement close
 * routes to the provided spies. BR-65: all panel tests now go through the real
 * owner path — no ABANDONED effect-callback `useLiveReviewTarget` wiring. */
const OwnedPanel = ({
  clusterId,
  onClose,
  onFocusQueueRoot,
}: {
  clusterId: string;
  onClose: () => void;
  onFocusQueueRoot?: () => void;
}) => {
  const { clusterPanel, dispatchClusterPanel } = useClusterPanel();
  const { message, seq, announce } = useAriaAnnounce();
  const opened = React.useRef(false);

  const { reviewClusterId } = useOpenReviewTargetLifecycle({
    requestedClusterId: clusterPanel.mode === 'review' ? clusterPanel.clusterId : null,
    onAnnounce: announce,
    onFocusQueueRoot,
    onRetireClose: () => {
      dispatchClusterPanel({ type: 'close' });
      onClose();
    },
    onRebindSync: (survivorId) => dispatchClusterPanel({ type: 'open_review', clusterId: survivorId }),
  });

  React.useEffect(() => {
    if (!opened.current) {
      opened.current = true;
      dispatchClusterPanel({ type: 'open_review', clusterId });
    }
  }, [dispatchClusterPanel, clusterId]);

  return (
    <>
      <p key={seq} role="status" aria-live="polite">
        {message}
      </p>
      {reviewClusterId !== null ? (
        <ClusterReviewPanel
          key={reviewClusterId}
          clusterId={reviewClusterId}
          onClose={() => {
            dispatchClusterPanel({ type: 'close' });
            onClose();
          }}
        />
      ) : null}
    </>
  );
};

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
        <OwnedPanel clusterId={clusterId} onClose={onClose} onFocusQueueRoot={onFocusQueueRoot} />
      </PanelProviders>
    </QueryClientProvider>,
  );

  return { queryClient, ...utils };
};

/** Mirrors ScanTabContent ownership: the always-mounted owner opens the review
 * via the panel reducer (user action), runs the retirement lifecycle through the
 * shared owner wiring, and mounts the panel on the returned `reviewClusterId`
 * (the rebound survivor, or null once retired). */
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
  const { message, seq, announce } = useAriaAnnounce();
  const seeded = React.useRef(false);

  const { reviewClusterId } = useOpenReviewTargetLifecycle({
    requestedClusterId: clusterPanel.mode === 'review' ? clusterPanel.clusterId : null,
    onAnnounce: announce,
    onFocusQueueRoot,
    onRetireClose: () => dispatchClusterPanel({ type: 'close' }),
    // BR-66: mirror ScanTabContent — advance the reducer to the survivor on rebind.
    onRebindSync: (survivorId) => dispatchClusterPanel({ type: 'open_review', clusterId: survivorId }),
  });

  React.useEffect(() => {
    if (!seeded.current) {
      seeded.current = true;
      if (seedSurvivor) {
        recordMergeSurvivor(seedSurvivor.retiredId, seedSurvivor.survivorId);
      }
      dispatchClusterPanel({ type: 'open_review', clusterId: initialClusterId });
    }
  }, [dispatchClusterPanel, initialClusterId, recordMergeSurvivor, seedSurvivor]);

  return (
    <>
      <p key={seq} role="status" aria-live="polite">
        {message}
      </p>
      {/* BR-66: observable mirror of the panel reducer's current review id. */}
      <span data-testid="reducer-cluster-id">{clusterPanel.clusterId ?? 'none'}</span>
      {reviewClusterId === null ? (
        <div data-testid="review-closed">closed</div>
      ) : (
        <ClusterReviewPanel
          key={reviewClusterId}
          clusterId={reviewClusterId}
          onClose={() => dispatchClusterPanel({ type: 'close' })}
        />
      )}
    </>
  );
};

/** BR-68: drives sequential retirements through the production owner path. Two
 * consecutive identical close announcements must each force a fresh live-region
 * render (seq bump) so a screen reader re-reads the repeated copy instead of an
 * Object.is state bail-out swallowing the second. */
const SequentialRetireHarness = ({ ids }: { ids: readonly string[] }) => {
  const { clusterPanel, dispatchClusterPanel } = useClusterPanel();
  const { message, seq, announce } = useAriaAnnounce();

  const { reviewClusterId } = useOpenReviewTargetLifecycle({
    requestedClusterId: clusterPanel.mode === 'review' ? clusterPanel.clusterId : null,
    onAnnounce: announce,
    onRetireClose: () => dispatchClusterPanel({ type: 'close' }),
  });

  return (
    <>
      <p key={seq} role="status" aria-live="polite" data-announce-seq={seq}>
        {message}
      </p>
      {ids.map((id) => (
        <button
          key={id}
          type="button"
          onClick={() => dispatchClusterPanel({ type: 'open_review', clusterId: id })}
        >
          {`open ${id}`}
        </button>
      ))}
      {reviewClusterId !== null ? (
        <ClusterReviewPanel
          key={reviewClusterId}
          clusterId={reviewClusterId}
          onClose={() => dispatchClusterPanel({ type: 'close' })}
        />
      ) : null}
    </>
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

  it('headline uses plain language: Review these faces (UXW2-3 / NAV-13)', async () => {
    vi.mocked(fetchClusterMembers).mockResolvedValue(makeClusterMembersResponse());

    renderPanel();

    expect(
      await screen.findByRole('heading', { level: 2, name: 'Review these faces' }),
    ).toBeInTheDocument();
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

    expect(screen.getByRole('img', { name: /Face on media/ })).toHaveAttribute(
      'src',
      'http://example.test/thumb-envelope.jpg',
    );
    expect(screen.queryByText('No faces in this group.')).not.toBeInTheDocument();
  });

  // UI-05: members error must offer retry that re-invokes the members query.
  it('UI-05: members error Retry re-invokes fetchClusterMembers', async () => {
    const fetchMock = vi.mocked(fetchClusterMembers);
    fetchMock.mockRejectedValue(new Error('acx_projection_query_failed'));

    renderPanel('cluster-members-error');

    const error = await screen.findByTestId('acx-cluster-members-error');
    expect(error).toHaveTextContent('Unable to load faces.');
    const callsBefore = fetchMock.mock.calls.length;

    await userEvent.click(within(error).getByRole('button', { name: 'Retry' }));

    await waitFor(() => {
      expect(fetchMock.mock.calls.length).toBeGreaterThan(callsBefore);
    });
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
      expect(screen.getAllByRole('img', { name: /Face on media/ })).toHaveLength(2);
    });
    expect(screen.queryByRole('button', { name: 'Show all (2)' })).not.toBeInTheDocument();
    expect(fetchClusterMembersMock).toHaveBeenCalledWith('cluster-truncated', {
      limit: 1,
      offset: 1,
    });

    // AT affordance: completion is announced and focus lands on the member
    // grid because the show-all button just unmounted.
    expect(screen.getByText('All 2 faces shown')).toHaveAttribute('role', 'status');
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

    expect(screen.getByRole('img', { name: /Face on media/ }).closest('.acx-cluster-member-card__image')).toBeTruthy();

    const user = userEvent.setup();
    await user.click(screen.getByLabelText('Remove this face from the face group'));
    await user.click(screen.getByRole('button', { name: 'Remove face' }));

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

    expect(screen.getByRole('img', { name: /Face on media/ })).toHaveAttribute(
      'src',
      'http://example.test/media/member-2.jpg',
    );
    expect(screen.getByRole('img', { name: /Face on media/ })).not.toHaveClass('acx-cluster-member-card__image');
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
    expect(screen.getByRole('img', { name: /Face on media/ })).toHaveAttribute(
      'src',
      'http://example.test/media/member-2b.jpg',
    );
    expect(container.querySelector('.acx-cluster-member-card__image')).not.toBeNull();
  });

  // E21-16 W3: zero-extent bbox must not enter FaceThumbnail.
  it('does not render FaceThumbnail for a zero-extent bbox', async () => {
    const fetchClusterMembersMock = vi.mocked(fetchClusterMembers);

    fetchClusterMembersMock.mockResolvedValue(
      makeClusterMembersResponse([
        {
          identity_id: 'identity-zero-bbox',
          media_id: 30,
          similarity: 0.9,
          confidence: 0.95,
          bbox: { x: 0, y: 0, width: 0, height: 0 },
          thumb_url: null,
          media_url: 'http://example.test/media/member-zero.jpg',
        },
      ]),
    );

    const { container } = renderPanel('cluster-zero-bbox');

    await waitFor(() => {
      expect(fetchClusterMembersMock).toHaveBeenCalledWith('cluster-zero-bbox');
    });

    expect(container.querySelector('.acx-face-thumbnail')).toBeNull();
    const image = screen.getByRole('img', { name: /Face on media/ });
    expect(image).toHaveAttribute('src', 'http://example.test/media/member-zero.jpg');
    expect(image).toHaveClass('acx-durable-face-thumb__uncropped');
    expect(screen.queryByText('No image')).not.toBeInTheDocument();
  });

  it('renders FaceThumbnail for a positive-extent bbox when no dedicated thumb exists', async () => {
    const fetchClusterMembersMock = vi.mocked(fetchClusterMembers);

    fetchClusterMembersMock.mockResolvedValue(
      makeClusterMembersResponse([
        {
          identity_id: 'identity-positive-bbox',
          media_id: 31,
          similarity: 0.9,
          confidence: 0.95,
          bbox: { x: 4, y: 6, width: 40, height: 48 },
          thumb_url: null,
          media_url: 'http://example.test/media/member-positive.jpg',
        },
      ]),
    );

    const { container } = renderPanel('cluster-positive-bbox');

    await waitFor(() => {
      expect(fetchClusterMembersMock).toHaveBeenCalledWith('cluster-positive-bbox');
    });

    expect(container.querySelector('.acx-face-thumbnail')).not.toBeNull();
    expect(screen.getByRole('img', { name: /Face on media/ })).toHaveAttribute(
      'src',
      'http://example.test/media/member-positive.jpg',
    );
  });

  // E21-16 W4: silent acx-placeholder must become a labelled unavailable state.
  it('renders a visible unavailable state when the member has no usable image', async () => {
    const fetchClusterMembersMock = vi.mocked(fetchClusterMembers);

    fetchClusterMembersMock.mockResolvedValue(
      makeClusterMembersResponse([
        {
          identity_id: 'identity-no-image',
          media_id: 32,
          similarity: 0.8,
          confidence: 0.9,
          bbox: null,
          thumb_url: null,
          media_url: null,
        },
      ]),
    );

    const { container } = renderPanel('cluster-no-image');

    await waitFor(() => {
      expect(fetchClusterMembersMock).toHaveBeenCalledWith('cluster-no-image');
    });

    expect(screen.getByText('No image')).toBeInTheDocument();
    expect(screen.getByRole('img', { name: /Face on media \d+ — image unavailable/ })).toBeInTheDocument();
    expect(container.querySelector('.acx-placeholder:empty')).toBeNull();
  });

  it('shows loading state while fetching members', () => {
    const fetchClusterMembersMock = vi.mocked(fetchClusterMembers);
    fetchClusterMembersMock.mockReturnValue(new Promise(() => undefined));

    renderPanel('cluster-loading');

    expect(screen.getByText('Loading faces…')).toBeInTheDocument();
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

    expect(screen.getByText('Unable to load faces.')).toBeInTheDocument();
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

    await user.click(screen.getByLabelText('Remove this face from the face group'));
    await user.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(removeClusterMemberMock).not.toHaveBeenCalled();
  });

  it('calls onClose when Back is clicked (single exit)', async () => {
    const fetchClusterMembersMock = vi.mocked(fetchClusterMembers);
    const onClose = vi.fn();
    fetchClusterMembersMock.mockResolvedValue(makeClusterMembersResponse());

    renderPanel('cluster-close', onClose);
    const user = userEvent.setup();

    await user.click(screen.getByRole('button', { name: '← Back to Review Suggestions' }));
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
    expect(screen.queryByRole('img', { name: /Face on media/ })).not.toBeInTheDocument();
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

    // Persistent owner-owned live region announces the rebind (survives the
    // panel remount). Target the text: the remounted survivor panel also renders
    // its own (empty) show-all role=status region.
    await waitFor(() => {
      expect(screen.getByText(LIVE_TARGET_REBIND_ANNOUNCE)).toHaveAttribute('role', 'status');
    });
    // Remounted on survivor — live membership of the survivor, never the retired id.
    await waitFor(() => {
      expect(screen.getByRole('img', { name: /Face on media/ })).toHaveAttribute(
        'src',
        'http://example.test/survivor.jpg',
      );
    });
    expect(fetchClusterMembersMock).toHaveBeenCalledWith('cluster-survivor');
  });

  it('BR-66: rebind syncs the panel reducer to the survivor id', async () => {
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

    // The reducer advances from the retired id to the survivor (canonical sync),
    // so it agrees with the mounted review target instead of stranding the
    // retired id. No requestedRef loop: survivor === openTarget on the next render.
    await waitFor(() => {
      expect(screen.getByTestId('reducer-cluster-id')).toHaveTextContent('cluster-survivor');
    });
    await waitFor(() => {
      expect(screen.getByRole('img', { name: /Face on media/ })).toHaveAttribute(
        'src',
        'http://example.test/survivor.jpg',
      );
    });
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
      expect(screen.getByRole('img', { name: /Face on media/ })).toBeInTheDocument();
    });

    // Simulate post-merge invalidation → members queries re-run as 404.
    await queryClient.invalidateQueries({ queryKey: queryKeys.clusters.memberList('cluster-stale') });

    await waitFor(() => {
      expect(onClose).toHaveBeenCalled();
    });
    expect(screen.queryByRole('img', { name: /Face on media/ })).not.toBeInTheDocument();
    // BR-71: the stale member's thumbnail is gone (can fail if a retired face
    // lingers — unlike the old `queryByText('stale')`, which never matched the
    // src-only URL and so could never fail).
    expect(document.querySelector('img[src="http://example.test/stale.jpg"]')).toBeNull();
  });

  it('BR-68: two sequential retirement closes both re-announce the identical copy', async () => {
    const fetchClusterMembersMock = vi.mocked(fetchClusterMembers);
    fetchClusterMembersMock.mockRejectedValue(membersNotFound());
    const user = userEvent.setup();

    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });

    render(
      <QueryClientProvider client={queryClient}>
        <PanelProviders>
          <SequentialRetireHarness ids={['cluster-a', 'cluster-b']} />
        </PanelProviders>
      </QueryClientProvider>,
    );

    await user.click(screen.getByRole('button', { name: 'open cluster-a' }));
    await waitFor(() => {
      expect(screen.getByRole('status')).toHaveTextContent(LIVE_TARGET_CLOSE_ANNOUNCE);
    });
    const firstSeq = screen.getByRole('status').getAttribute('data-announce-seq');
    expect(firstSeq).not.toBeNull();

    await user.click(screen.getByRole('button', { name: 'open cluster-b' }));
    // Identical copy, fresh render: the live region re-keyed (seq advanced), so
    // the repeated announcement is not swallowed by an Object.is bail-out.
    await waitFor(() => {
      expect(screen.getByRole('status').getAttribute('data-announce-seq')).not.toBe(firstSeq);
    });
    expect(screen.getByRole('status')).toHaveTextContent(LIVE_TARGET_CLOSE_ANNOUNCE);
  });

  /**
   * E215-BR-01: record-after-404 must rebind in the LIFECYCLE consumer.
   * The lifecycle latches exactly-once and nulls openTarget on retire; a survivor
   * recorded after that close must still rebind (S5-02 alone is unreachable here).
   */
  it('E215-BR-01: lifecycle record-after-404 rebinds after retire-close latch', async () => {
    const fetchClusterMembersMock = vi.mocked(fetchClusterMembers);
    fetchClusterMembersMock.mockImplementation((clusterId) => {
      if (clusterId === 'cluster-late-retired') {
        return Promise.reject(membersNotFound(clusterId));
      }
      return Promise.resolve(
        makeClusterMembersResponse([
          {
            identity_id: 'surv-late',
            media_id: 9,
            similarity: 0.9,
            confidence: 0.9,
            bbox: { x: 0, y: 0, width: 10, height: 10 },
            thumb_url: 'http://example.test/late-survivor.jpg',
          },
        ]),
      );
    });

    const LateRecordHarness = () => {
      const { clusterPanel, dispatchClusterPanel } = useClusterPanel();
      const { recordMergeSurvivor } = useMergeSurvivors();
      const { message, seq, announce } = useAriaAnnounce();
      const opened = React.useRef(false);

      const { reviewClusterId } = useOpenReviewTargetLifecycle({
        requestedClusterId: clusterPanel.mode === 'review' ? clusterPanel.clusterId : null,
        onAnnounce: announce,
        onRetireClose: () => dispatchClusterPanel({ type: 'close' }),
        onRebindSync: (survivorId) => dispatchClusterPanel({ type: 'open_review', clusterId: survivorId }),
      });

      React.useEffect(() => {
        if (!opened.current) {
          opened.current = true;
          dispatchClusterPanel({ type: 'open_review', clusterId: 'cluster-late-retired' });
        }
      }, [dispatchClusterPanel]);

      return (
        <>
          <p key={seq} role="status" aria-live="polite">
            {message}
          </p>
          <button
            type="button"
            onClick={() => recordMergeSurvivor('cluster-late-retired', 'cluster-late-survivor')}
          >
            record survivor
          </button>
          <span data-testid="lifecycle-review-id">{reviewClusterId ?? 'none'}</span>
          {reviewClusterId === null ? (
            <div data-testid="review-closed">closed</div>
          ) : (
            <ClusterReviewPanel
              key={reviewClusterId}
              clusterId={reviewClusterId}
              onClose={() => dispatchClusterPanel({ type: 'close' })}
            />
          )}
        </>
      );
    };

    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const user = userEvent.setup();

    render(
      <QueryClientProvider client={queryClient}>
        <PanelProviders>
          <LateRecordHarness />
        </PanelProviders>
      </QueryClientProvider>,
    );

    // First: 404 with empty survivor map → retire close.
    await waitFor(() => {
      expect(screen.getByTestId('review-closed')).toBeInTheDocument();
    });
    expect(screen.getByRole('status')).toHaveTextContent(LIVE_TARGET_CLOSE_ANNOUNCE);
    expect(screen.getByTestId('lifecycle-review-id')).toHaveTextContent('none');

    // Then: survivor recorded after the latch — lifecycle must rebind.
    await user.click(screen.getByRole('button', { name: 'record survivor' }));

    await waitFor(() => {
      expect(screen.getByTestId('lifecycle-review-id')).toHaveTextContent('cluster-late-survivor');
    });
    await waitFor(() => {
      expect(screen.getByText(LIVE_TARGET_REBIND_ANNOUNCE)).toHaveAttribute('role', 'status');
    });
    await waitFor(() => {
      expect(screen.getByRole('img', { name: /Face on media/ })).toHaveAttribute(
        'src',
        'http://example.test/late-survivor.jpg',
      );
    });
  });
});
