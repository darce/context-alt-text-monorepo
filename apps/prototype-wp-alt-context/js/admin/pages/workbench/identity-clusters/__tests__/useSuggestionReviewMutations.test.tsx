/**
 * E21-5 Slice 2 — gated advance + undo hold concurrency tests.
 *
 * Named exit criteria: rapid double-action, unmount-during-window, post-window
 * failure re-surface, undo-cancel=0, commit=1, advance-only-on-success,
 * invalidation presence, hold/failure announce. BR-15..24 fix-round coverage.
 */

import type { ReactNode } from 'react';
import { QueryClient, QueryClientProvider, useQuery } from '@tanstack/react-query';
import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { queryKeys } from '../../../../api/queryKeys';
import { DATA_SOURCE } from '../../../../api/recognition/types';
import type {
  PendingMergeSuggestion,
  PendingMergeSuggestionsResponse,
  PendingNameSuggestion,
  PendingNameSuggestionsResponse,
  TopUnlabeledCluster,
  TopUnlabeledClustersResponse,
} from '../../../../api/recognition/types';
import type { AcceptedMergeSuggestion } from '../../../../api/recognition';
import * as recognitionApi from '../../../../api/recognition';
import * as rosterApi from '../../../../api/rosterApi';
import type { RosterClusterCommitResponse } from '../../../../api/rosterApi';

const rosterCommitFixture = (
  overrides: Partial<RosterClusterCommitResponse> = {},
): RosterClusterCommitResponse => ({
  cluster_id: 'cluster-1',
  person_id: 7,
  person_uuid: 'person-uuid-7',
  person_name: 'Alex',
  updated_at: '2026-01-01T00:00:00Z',
  ...overrides,
});
import { MergeSurvivorProvider, useMergeSurvivors } from '../MergeSurvivorContext';
import {
  SUGGESTION_PROJECTION_INVALIDATION_EVENTS,
  type SuggestionProjectionInvalidationEvent,
} from '../suggestionProjection';
import type { ProjectedSuggestion } from '../suggestionProjection';
import type { SuggestionReviewPage } from '../useSuggestionReviewQueries';
import {
  HOLD_STATUS_COPY,
  UNDO_HOLD_MS,
  useSuggestionReviewMutations,
} from '../useSuggestionReviewMutations';

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
}));

vi.mock('../../../../api/recognition', () => ({
  acceptSuggestion: vi.fn(),
  rejectSuggestion: vi.fn(),
  acceptMergeSuggestion: vi.fn(),
  rejectMergeSuggestion: vi.fn(),
  acceptNameSuggestion: vi.fn(),
  rejectNameSuggestion: vi.fn(),
  bulkAcceptSuggestions: vi.fn(),
}));

vi.mock('../../../../api/rosterApi', () => ({
  commitClusterToRosterEntry: vi.fn(),
  listRosterEntries: vi.fn().mockResolvedValue([]),
}));

const reviewPageKey = queryKeys.suggestions.projection.reviewPage(0);
const mergePendingKey = queryKeys.suggestions.mergePending();
const namePendingKey = queryKeys.suggestions.namePending();

const makeItem = (
  overrides: Partial<ProjectedSuggestion> & Pick<ProjectedSuggestion, 'suggestionId'>,
): ProjectedSuggestion => ({
  identityId: `identity-${overrides.suggestionId}`,
  clusterId: 'cluster-1',
  label: 'Alice',
  similarity: 0.9,
  ...overrides,
});

const makePage = (items: ProjectedSuggestion[]): SuggestionReviewPage => ({
  items,
  dataSource: DATA_SOURCE.LOCAL_PROJECTION,
});

const makeMerge = (id: string): PendingMergeSuggestion => ({
  id,
  cluster_a_id: 'a',
  cluster_b_id: 'b',
  similarity: 0.9,
  status: 'pending',
  cluster_a_label: 'Alice',
  cluster_b_label: 'Bob',
});

const makeAccepted = (
  id: string,
  overrides: Partial<AcceptedMergeSuggestion> = {},
): AcceptedMergeSuggestion => ({
  ...makeMerge(id),
  source_cluster_id: 'a',
  target_cluster_id: 'b',
  moved_identity_ids: [],
  ...overrides,
});

const makeMergePage = (suggestions: PendingMergeSuggestion[]): PendingMergeSuggestionsResponse => ({
  suggestions,
  limit: 10,
  offset: 0,
  data_source: DATA_SOURCE.LOCAL_PROJECTION,
});

const makeName = (id: string): PendingNameSuggestion => ({
  id,
  cluster_id: 'cluster-1',
  suggested_name: 'Alex',
  confidence_score: 0.9,
  source: 'test',
  created_at: '2026-01-01T00:00:00Z',
  expires_at: null,
});

const makeNamePage = (suggestions: PendingNameSuggestion[]): PendingNameSuggestionsResponse => ({
  suggestions,
  limit: 25,
  offset: 0,
  data_source: DATA_SOURCE.LOCAL_PROJECTION,
});

const makeTopCluster = (id: string): TopUnlabeledCluster => ({
  id,
  tenant_id: 'test-tenant',
  label: null,
  is_labeled: false,
  is_auto_label: true,
  identity_count: 2,
  user_confirmed: false,
  representatives: [],
});

const makeTopUnlabeledPage = (clusters: TopUnlabeledCluster[]): TopUnlabeledClustersResponse => ({
  clusters,
  limit: 20,
  total: clusters.length,
  truncated: false,
  data_source: DATA_SOURCE.LOCAL_PROJECTION,
});

const crossFamilyQueryKey = (target: string): readonly unknown[] => {
  switch (target) {
    case 'clusters.all':
      return queryKeys.clusters.all;
    case 'clusters.labels':
      return queryKeys.clusters.labels();
    case 'media.identities':
      return queryKeys.media.identities();
    case 'mergePending':
      return queryKeys.suggestions.mergePending();
    case 'namePending':
      return queryKeys.suggestions.namePending();
    default:
      throw new Error(`Unknown keptCrossFamilyTargets token: ${target}`);
  }
};

const expectCrossFamilyPresent = (
  spy: ReturnType<typeof vi.spyOn>,
  event: SuggestionProjectionInvalidationEvent,
): void => {
  for (const target of SUGGESTION_PROJECTION_INVALIDATION_EVENTS[event].keptCrossFamilyTargets) {
    expect(spy).toHaveBeenCalledWith(expect.objectContaining({ queryKey: crossFamilyQueryKey(target) }));
  }
};

/** Advance the hold timer and flush pending promise chains (TEST-08 deterministic). */
const expireHold = async (): Promise<void> => {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(UNDO_HOLD_MS);
    // Flush the timer's promise chain + any nested microtasks from the POST.
    await Promise.resolve();
    await Promise.resolve();
  });
};

describe('useSuggestionReviewMutations (Slice 2 hold/flush)', () => {
  let queryClient: QueryClient;
  let bulkActionRef: { current: boolean };

  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );

  const renderMutations = () =>
    renderHook(() => useSuggestionReviewMutations({ queryClient, bulkActionRef }), { wrapper });

  beforeEach(() => {
    vi.clearAllMocks();
    // mockImplementationOnce queues survive clearAllMocks — reset so prior tests
    // cannot leave a hanging once-impl that steals the next call.
    vi.mocked(recognitionApi.acceptSuggestion).mockReset();
    vi.mocked(recognitionApi.rejectSuggestion).mockReset();
    vi.mocked(recognitionApi.acceptMergeSuggestion).mockReset();
    vi.mocked(recognitionApi.rejectMergeSuggestion).mockReset();
    vi.mocked(recognitionApi.acceptNameSuggestion).mockReset();
    vi.mocked(recognitionApi.bulkAcceptSuggestions).mockReset();
    vi.mocked(recognitionApi.rejectNameSuggestion).mockReset();
    vi.useFakeTimers();
    bulkActionRef = { current: false };
    queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('exports a single pinned UNDO_HOLD_MS = 5000', () => {
    expect(UNDO_HOLD_MS).toBe(5000);
  });

  it('exports a single HOLD_STATUS_COPY for component + tests (BR-24)', () => {
    expect(HOLD_STATUS_COPY).toBe('Saving… — Undo');
  });

  it('undo-cancel: accept then Undo yields exactly 0 backend calls', async () => {
    vi.mocked(recognitionApi.acceptSuggestion).mockResolvedValue({
      suggestion_id: 'sugg-a',
      resolution: 'accepted',
      identity_id: 'identity-a',
      cluster_id: 'cluster-1',
      message: 'ok',
    });

    const { result } = renderMutations();

    let outcome: string | undefined;
    act(() => {
      void result.current.scheduleAccept('sugg-a').then((r) => {
        outcome = r.outcome;
      });
    });

    expect(result.current.hold.phase).toBe('holding');
    expect(recognitionApi.acceptSuggestion).not.toHaveBeenCalled();

    act(() => {
      result.current.undoHold();
    });
    // Flush the scheduleAccept promise .then microtask.
    await Promise.resolve();

    expect(outcome).toBe('undone');
    expect(recognitionApi.acceptSuggestion).toHaveBeenCalledTimes(0);
    expect(result.current.hold.phase).toBe('idle');
  });

  it('commit: hold window expiry fires exactly 1 POST and removes from cache only on success', async () => {
    const itemA = makeItem({ suggestionId: 'sugg-a', similarity: 0.95 });
    const itemB = makeItem({ suggestionId: 'sugg-b', similarity: 0.85, clusterId: 'cluster-2', label: 'Bob' });
    queryClient.setQueryData(reviewPageKey, makePage([itemA, itemB]));

    vi.mocked(recognitionApi.acceptSuggestion).mockResolvedValue({
      suggestion_id: 'sugg-a',
      resolution: 'accepted',
      identity_id: 'identity-a',
      cluster_id: 'cluster-1',
      message: 'ok',
    });

    const { result } = renderMutations();

    let outcome: string | undefined;
    act(() => {
      void result.current.scheduleAccept('sugg-a').then((r) => {
        outcome = r.outcome;
      });
    });

    // During hold: item still at head (no optimistic remove).
    expect(queryClient.getQueryData<SuggestionReviewPage>(reviewPageKey)?.items.map((i) => i.suggestionId)).toEqual([
      'sugg-a',
      'sugg-b',
    ]);
    expect(recognitionApi.acceptSuggestion).not.toHaveBeenCalled();

    await expireHold();

    expect(recognitionApi.acceptSuggestion).toHaveBeenCalledTimes(1);
    expect(recognitionApi.acceptSuggestion).toHaveBeenCalledWith('sugg-a');
    expect(outcome).toBe('committed');
    expect(queryClient.getQueryData<SuggestionReviewPage>(reviewPageKey)?.items.map((i) => i.suggestionId)).toEqual([
      'sugg-b',
    ]);
  });

  it('advance-only-on-success: rejected POST leaves item at queue head', async () => {
    const itemA = makeItem({ suggestionId: 'sugg-a' });
    queryClient.setQueryData(reviewPageKey, makePage([itemA]));

    vi.mocked(recognitionApi.acceptSuggestion).mockRejectedValue(new Error('network'));

    const { result } = renderMutations();

    let outcome: string | undefined;
    act(() => {
      void result.current.scheduleAccept('sugg-a').then((r) => {
        outcome = r.outcome;
      });
    });

    await expireHold();

    expect(outcome).toBe('failed');
    expect(queryClient.getQueryData<SuggestionReviewPage>(reviewPageKey)?.items.map((i) => i.suggestionId)).toEqual([
      'sugg-a',
    ]);
    expect(result.current.hold.phase).toBe('failed');
    expect(result.current.hold.errorMessage).toBeTruthy();
  });

  it('rapid double-action: accept A then immediately accept B flushes A before B hold; 2 POSTs order preserved', async () => {
    const order: string[] = [];
    let resolveA!: () => void;
    const aGate = new Promise<void>((resolve) => {
      resolveA = resolve;
    });

    vi.mocked(recognitionApi.acceptSuggestion).mockImplementation(async (id: string) => {
      order.push(`start:${id}`);
      if (id === 'sugg-a') {
        await aGate;
      }
      order.push(`end:${id}`);
      return {
        suggestion_id: id,
        resolution: 'accepted' as const,
        identity_id: `identity-${id}`,
        cluster_id: 'cluster-1',
        message: 'ok',
      };
    });

    const { result } = renderMutations();

    let outcomeA: string | undefined;
    let outcomeB: string | undefined;

    act(() => {
      void result.current.scheduleAccept('sugg-a').then((r) => {
        outcomeA = r.outcome;
      });
    });

    expect(result.current.hold.phase).toBe('holding');
    expect(result.current.hold.suggestionId).toBe('sugg-a');
    expect(recognitionApi.acceptSuggestion).not.toHaveBeenCalled();

    // Immediately schedule B — must flush A first and await its POST before B's window.
    await act(async () => {
      void result.current.scheduleAccept('sugg-b').then((r) => {
        outcomeB = r.outcome;
      });
      // Let the flush chain start.
      await Promise.resolve();
    });

    expect(recognitionApi.acceptSuggestion).toHaveBeenCalledTimes(1);
    expect(recognitionApi.acceptSuggestion).toHaveBeenCalledWith('sugg-a');
    // B's hold must not open until A resolves.
    expect(result.current.hold.phase).toBe('committing');
    expect(result.current.hold.suggestionId).toBe('sugg-a');

    await act(async () => {
      resolveA();
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(result.current.hold.phase).toBe('holding');
    expect(result.current.hold.suggestionId).toBe('sugg-b');
    expect(outcomeA).toBe('committed');
    expect(recognitionApi.acceptSuggestion).toHaveBeenCalledTimes(1);

    // Flush B's hold (timer path covered by the commit test); assert order + count.
    await act(async () => {
      await result.current.flushHeld();
    });

    expect(recognitionApi.acceptSuggestion).toHaveBeenCalledTimes(2);
    expect(outcomeB).toBe('committed');
    expect(order).toEqual(['start:sugg-a', 'end:sugg-a', 'start:sugg-b', 'end:sugg-b']);
    expect(vi.mocked(recognitionApi.acceptSuggestion).mock.calls.map((c) => c[0])).toEqual([
      'sugg-a',
      'sugg-b',
    ]);
  });

  it('unmount-during-window: unmount with held commit fires exactly 1 POST and no setState-after-unmount warning (BR-19/23)', async () => {
    const errorSpy = vi.spyOn(console, 'error').mockImplementation(() => undefined);
    vi.mocked(recognitionApi.acceptSuggestion).mockResolvedValue({
      suggestion_id: 'sugg-a',
      resolution: 'accepted',
      identity_id: 'identity-a',
      cluster_id: 'cluster-1',
      message: 'ok',
    });

    const { result, unmount } = renderMutations();

    act(() => {
      void result.current.scheduleAccept('sugg-a');
    });
    expect(result.current.hold.phase).toBe('holding');
    expect(recognitionApi.acceptSuggestion).not.toHaveBeenCalled();

    unmount();

    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
      // Ensure a late-armed timer would have fired if present.
      await vi.advanceTimersByTimeAsync(UNDO_HOLD_MS * 2);
      await Promise.resolve();
    });

    expect(recognitionApi.acceptSuggestion).toHaveBeenCalledTimes(1);
    expect(recognitionApi.acceptSuggestion).toHaveBeenCalledWith('sugg-a');
    const setStateWarnings = errorSpy.mock.calls.filter((args) =>
      args.some((arg) => typeof arg === 'string' && /unmounted|Can't perform a React state update/i.test(arg)),
    );
    expect(setStateWarnings).toHaveLength(0);
    errorSpy.mockRestore();
  });

  it('post-window failure re-surface: flushed POST rejects → failed phase + retry re-fires exactly 1 POST', async () => {
    vi.mocked(recognitionApi.acceptSuggestion)
      .mockRejectedValueOnce(new Error('boom'))
      .mockResolvedValueOnce({
        suggestion_id: 'sugg-a',
        resolution: 'accepted',
        identity_id: 'identity-a',
        cluster_id: 'cluster-1',
        message: 'ok',
      });

    const itemA = makeItem({ suggestionId: 'sugg-a' });
    queryClient.setQueryData(reviewPageKey, makePage([itemA]));

    const { result } = renderMutations();

    act(() => {
      void result.current.scheduleAccept('sugg-a');
    });

    await expireHold();

    expect(result.current.hold.phase).toBe('failed');
    expect(result.current.hold.suggestionId).toBe('sugg-a');
    // Item still at head.
    expect(queryClient.getQueryData<SuggestionReviewPage>(reviewPageKey)?.items).toHaveLength(1);
    expect(recognitionApi.acceptSuggestion).toHaveBeenCalledTimes(1);

    await act(async () => {
      const retry = result.current.retryFailure();
      expect(retry).not.toBeNull();
      await retry;
    });

    expect(recognitionApi.acceptSuggestion).toHaveBeenCalledTimes(2);
    expect(result.current.hold.phase).toBe('idle');
    expect(queryClient.getQueryData<SuggestionReviewPage>(reviewPageKey)?.items).toHaveLength(0);
  });

  it('S2-01: a different item cannot be scheduled while another item is failed; the failure surface is preserved and no POST fires', async () => {
    vi.mocked(recognitionApi.acceptSuggestion).mockRejectedValue(new Error('boom'));
    const itemA = makeItem({ suggestionId: 'sugg-a' });
    const itemB = makeItem({ suggestionId: 'sugg-b' });
    queryClient.setQueryData(reviewPageKey, makePage([itemA, itemB]));

    const { result } = renderMutations();

    act(() => {
      void result.current.scheduleAccept('sugg-a');
    });
    await expireHold();

    // Item A is now in the single failed slot.
    expect(result.current.hold.phase).toBe('failed');
    expect(result.current.hold.suggestionId).toBe('sugg-a');
    expect(recognitionApi.acceptSuggestion).toHaveBeenCalledTimes(1);

    // Acting on B must be refused — not silently swallow A's unresolved failure.
    let outcomeB: string | undefined;
    act(() => {
      void result.current.scheduleReject('sugg-b').then((r) => {
        outcomeB = r.outcome;
      });
    });
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(outcomeB).toBe('not_attempted_prior_failed');
    // A's failure surface is intact — NOT replaced by a B hold.
    expect(result.current.hold.phase).toBe('failed');
    expect(result.current.hold.suggestionId).toBe('sugg-a');
    // No accept/reject POST fired for B.
    expect(recognitionApi.acceptSuggestion).toHaveBeenCalledTimes(1);
    expect(recognitionApi.rejectSuggestion).not.toHaveBeenCalled();

    // Recovery: a successful retry of A clears the slot and unblocks other items.
    vi.mocked(recognitionApi.acceptSuggestion).mockResolvedValueOnce({
      suggestion_id: 'sugg-a',
      resolution: 'accepted',
      identity_id: 'identity-a',
      cluster_id: 'cluster-1',
      message: 'ok',
    });
    await act(async () => {
      await result.current.retryFailure();
    });
    expect(result.current.hold.phase).toBe('idle');

    let outcomeB2: string | undefined;
    act(() => {
      void result.current.scheduleReject('sugg-b').then((r) => {
        outcomeB2 = r.outcome;
      });
    });
    // B now opens its own hold (holding), no longer blocked.
    expect(result.current.hold.phase).toBe('holding');
    expect(result.current.hold.suggestionId).toBe('sugg-b');
    void outcomeB2;
  });

  it('S2-01 (bulk-safe): a bulk commitOneNow failure does not block single scheduling of other items', async () => {
    // Bulk path fails via updateUi:false — sets the internal failedHold latch but NOT the
    // visible hold surface (bulk owns its own partial-failure Retry). The S2-01 guard must
    // key off the visible hold.phase, so single scheduling of other items stays open.
    vi.mocked(recognitionApi.acceptSuggestion).mockRejectedValueOnce(new Error('bulk-boom'));

    const { result } = renderMutations();

    let bulkOutcome: string | undefined;
    await act(async () => {
      bulkOutcome = await result.current.commitOneNow('accept', 'sugg-bulk');
    });
    expect(bulkOutcome).toBe('failed');
    // Bulk failure leaves the single-item hold surface idle.
    expect(result.current.hold.phase).toBe('idle');

    // A different single item must still open its hold (not silently refused).
    act(() => {
      void result.current.scheduleAccept('sugg-other');
    });
    expect(result.current.hold.phase).toBe('holding');
    expect(result.current.hold.suggestionId).toBe('sugg-other');
  });

  it('S2-01: a person-commit is refused while a single-item accept/reject failure is unresolved', async () => {
    vi.mocked(recognitionApi.acceptSuggestion).mockRejectedValue(new Error('boom'));
    const itemA = makeItem({ suggestionId: 'sugg-a' });
    queryClient.setQueryData(reviewPageKey, makePage([itemA]));

    const { result } = renderMutations();

    act(() => {
      void result.current.scheduleAccept('sugg-a');
    });
    await expireHold();
    expect(result.current.hold.phase).toBe('failed');

    // Person-commit would otherwise invalidate the projection and drop the failed card,
    // stranding the failed slot. It must be refused until the failure is retried.
    let pcOutcome: string | undefined;
    await act(async () => {
      pcOutcome = (
        await result.current.schedulePersonCommit({ clusterId: 'cluster-1', newEntryName: 'X' })
      ).outcome;
    });

    expect(pcOutcome).toBe('not_attempted_prior_failed');
    expect(rosterApi.commitClusterToRosterEntry).not.toHaveBeenCalled();
    // Failed surface preserved.
    expect(result.current.hold.phase).toBe('failed');
    expect(result.current.hold.suggestionId).toBe('sugg-a');
  });

  it('BR-17: double-retry while first in flight yields exactly 1 POST', async () => {
    let resolvePost!: () => void;
    const gate = new Promise<void>((resolve) => {
      resolvePost = resolve;
    });
    vi.mocked(recognitionApi.acceptSuggestion)
      .mockRejectedValueOnce(new Error('boom'))
      .mockImplementationOnce(async () => {
        await gate;
        return {
          suggestion_id: 'sugg-a',
          resolution: 'accepted' as const,
          identity_id: 'identity-a',
          cluster_id: 'cluster-1',
          message: 'ok',
        };
      });

    const { result } = renderMutations();
    act(() => {
      void result.current.scheduleAccept('sugg-a');
    });
    await expireHold();
    expect(result.current.hold.phase).toBe('failed');

    let first: Promise<unknown> | null = null;
    let second: Promise<unknown> | null = null;
    act(() => {
      first = result.current.retryFailure();
      second = result.current.retryFailure();
    });

    expect(first).not.toBeNull();
    expect(second).toBeNull();
    expect(result.current.retryPending).toBe(true);

    await act(async () => {
      resolvePost();
      await first;
      await Promise.resolve();
    });

    expect(recognitionApi.acceptSuggestion).toHaveBeenCalledTimes(2); // fail + one retry
    expect(result.current.retryPending).toBe(false);
  });

  it('BR-17: retry then accept-same-item does not interleave POSTs', async () => {
    let resolveRetry!: () => void;
    const retryGate = new Promise<void>((resolve) => {
      resolveRetry = resolve;
    });
    const order: string[] = [];
    vi.mocked(recognitionApi.acceptSuggestion)
      .mockRejectedValueOnce(new Error('boom'))
      .mockImplementationOnce(async () => {
        order.push('retry-start');
        await retryGate;
        order.push('retry-end');
        return {
          suggestion_id: 'sugg-a',
          resolution: 'accepted' as const,
          identity_id: 'identity-a',
          cluster_id: 'cluster-1',
          message: 'ok',
        };
      })
      .mockImplementationOnce(() => {
        order.push('accept-same');
        return Promise.resolve({
          suggestion_id: 'sugg-a',
          resolution: 'accepted' as const,
          identity_id: 'identity-a',
          cluster_id: 'cluster-1',
          message: 'ok',
        });
      });

    const { result } = renderMutations();
    act(() => {
      void result.current.scheduleAccept('sugg-a');
    });
    await expireHold();

    let acceptOutcome: string | undefined;
    await act(async () => {
      void result.current.retryFailure();
      await Promise.resolve();
      // Same item while failed/retrying must not open a new hold path.
      void result.current.scheduleAccept('sugg-a').then((r) => {
        acceptOutcome = r.outcome;
      });
      await Promise.resolve();
    });

    expect(acceptOutcome).toBe('failed');
    expect(order).toEqual(['retry-start']);

    await act(async () => {
      resolveRetry();
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(order).toEqual(['retry-start', 'retry-end']);
    expect(recognitionApi.acceptSuggestion).toHaveBeenCalledTimes(2);
  });

  it('BR-21: dropped queued action resolves with own kind/id and not_attempted_prior_failed', async () => {
    vi.mocked(recognitionApi.acceptSuggestion).mockRejectedValue(new Error('prior fail'));

    const { result } = renderMutations();
    act(() => {
      void result.current.scheduleAccept('sugg-a');
    });

    let dropped: { outcome: string; kind: string; suggestionId: string } | undefined;
    await act(async () => {
      // Busy path flushes A (fails) → B resolves not_attempted_prior_failed.
      dropped = await result.current.scheduleReject('sugg-b');
    });

    expect(dropped).toEqual({
      outcome: 'not_attempted_prior_failed',
      kind: 'reject',
      suggestionId: 'sugg-b',
    });
    expect(recognitionApi.acceptSuggestion).toHaveBeenCalledTimes(1);
    expect(recognitionApi.rejectSuggestion).not.toHaveBeenCalled();
  });

  it('BR-22: undo then immediately re-accept same item gets a fresh full window', async () => {
    vi.mocked(recognitionApi.acceptSuggestion).mockResolvedValue({
      suggestion_id: 'sugg-a',
      resolution: 'accepted',
      identity_id: 'identity-a',
      cluster_id: 'cluster-1',
      message: 'ok',
    });

    const { result } = renderMutations();

    act(() => {
      void result.current.scheduleAccept('sugg-a');
    });
    // Advance partway through first hold.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(UNDO_HOLD_MS - 500);
    });
    expect(recognitionApi.acceptSuggestion).not.toHaveBeenCalled();

    act(() => {
      result.current.undoHold();
    });
    act(() => {
      void result.current.scheduleAccept('sugg-a');
    });
    expect(result.current.hold.phase).toBe('holding');

    // Old remaining 500ms must NOT fire the new hold.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
      await Promise.resolve();
    });
    expect(recognitionApi.acceptSuggestion).not.toHaveBeenCalled();

    // Full window for the new hold.
    await expireHold();
    expect(recognitionApi.acceptSuggestion).toHaveBeenCalledTimes(1);
  });

  it('BR-23: unmount while prepare queued does not arm a post-unmount timer commit', async () => {
    const errorSpy = vi.spyOn(console, 'error').mockImplementation(() => undefined);
    let resolveA!: () => void;
    const aGate = new Promise<void>((resolve) => {
      resolveA = resolve;
    });
    vi.mocked(recognitionApi.acceptSuggestion).mockImplementation(async (id: string) => {
      if (id === 'sugg-a') {
        await aGate;
      }
      return {
        suggestion_id: id,
        resolution: 'accepted' as const,
        identity_id: `identity-${id}`,
        cluster_id: 'cluster-1',
        message: 'ok',
      };
    });

    const { result, unmount } = renderMutations();
    act(() => {
      void result.current.scheduleAccept('sugg-a');
    });
    // Queue B while A holding → busy prepare waits on A flush.
    act(() => {
      void result.current.scheduleAccept('sugg-b');
    });
    // Unmount before A resolves — cleanup fires A; B must not open a hold timer.
    unmount();

    await act(async () => {
      resolveA();
      await Promise.resolve();
      await Promise.resolve();
      await vi.advanceTimersByTimeAsync(UNDO_HOLD_MS * 2);
      await Promise.resolve();
    });

    // Cleanup fire + no second timer-fired B commit.
    expect(vi.mocked(recognitionApi.acceptSuggestion).mock.calls.map((c) => c[0])).toEqual(['sugg-a']);
    const setStateWarnings = errorSpy.mock.calls.filter((args) =>
      args.some((arg) => typeof arg === 'string' && /unmounted|Can't perform a React state update/i.test(arg)),
    );
    expect(setStateWarnings).toHaveLength(0);
    errorSpy.mockRestore();
  });

  it('invalidation presence: accept path keeps suggestionAccept cross-family targets', async () => {
    const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries');
    vi.mocked(recognitionApi.acceptSuggestion).mockResolvedValue({
      suggestion_id: 'sugg-a',
      resolution: 'accepted',
      identity_id: 'identity-a',
      cluster_id: 'cluster-1',
      message: 'ok',
    });

    const { result } = renderMutations();

    act(() => {
      void result.current.scheduleAccept('sugg-a');
    });
    await expireHold();

    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: queryKeys.suggestions.projection.all });
    expectCrossFamilyPresent(invalidateSpy, 'suggestionAccept');
  });

  it('invalidation presence: reject path keeps suggestionReject cross-family targets', async () => {
    const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries');
    vi.mocked(recognitionApi.rejectSuggestion).mockResolvedValue({
      suggestion_id: 'sugg-a',
      resolution: 'rejected',
      identity_id: 'identity-a',
      cluster_id: null,
      message: 'ok',
    });

    const { result } = renderMutations();

    act(() => {
      void result.current.scheduleReject('sugg-a');
    });
    await expireHold();

    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: queryKeys.suggestions.projection.all });
    expectCrossFamilyPresent(invalidateSpy, 'suggestionReject');
  });

  it('BR-18/20: acceptMerge hold→success removes from cache + invalidates mergePending/media/clusters', async () => {
    // merge-2 references an unrelated cluster pair so this asserts targeted
    // removal of the accepted row, not collateral drop of a cluster sibling.
    queryClient.setQueryData(
      mergePendingKey,
      makeMergePage([
        makeMerge('merge-1'),
        { ...makeMerge('merge-2'), cluster_a_id: 'c', cluster_b_id: 'd' },
      ]),
    );
    const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries');
    vi.mocked(recognitionApi.acceptMergeSuggestion).mockResolvedValue(makeAccepted('merge-1'));

    const { result } = renderMutations();
    act(() => {
      void result.current.scheduleAcceptMerge('merge-1');
    });
    await expireHold();

    expect(recognitionApi.acceptMergeSuggestion).toHaveBeenCalledTimes(1);
    expect(
      queryClient.getQueryData<PendingMergeSuggestionsResponse>(mergePendingKey)?.suggestions.map((s) => s.id),
    ).toEqual(['merge-2']);
    expect(invalidateSpy).toHaveBeenCalledWith(expect.objectContaining({ queryKey: mergePendingKey }));
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: queryKeys.media.identities() });
    expect(invalidateSpy).toHaveBeenCalledWith(expect.objectContaining({ queryKey: queryKeys.clusters.all }));
    // Re-schedule same id is possible at hook level but item is gone from queue cache.
    expect(result.current.hold.phase).toBe('idle');
  });

  it('S5-03/GROK-01: acceptMerge records survivor from response ids, not client rank (user_confirmed flip)', async () => {
    // Larger unconfirmed A would win client identity_count rank; authoritative
    // accept response flips to smaller confirmed B as survivor.
    const largerUnconfirmed = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa';
    const smallerConfirmed = 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb';
    const acceptResponse: AcceptedMergeSuggestion = {
      id: 'merge-flip',
      cluster_a_id: largerUnconfirmed,
      cluster_b_id: smallerConfirmed,
      similarity: 0.91,
      status: 'accepted',
      cluster_a_label: 'Alice',
      cluster_b_label: 'Bob',
      cluster_a_identity_count: 50,
      cluster_b_identity_count: 2,
      source_cluster_id: largerUnconfirmed,
      target_cluster_id: smallerConfirmed,
      moved_identity_ids: [],
    };
    vi.mocked(recognitionApi.acceptMergeSuggestion).mockResolvedValue(acceptResponse);
    queryClient.setQueryData(mergePendingKey, makeMergePage([makeMerge('merge-flip')]));

    const wrapperWithSurvivors = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={queryClient}>
        <MergeSurvivorProvider>{children}</MergeSurvivorProvider>
      </QueryClientProvider>
    );

    const { result } = renderHook(
      () => {
        const mutations = useSuggestionReviewMutations({ queryClient, bulkActionRef });
        const survivors = useMergeSurvivors();
        return { mutations, survivors };
      },
      { wrapper: wrapperWithSurvivors },
    );

    act(() => {
      void result.current.mutations.scheduleAcceptMerge('merge-flip');
    });
    await expireHold();

    expect(recognitionApi.acceptMergeSuggestion).toHaveBeenCalledTimes(1);
    // Retired = larger A, survivor = smaller confirmed B (response ids).
    expect(result.current.survivors.resolveSurvivor(largerUnconfirmed)).toBe(smallerConfirmed);
    expect(result.current.survivors.resolveSurvivor(smallerConfirmed)).toBeNull();
  });

  it('BR-18/20: rejectMerge hold→success removes from cache + invalidates mergePending', async () => {
    queryClient.setQueryData(mergePendingKey, makeMergePage([makeMerge('merge-1')]));
    const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries');
    vi.mocked(recognitionApi.rejectMergeSuggestion).mockResolvedValue(makeMerge('merge-1'));

    const { result } = renderMutations();
    act(() => {
      void result.current.scheduleRejectMerge('merge-1');
    });
    await expireHold();

    expect(
      queryClient.getQueryData<PendingMergeSuggestionsResponse>(mergePendingKey)?.suggestions,
    ).toHaveLength(0);
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: mergePendingKey });
    expect(result.current.hold.phase).toBe('idle');
  });

  it('BR-18/20: acceptName hold→success removes from cache + invalidates namePending', async () => {
    queryClient.setQueryData(
      namePendingKey,
      makeNamePage([makeName('name-1'), { ...makeName('name-2'), id: 'name-2', cluster_id: 'cluster-other' }]),
    );
    const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries');
    vi.mocked(recognitionApi.acceptNameSuggestion).mockResolvedValue({
      suggestion_id: 'name-1',
      resolution: 'accepted',
      identity_id: 'identity-1',
      cluster_id: 'cluster-1',
      message: 'ok',
    });

    const { result } = renderMutations();
    act(() => {
      void result.current.scheduleAcceptName('name-1');
    });
    await expireHold();

    expect(
      queryClient.getQueryData<PendingNameSuggestionsResponse>(namePendingKey)?.suggestions.map((s) => s.id),
    ).toEqual(['name-2']);
    expect(invalidateSpy).toHaveBeenCalledWith(expect.objectContaining({ queryKey: namePendingKey }));
    expect(result.current.hold.phase).toBe('idle');
  });

  it('BR-18/20: rejectName hold→success removes from cache + invalidates namePending', async () => {
    queryClient.setQueryData(namePendingKey, makeNamePage([makeName('name-1')]));
    const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries');
    vi.mocked(recognitionApi.rejectNameSuggestion).mockResolvedValue({
      suggestion_id: 'name-1',
      resolution: 'rejected',
      identity_id: 'identity-1',
      cluster_id: null,
      message: 'ok',
    });

    const { result } = renderMutations();
    act(() => {
      void result.current.scheduleRejectName('name-1');
    });
    await expireHold();

    expect(
      queryClient.getQueryData<PendingNameSuggestionsResponse>(namePendingKey)?.suggestions,
    ).toHaveLength(0);
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: namePendingKey });
  });

  it('BR-20: name failure + retry re-fires exactly 1 POST', async () => {
    vi.mocked(recognitionApi.acceptNameSuggestion)
      .mockRejectedValueOnce(new Error('name fail'))
      .mockResolvedValueOnce({
        suggestion_id: 'name-1',
        resolution: 'accepted',
        identity_id: 'identity-1',
        cluster_id: 'cluster-1',
        message: 'ok',
      });
    queryClient.setQueryData(namePendingKey, makeNamePage([makeName('name-1')]));

    const { result } = renderMutations();
    act(() => {
      void result.current.scheduleAcceptName('name-1');
    });
    await expireHold();
    expect(result.current.hold.phase).toBe('failed');

    await act(async () => {
      await result.current.retryFailure();
    });

    expect(recognitionApi.acceptNameSuggestion).toHaveBeenCalledTimes(2);
    expect(result.current.hold.phase).toBe('idle');
    expect(
      queryClient.getQueryData<PendingNameSuggestionsResponse>(namePendingKey)?.suggestions,
    ).toHaveLength(0);
  });

  it('merge accept failure surfaces failed phase (pending/error built from zero)', async () => {
    vi.mocked(recognitionApi.acceptMergeSuggestion).mockRejectedValue(new Error('merge fail'));
    const { result } = renderMutations();

    act(() => {
      void result.current.scheduleAcceptMerge('merge-1');
    });
    await expireHold();

    expect(result.current.hold.phase).toBe('failed');
    expect(result.current.hold.kind).toBe('acceptMerge');
    expect(result.current.hold.errorMessage).toBeTruthy();
  });

  it('hold countdown pauses while setHoldPaused(true)', async () => {
    vi.mocked(recognitionApi.acceptSuggestion).mockResolvedValue({
      suggestion_id: 'sugg-a',
      resolution: 'accepted',
      identity_id: 'identity-a',
      cluster_id: 'cluster-1',
      message: 'ok',
    });

    const { result } = renderMutations();

    act(() => {
      void result.current.scheduleAccept('sugg-a');
    });

    act(() => {
      result.current.setHoldPaused(true);
    });

    await act(async () => {
      await vi.advanceTimersByTimeAsync(UNDO_HOLD_MS * 2);
      await Promise.resolve();
    });

    expect(recognitionApi.acceptSuggestion).not.toHaveBeenCalled();
    expect(result.current.hold.phase).toBe('holding');

    act(() => {
      result.current.setHoldPaused(false);
    });

    await expireHold();

    expect(recognitionApi.acceptSuggestion).toHaveBeenCalledTimes(1);
  });

  it('BR-15: isCardActionsDisabled only for held card; other ids stay enabled', () => {
    const { result } = renderMutations();
    act(() => {
      void result.current.scheduleAccept('sugg-a');
    });
    expect(result.current.hold.phase).toBe('holding');
    expect(result.current.isCardActionsDisabled('sugg-a', ['accept', 'reject'])).toBe(true);
    expect(result.current.isCardActionsDisabled('sugg-b', ['accept', 'reject'])).toBe(false);
  });

  // --- Slice 3: person-commit (flush-then-immediate, no undo window) ---

  it('person-commit routes to commitClusterToRosterEntry (not updateClusterLabel)', async () => {
    vi.mocked(rosterApi.commitClusterToRosterEntry).mockResolvedValue(rosterCommitFixture());
    const { result } = renderMutations();

    let outcome: string | undefined;
    await act(async () => {
      const promise = result.current.schedulePersonCommit({
        clusterId: 'cluster-1',
        newEntryName: 'Alex',
      });
      await Promise.resolve();
      await Promise.resolve();
      outcome = (await promise).outcome;
    });

    expect(rosterApi.commitClusterToRosterEntry).toHaveBeenCalledTimes(1);
    expect(rosterApi.commitClusterToRosterEntry).toHaveBeenCalledWith({
      clusterId: 'cluster-1',
      rosterEntryId: undefined,
      newEntryName: 'Alex',
    });
    expect(outcome).toBe('committed');
    expect(result.current.personCommit.phase).toBe('succeeded');
  });

  it('person-commit while accept hold is open flushes held commit first (single in-flight)', async () => {
    const order: string[] = [];
    vi.mocked(recognitionApi.acceptSuggestion).mockImplementation((id: string) => {
      order.push(`accept:${id}`);
      return Promise.resolve({
        suggestion_id: id,
        resolution: 'accepted' as const,
        identity_id: 'identity-a',
        cluster_id: 'cluster-1',
        message: 'ok',
      });
    });
    vi.mocked(rosterApi.commitClusterToRosterEntry).mockImplementation(() => {
      order.push('person-commit');
      return Promise.resolve(rosterCommitFixture());
    });

    const { result } = renderMutations();

    act(() => {
      void result.current.scheduleAccept('sugg-a');
    });
    expect(result.current.hold.phase).toBe('holding');
    expect(recognitionApi.acceptSuggestion).not.toHaveBeenCalled();

    let personOutcome: string | undefined;
    await act(async () => {
      const promise = result.current.schedulePersonCommit({
        clusterId: 'cluster-1',
        rosterEntryId: 42,
      });
      await Promise.resolve();
      await Promise.resolve();
      personOutcome = (await promise).outcome;
    });

    expect(order).toEqual(['accept:sugg-a', 'person-commit']);
    expect(recognitionApi.acceptSuggestion).toHaveBeenCalledTimes(1);
    expect(rosterApi.commitClusterToRosterEntry).toHaveBeenCalledTimes(1);
    expect(personOutcome).toBe('committed');
  });

  it('person-commit failure surfaces role=alert state + retry re-fires exactly 1 POST', async () => {
    vi.mocked(rosterApi.commitClusterToRosterEntry)
      .mockRejectedValueOnce(new Error('network'))
      .mockResolvedValueOnce(rosterCommitFixture());

    const { result } = renderMutations();

    await act(async () => {
      const promise = result.current.schedulePersonCommit({
        clusterId: 'cluster-1',
        newEntryName: 'Alex',
      });
      await Promise.resolve();
      await Promise.resolve();
      await promise;
    });

    expect(result.current.personCommit.phase).toBe('failed');
    expect(result.current.personCommit.errorMessage).toBeTruthy();
    expect(rosterApi.commitClusterToRosterEntry).toHaveBeenCalledTimes(1);

    await act(async () => {
      const retry = result.current.retryPersonCommit();
      expect(retry).not.toBeNull();
      await Promise.resolve();
      await Promise.resolve();
      await retry;
    });

    expect(rosterApi.commitClusterToRosterEntry).toHaveBeenCalledTimes(2);
    expect(result.current.personCommit.phase).toBe('succeeded');
  });

  it('BR-25: double schedulePersonCommit while first in flight yields exactly 1 POST', async () => {
    let resolvePost!: () => void;
    const gate = new Promise<void>((resolve) => {
      resolvePost = resolve;
    });
    vi.mocked(rosterApi.commitClusterToRosterEntry).mockImplementation(async () => {
      await gate;
      return rosterCommitFixture();
    });

    const { result } = renderMutations();

    let first!: Promise<{ outcome: string }>;
    let second!: Promise<{ outcome: string }>;
    act(() => {
      first = result.current.schedulePersonCommit({
        clusterId: 'cluster-1',
        newEntryName: 'Alex',
      });
      second = result.current.schedulePersonCommit({
        clusterId: 'cluster-1',
        newEntryName: 'Alex',
      });
    });

    expect(result.current.personCommitPending).toBe(true);

    await act(async () => {
      resolvePost();
      await first;
      await second;
      await Promise.resolve();
    });

    expect(rosterApi.commitClusterToRosterEntry).toHaveBeenCalledTimes(1);
    expect(result.current.personCommitPending).toBe(false);
  });

  it('BR-25: schedule during held-accept flush latency still yields exactly 1 person-commit POST', async () => {
    let resolveAccept!: () => void;
    const acceptGate = new Promise<void>((resolve) => {
      resolveAccept = resolve;
    });
    vi.mocked(recognitionApi.acceptSuggestion).mockImplementation(async () => {
      await acceptGate;
      return {
        suggestion_id: 'sugg-a',
        resolution: 'accepted' as const,
        identity_id: 'identity-a',
        cluster_id: 'cluster-1',
        message: 'ok',
      };
    });
    vi.mocked(rosterApi.commitClusterToRosterEntry).mockResolvedValue(rosterCommitFixture());

    const { result } = renderMutations();
    act(() => {
      void result.current.scheduleAccept('sugg-a');
    });
    expect(result.current.hold.phase).toBe('holding');

    let first!: Promise<{ outcome: string }>;
    let second!: Promise<{ outcome: string }>;
    act(() => {
      first = result.current.schedulePersonCommit({
        clusterId: 'cluster-1',
        rosterEntryId: 7,
      });
      // Second click while phase still idle / flush in flight.
      second = result.current.schedulePersonCommit({
        clusterId: 'cluster-1',
        rosterEntryId: 7,
      });
    });
    expect(result.current.personCommitPending).toBe(true);

    await act(async () => {
      resolveAccept();
      await first;
      await second;
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(rosterApi.commitClusterToRosterEntry).toHaveBeenCalledTimes(1);
  });

  it('BR-26: double retryPersonCommit while first in flight yields exactly 1 POST', async () => {
    let resolveRetry!: () => void;
    const retryGate = new Promise<void>((resolve) => {
      resolveRetry = resolve;
    });
    vi.mocked(rosterApi.commitClusterToRosterEntry)
      .mockRejectedValueOnce(new Error('network'))
      .mockImplementationOnce(async () => {
        await retryGate;
        return rosterCommitFixture();
      });

    const { result } = renderMutations();

    await act(async () => {
      const promise = result.current.schedulePersonCommit({
        clusterId: 'cluster-1',
        newEntryName: 'Alex',
      });
      await Promise.resolve();
      await Promise.resolve();
      await promise;
    });
    expect(result.current.personCommit.phase).toBe('failed');

    let first: Promise<unknown> | null = null;
    let second: Promise<unknown> | null = null;
    act(() => {
      first = result.current.retryPersonCommit();
      second = result.current.retryPersonCommit();
    });

    expect(first).not.toBeNull();
    expect(second).toBeNull();
    expect(result.current.personCommitPending).toBe(true);

    await act(async () => {
      resolveRetry();
      await first;
      await Promise.resolve();
    });

    // fail + one retry
    expect(rosterApi.commitClusterToRosterEntry).toHaveBeenCalledTimes(2);
    expect(result.current.personCommitPending).toBe(false);
  });

  it('BR-28: person-commit success invalidates clusterLabelSetClear kept targets', async () => {
    vi.mocked(rosterApi.commitClusterToRosterEntry).mockResolvedValue(rosterCommitFixture());
    const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries');
    const { result } = renderMutations();

    await act(async () => {
      const promise = result.current.schedulePersonCommit({
        clusterId: 'cluster-1',
        newEntryName: 'Alex',
      });
      await Promise.resolve();
      await Promise.resolve();
      await promise;
    });

    expect(invalidateSpy).toHaveBeenCalledWith(
      expect.objectContaining({ queryKey: queryKeys.suggestions.projection.all }),
    );
    expectCrossFamilyPresent(invalidateSpy, 'clusterLabelSetClear');
  });

  it('BR-29: person-commit success removes namePending rows for the committed cluster', async () => {
    queryClient.setQueryData(
      namePendingKey,
      makeNamePage([makeName('name-1'), makeName('name-other')]),
    );
    // name-other on a different cluster so only cluster-1 rows leave.
    queryClient.setQueryData(namePendingKey, {
      ...makeNamePage([
        makeName('name-1'),
        { ...makeName('name-other'), id: 'name-other', cluster_id: 'cluster-other' },
      ]),
    });
    vi.mocked(rosterApi.commitClusterToRosterEntry).mockResolvedValue(rosterCommitFixture());

    const { result } = renderMutations();
    await act(async () => {
      const promise = result.current.schedulePersonCommit({
        clusterId: 'cluster-1',
        newEntryName: 'Alex',
      });
      await Promise.resolve();
      await Promise.resolve();
      await promise;
    });

    const remaining = queryClient.getQueryData<PendingNameSuggestionsResponse>(namePendingKey);
    expect(remaining?.suggestions.map((s) => s.id)).toEqual(['name-other']);
  });

  it('S2-02: person-commit optimistic namePending drop survives the invalidation (no refetch clobber)', async () => {
    // Backend still returns the just-committed cluster's row (curation lag).
    const staleServer: PendingNameSuggestionsResponse = {
      ...makeNamePage([
        makeName('name-1'), // cluster-1 — about to be committed
        { ...makeName('name-other'), id: 'name-other', cluster_id: 'cluster-other' },
      ]),
    };
    const fetchName = vi.fn().mockResolvedValue(staleServer);
    queryClient.setQueryData(namePendingKey, staleServer);
    vi.mocked(rosterApi.commitClusterToRosterEntry).mockResolvedValue(rosterCommitFixture());

    // An ACTIVE observer makes invalidateQueries refetch — this is what reproduces the race.
    const { result } = renderHook(
      () => {
        const q = useQuery({ queryKey: namePendingKey, queryFn: fetchName, staleTime: 0 });
        const m = useSuggestionReviewMutations({ queryClient, bulkActionRef });
        return { q, m };
      },
      { wrapper },
    );

    // Let the observer's mount fetch settle before we measure the commit's behaviour.
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    fetchName.mockClear();

    await act(async () => {
      const promise = result.current.m.schedulePersonCommit({
        clusterId: 'cluster-1',
        newEntryName: 'Alex',
      });
      await Promise.resolve();
      await Promise.resolve();
      await promise;
      // Give any (wrongly) triggered refetch a chance to resolve and clobber the removal.
      await Promise.resolve();
      await Promise.resolve();
    });

    // The invalidation must NOT refetch namePending (refetchType 'none').
    expect(fetchName).not.toHaveBeenCalled();
    // The committed cluster's row stays dropped; the other cluster's row survives.
    const remaining = queryClient.getQueryData<PendingNameSuggestionsResponse>(namePendingKey);
    expect(remaining?.suggestions.map((s) => s.id)).toEqual(['name-other']);
  });

  it('UXW2-2 (B6): person-commit drops the committed cluster from all four review caches', async () => {
    queryClient.setQueryData(
      reviewPageKey,
      makePage([
        makeItem({ suggestionId: 'sugg-x', clusterId: 'cluster-1' }),
        makeItem({ suggestionId: 'sugg-source', clusterId: 'elsewhere' }),
        makeItem({ suggestionId: 'sugg-y', clusterId: 'cluster-other' }),
      ]),
    );
    queryClient.setQueryData(
      namePendingKey,
      makeNamePage([
        makeName('name-1'),
        { ...makeName('name-other'), id: 'name-other', cluster_id: 'cluster-other' },
      ]),
    );
    queryClient.setQueryData(
      mergePendingKey,
      makeMergePage([
        { ...makeMerge('merge-a-side'), cluster_a_id: 'cluster-1', cluster_b_id: 'b' },
        { ...makeMerge('merge-b-side'), cluster_a_id: 'c', cluster_b_id: 'cluster-1' },
        { ...makeMerge('merge-unrelated'), cluster_a_id: 'd', cluster_b_id: 'e' },
      ]),
    );
    const topUnlabeledKey = queryKeys.clusters.topUnlabeled('test-tenant');
    queryClient.setQueryData(
      topUnlabeledKey,
      makeTopUnlabeledPage([makeTopCluster('cluster-1'), makeTopCluster('cluster-other')]),
    );
    vi.mocked(rosterApi.commitClusterToRosterEntry).mockResolvedValue(rosterCommitFixture());

    const { result } = renderMutations();
    await act(async () => {
      const promise = result.current.schedulePersonCommit({
        clusterId: 'cluster-1',
        newEntryName: 'Alex',
      });
      await Promise.resolve();
      await Promise.resolve();
      await promise;
    });

    expect(
      queryClient.getQueryData<SuggestionReviewPage>(reviewPageKey)?.items.map((item) => item.suggestionId),
    ).toEqual(['sugg-source', 'sugg-y']);
    expect(
      queryClient.getQueryData<PendingNameSuggestionsResponse>(namePendingKey)?.suggestions.map((s) => s.id),
    ).toEqual(['name-other']);
    // R1-23: naming does not resolve a merge suggestion.
    expect(
      queryClient.getQueryData<PendingMergeSuggestionsResponse>(mergePendingKey)?.suggestions.map((s) => s.id),
    ).toEqual(['merge-a-side', 'merge-b-side', 'merge-unrelated']);
    expect(
      queryClient.getQueryData<TopUnlabeledClustersResponse>(topUnlabeledKey)?.clusters.map((c) => c.id),
    ).toEqual(['cluster-other']);
  });

  it('R1-18: person-commit four-cache drop survives active observers that still return the row', async () => {
    const staleAssignment: SuggestionReviewPage = makePage([
      makeItem({ suggestionId: 'sugg-x', clusterId: 'cluster-1' }),
      makeItem({ suggestionId: 'sugg-y', clusterId: 'cluster-other' }),
    ]);
    const staleName = makeNamePage([
      makeName('name-1'),
      { ...makeName('name-other'), id: 'name-other', cluster_id: 'cluster-other' },
    ]);
    const staleMerge = makeMergePage([
      { ...makeMerge('merge-live'), cluster_a_id: 'cluster-1', cluster_b_id: 'cluster-other' },
    ]);
    const topUnlabeledKey = queryKeys.clusters.topUnlabeled('test-tenant');
    const staleTop = makeTopUnlabeledPage([makeTopCluster('cluster-1'), makeTopCluster('cluster-other')]);

    const fetchAssignment = vi.fn().mockResolvedValue(staleAssignment);
    const fetchName = vi.fn().mockResolvedValue(staleName);
    const fetchMerge = vi.fn().mockResolvedValue(staleMerge);
    const fetchTop = vi.fn().mockResolvedValue(staleTop);

    queryClient.setQueryData(reviewPageKey, staleAssignment);
    queryClient.setQueryData(namePendingKey, staleName);
    queryClient.setQueryData(mergePendingKey, staleMerge);
    queryClient.setQueryData(topUnlabeledKey, staleTop);
    vi.mocked(rosterApi.commitClusterToRosterEntry).mockResolvedValue(rosterCommitFixture());

    const { result } = renderHook(
      () => {
        const assignment = useQuery({ queryKey: reviewPageKey, queryFn: fetchAssignment, staleTime: 0 });
        const name = useQuery({ queryKey: namePendingKey, queryFn: fetchName, staleTime: 0 });
        const merge = useQuery({ queryKey: mergePendingKey, queryFn: fetchMerge, staleTime: 0 });
        const top = useQuery({ queryKey: topUnlabeledKey, queryFn: fetchTop, staleTime: 0 });
        const m = useSuggestionReviewMutations({ queryClient, bulkActionRef });
        return { assignment, name, merge, top, m };
      },
      { wrapper },
    );

    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    fetchAssignment.mockClear();
    fetchName.mockClear();
    fetchMerge.mockClear();
    fetchTop.mockClear();

    await act(async () => {
      const promise = result.current.m.schedulePersonCommit({
        clusterId: 'cluster-1',
        newEntryName: 'Alex',
      });
      await Promise.resolve();
      await Promise.resolve();
      await promise;
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(fetchAssignment).not.toHaveBeenCalled();
    expect(fetchName).not.toHaveBeenCalled();
    expect(fetchMerge).not.toHaveBeenCalled();
    expect(fetchTop).not.toHaveBeenCalled();
    expect(
      queryClient.getQueryData<SuggestionReviewPage>(reviewPageKey)?.items.map((item) => item.suggestionId),
    ).toEqual(['sugg-y']);
    expect(
      queryClient.getQueryData<PendingNameSuggestionsResponse>(namePendingKey)?.suggestions.map((s) => s.id),
    ).toEqual(['name-other']);
    expect(
      queryClient.getQueryData<PendingMergeSuggestionsResponse>(mergePendingKey)?.suggestions.map((s) => s.id),
    ).toEqual(['merge-live']);
    expect(
      queryClient.getQueryData<TopUnlabeledClustersResponse>(topUnlabeledKey)?.clusters.map((c) => c.id),
    ).toEqual(['cluster-other']);
  });

  it('R1-17: acceptMerge drops the retired source from all four caches and keeps the survivor', async () => {
    queryClient.setQueryData(
      reviewPageKey,
      makePage([
        makeItem({ suggestionId: 'sugg-retired', clusterId: 'cluster-1' }),
        makeItem({ suggestionId: 'sugg-survivor', clusterId: 'cluster-2' }),
      ]),
    );
    queryClient.setQueryData(
      namePendingKey,
      makeNamePage([
        makeName('name-1'),
        { ...makeName('name-surv'), id: 'name-surv', cluster_id: 'cluster-2' },
      ]),
    );
    const mergeRow: AcceptedMergeSuggestion = {
      ...makeMerge('merge-1'),
      cluster_a_id: 'cluster-1',
      cluster_b_id: 'cluster-2',
      source_cluster_id: 'cluster-1',
      target_cluster_id: 'cluster-2',
      moved_identity_ids: [],
    };
    queryClient.setQueryData(
      mergePendingKey,
      makeMergePage([
        mergeRow,
        { ...makeMerge('merge-sib'), cluster_a_id: 'cluster-2', cluster_b_id: 'cluster-3' },
      ]),
    );
    const topUnlabeledKey = queryKeys.clusters.topUnlabeled('test-tenant');
    queryClient.setQueryData(
      topUnlabeledKey,
      makeTopUnlabeledPage([makeTopCluster('cluster-1'), makeTopCluster('cluster-2')]),
    );
    vi.mocked(recognitionApi.acceptMergeSuggestion).mockResolvedValue(mergeRow);

    const { result } = renderMutations();
    act(() => {
      void result.current.scheduleAcceptMerge('merge-1');
    });
    await expireHold();

    expect(
      queryClient.getQueryData<SuggestionReviewPage>(reviewPageKey)?.items.map((item) => item.suggestionId),
    ).toEqual(['sugg-survivor']);
    expect(
      queryClient.getQueryData<PendingNameSuggestionsResponse>(namePendingKey)?.suggestions.map((s) => s.id),
    ).toEqual(['name-surv']);
    expect(
      queryClient.getQueryData<PendingMergeSuggestionsResponse>(mergePendingKey)?.suggestions.map((s) => s.id),
    ).toEqual(['merge-sib']);
    expect(
      queryClient.getQueryData<TopUnlabeledClustersResponse>(topUnlabeledKey)?.clusters.map((c) => c.id),
    ).toEqual(['cluster-2']);
  });

  it('R3-08: unmount during acceptMerge still drops the retired source', async () => {
    const mergeRow: AcceptedMergeSuggestion = {
      ...makeMerge('merge-1'),
      cluster_a_id: 'cluster-1',
      cluster_b_id: 'cluster-2',
      source_cluster_id: 'cluster-1',
      target_cluster_id: 'cluster-2',
      moved_identity_ids: [],
    };
    queryClient.setQueryData(mergePendingKey, makeMergePage([mergeRow, makeMerge('merge-sib')]));
    const topUnlabeledKey = queryKeys.clusters.topUnlabeled('test-tenant');
    queryClient.setQueryData(
      topUnlabeledKey,
      makeTopUnlabeledPage([makeTopCluster('cluster-1'), makeTopCluster('cluster-2')]),
    );

    let resolveAccept: (value: AcceptedMergeSuggestion) => void = () => undefined;
    vi.mocked(recognitionApi.acceptMergeSuggestion).mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveAccept = resolve;
        }),
    );

    const { result, unmount } = renderMutations();
    act(() => {
      void result.current.scheduleAcceptMerge('merge-1');
    });
    unmount();

    await act(async () => {
      resolveAccept(mergeRow);
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(
      queryClient.getQueryData<PendingMergeSuggestionsResponse>(mergePendingKey)?.suggestions.map((s) => s.id),
    ).toEqual(['merge-sib']);
    expect(
      queryClient.getQueryData<TopUnlabeledClustersResponse>(topUnlabeledKey)?.clusters.map((c) => c.id),
    ).toEqual(['cluster-2']);
  });

  it('R1-21: foreign source_cluster_id does not evict an innocent group', async () => {
    queryClient.setQueryData(
      reviewPageKey,
      makePage([makeItem({ suggestionId: 'sugg-innocent', clusterId: 'innocent' })]),
    );
    queryClient.setQueryData(namePendingKey, makeNamePage([{ ...makeName('name-inn'), cluster_id: 'innocent' }]));
    const topUnlabeledKey = queryKeys.clusters.topUnlabeled('test-tenant');
    queryClient.setQueryData(topUnlabeledKey, makeTopUnlabeledPage([makeTopCluster('innocent')]));
    const foreign: AcceptedMergeSuggestion = {
      ...makeMerge('merge-1'),
      cluster_a_id: 'cluster-a',
      cluster_b_id: 'cluster-b',
      source_cluster_id: 'innocent',
      target_cluster_id: 'cluster-b',
      moved_identity_ids: [],
    };
    queryClient.setQueryData(mergePendingKey, makeMergePage([foreign]));
    vi.mocked(recognitionApi.acceptMergeSuggestion).mockResolvedValue(foreign);

    const { result } = renderMutations();
    act(() => {
      void result.current.scheduleAcceptMerge('merge-1');
    });
    await expireHold();

    expect(
      queryClient.getQueryData<SuggestionReviewPage>(reviewPageKey)?.items.map((item) => item.suggestionId),
    ).toEqual(['sugg-innocent']);
    expect(
      queryClient.getQueryData<PendingNameSuggestionsResponse>(namePendingKey)?.suggestions.map((s) => s.id),
    ).toEqual(['name-inn']);
    expect(
      queryClient.getQueryData<TopUnlabeledClustersResponse>(topUnlabeledKey)?.clusters.map((c) => c.id),
    ).toEqual(['innocent']);
  });

  it('R1-24: acceptName drops the accepted group from namePending and topUnlabeled', async () => {
    queryClient.setQueryData(
      namePendingKey,
      makeNamePage([makeName('name-1'), { ...makeName('name-2'), id: 'name-2', cluster_id: 'cluster-other' }]),
    );
    const topUnlabeledKey = queryKeys.clusters.topUnlabeled('test-tenant');
    queryClient.setQueryData(
      topUnlabeledKey,
      makeTopUnlabeledPage([makeTopCluster('cluster-1'), makeTopCluster('cluster-other')]),
    );
    vi.mocked(recognitionApi.acceptNameSuggestion).mockResolvedValue({
      suggestion_id: 'name-1',
      resolution: 'accepted',
      identity_id: 'identity-1',
      cluster_id: 'cluster-1',
      message: 'ok',
    });

    const { result } = renderMutations();
    act(() => {
      void result.current.scheduleAcceptName('name-1');
    });
    await expireHold();

    expect(
      queryClient.getQueryData<PendingNameSuggestionsResponse>(namePendingKey)?.suggestions.map((s) => s.id),
    ).toEqual(['name-2']);
    expect(
      queryClient.getQueryData<TopUnlabeledClustersResponse>(topUnlabeledKey)?.clusters.map((c) => c.id),
    ).toEqual(['cluster-other']);
  });

  it('R8-03: matching accepted_count still refetches when the response has no ids', async () => {
    queryClient.setQueryData(
      namePendingKey,
      makeNamePage([
        { ...makeName('name-1'), confidence_score: 0.95 },
        { ...makeName('name-2'), id: 'name-2', cluster_id: 'cluster-2', confidence_score: 0.9 },
      ]),
    );
    const topUnlabeledKey = queryKeys.clusters.topUnlabeled('test-tenant');
    queryClient.setQueryData(
      topUnlabeledKey,
      makeTopUnlabeledPage([makeTopCluster('cluster-1'), makeTopCluster('cluster-2')]),
    );
    const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries');
    vi.mocked(recognitionApi.bulkAcceptSuggestions).mockResolvedValue({
      accepted_count: 2,
      skipped_count: 0,
    });

    const { result } = renderMutations();
    await act(async () => {
      await result.current.mutations.bulkAccept.mutateAsync({
        suggestion_type: 'name',
        min_confidence: 0.8,
      });
    });

    // Same cardinality as matched.length, different member set is possible.
    // Without accepted ids the client cannot evict — refetch instead.
    expect(
      queryClient.getQueryData<PendingNameSuggestionsResponse>(namePendingKey)?.suggestions.map((s) => s.id),
    ).toEqual(['name-1', 'name-2']);
    expect(
      queryClient.getQueryData<TopUnlabeledClustersResponse>(topUnlabeledKey)?.clusters.map((c) => c.id),
    ).toEqual(['cluster-1', 'cluster-2']);
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: namePendingKey });
    expect(invalidateSpy).toHaveBeenCalledWith({
      queryKey: [...queryKeys.clusters.all, 'top-unlabeled'],
    });
  });

  it('R1-24: bulkAccept name type does not guess which above-threshold row the server accepted', async () => {
    queryClient.setQueryData(
      namePendingKey,
      makeNamePage([
        { ...makeName('name-1'), confidence_score: 0.95 },
        { ...makeName('name-low'), id: 'name-low', cluster_id: 'cluster-low', confidence_score: 0.2 },
      ]),
    );
    const topUnlabeledKey = queryKeys.clusters.topUnlabeled('test-tenant');
    queryClient.setQueryData(
      topUnlabeledKey,
      makeTopUnlabeledPage([makeTopCluster('cluster-1'), makeTopCluster('cluster-low')]),
    );
    const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries');
    vi.mocked(recognitionApi.bulkAcceptSuggestions).mockResolvedValue({
      accepted_count: 1,
      skipped_count: 0,
    });

    const { result } = renderMutations();
    await act(async () => {
      await result.current.mutations.bulkAccept.mutateAsync({
        suggestion_type: 'name',
        min_confidence: 0.8,
      });
    });

    expect(
      queryClient.getQueryData<PendingNameSuggestionsResponse>(namePendingKey)?.suggestions.map((s) => s.id),
    ).toEqual(['name-1', 'name-low']);
    expect(
      queryClient.getQueryData<TopUnlabeledClustersResponse>(topUnlabeledKey)?.clusters.map((c) => c.id),
    ).toEqual(['cluster-1', 'cluster-low']);
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: namePendingKey });
  });

  it('R5-01: a 200 with accepted_count 0 evicts nothing', async () => {
    queryClient.setQueryData(
      namePendingKey,
      makeNamePage([
        { ...makeName('name-1'), confidence_score: 0.95 },
        { ...makeName('name-low'), id: 'name-low', cluster_id: 'cluster-low', confidence_score: 0.2 },
      ]),
    );
    const topUnlabeledKey = queryKeys.clusters.topUnlabeled('test-tenant');
    queryClient.setQueryData(
      topUnlabeledKey,
      makeTopUnlabeledPage([makeTopCluster('cluster-1'), makeTopCluster('cluster-low')]),
    );
    vi.mocked(recognitionApi.bulkAcceptSuggestions).mockResolvedValue({
      accepted_count: 0,
      skipped_count: 2,
    });

    const { result } = renderMutations();
    await act(async () => {
      await result.current.mutations.bulkAccept.mutateAsync({
        suggestion_type: 'name',
        min_confidence: 0.8,
      });
    });

    expect(
      queryClient.getQueryData<PendingNameSuggestionsResponse>(namePendingKey)?.suggestions.map((s) => s.id),
    ).toEqual(['name-1', 'name-low']);
  });

  it('R5-01: a partial accept refetches instead of guessing', async () => {
    const namePage = makeNamePage([
      { ...makeName('name-1'), confidence_score: 0.95 },
      { ...makeName('name-low'), id: 'name-low', cluster_id: 'cluster-low', confidence_score: 0.2 },
    ]);
    const topUnlabeledKey = queryKeys.clusters.topUnlabeled('test-tenant');
    const topPage = makeTopUnlabeledPage([makeTopCluster('cluster-1'), makeTopCluster('cluster-low')]);
    queryClient.setQueryData(namePendingKey, namePage);
    queryClient.setQueryData(topUnlabeledKey, topPage);
    const fetchName = vi.fn().mockResolvedValue(namePage);
    const fetchTop = vi.fn().mockResolvedValue(topPage);
    const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries');
    vi.mocked(recognitionApi.bulkAcceptSuggestions).mockResolvedValue({
      accepted_count: 1,
      skipped_count: 1,
    });

    const { result } = renderHook(
      () => {
        const name = useQuery({ queryKey: namePendingKey, queryFn: fetchName, staleTime: 0 });
        const top = useQuery({ queryKey: topUnlabeledKey, queryFn: fetchTop, staleTime: 0 });
        const m = useSuggestionReviewMutations({ queryClient, bulkActionRef });
        return { name, top, m };
      },
      { wrapper },
    );

    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    fetchName.mockClear();
    fetchTop.mockClear();

    await act(async () => {
      await result.current.m.mutations.bulkAccept.mutateAsync({
        suggestion_type: 'name',
        min_confidence: 0.8,
      });
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: namePendingKey });
    expect(invalidateSpy).toHaveBeenCalledWith({
      queryKey: [...queryKeys.clusters.all, 'top-unlabeled'],
    });
    expect(fetchName).toHaveBeenCalled();
    expect(fetchTop).toHaveBeenCalled();
    expect(
      queryClient.getQueryData<PendingNameSuggestionsResponse>(namePendingKey)?.suggestions.map((s) => s.id),
    ).toEqual(['name-1', 'name-low']);
    expect(
      queryClient.getQueryData<TopUnlabeledClustersResponse>(topUnlabeledKey)?.clusters.map((c) => c.id),
    ).toEqual(['cluster-1', 'cluster-low']);
  });

  it('R7-07: full accept that disagrees with local cache invalidates instead of evicting', async () => {
    queryClient.setQueryData(
      namePendingKey,
      makeNamePage([
        { ...makeName('name-1'), confidence_score: 0.95 },
        { ...makeName('name-2'), id: 'name-2', cluster_id: 'cluster-2', confidence_score: 0.9 },
      ]),
    );
    const topUnlabeledKey = queryKeys.clusters.topUnlabeled('test-tenant');
    queryClient.setQueryData(
      topUnlabeledKey,
      makeTopUnlabeledPage([makeTopCluster('cluster-1'), makeTopCluster('cluster-2')]),
    );
    const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries');
    vi.mocked(recognitionApi.bulkAcceptSuggestions).mockResolvedValue({
      accepted_count: 1,
      skipped_count: 0,
    });

    const { result } = renderMutations();
    await act(async () => {
      await result.current.mutations.bulkAccept.mutateAsync({
        suggestion_type: 'name',
        min_confidence: 0.8,
      });
    });

    expect(
      queryClient.getQueryData<PendingNameSuggestionsResponse>(namePendingKey)?.suggestions.map((s) => s.id),
    ).toEqual(['name-1', 'name-2']);
    expect(
      queryClient.getQueryData<TopUnlabeledClustersResponse>(topUnlabeledKey)?.clusters.map((c) => c.id),
    ).toEqual(['cluster-1', 'cluster-2']);
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: namePendingKey });
    expect(invalidateSpy).toHaveBeenCalledWith({
      queryKey: [...queryKeys.clusters.all, 'top-unlabeled'],
    });
  });

  it('R1-24: bulkAccept name type invalidates the header source instead of locally decrementing', async () => {
    queryClient.setQueryData(
      namePendingKey,
      makeNamePage([
        { ...makeName('name-1'), confidence_score: 0.95 },
        { ...makeName('name-2'), id: 'name-2', cluster_id: 'cluster-2', confidence_score: 0.9 },
      ]),
    );
    const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries');
    vi.mocked(recognitionApi.bulkAcceptSuggestions).mockResolvedValue({
      accepted_count: 2,
      skipped_count: 0,
    });

    const { result } = renderMutations();
    await act(async () => {
      await result.current.mutations.bulkAccept.mutateAsync({
        suggestion_type: 'name',
        min_confidence: 0.8,
      });
    });

    expect(queryClient.getQueryData<PendingNameSuggestionsResponse>(namePendingKey)?.suggestions).toHaveLength(2);
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: namePendingKey });
  });

  it('R1-24: bulkAccept assignment type is scoped out (no silent drop)', async () => {
    queryClient.setQueryData(
      reviewPageKey,
      makePage([makeItem({ suggestionId: 'sugg-a', clusterId: 'cluster-1', similarity: 0.95 })]),
    );
    const topUnlabeledKey = queryKeys.clusters.topUnlabeled('test-tenant');
    queryClient.setQueryData(topUnlabeledKey, makeTopUnlabeledPage([makeTopCluster('cluster-1')]));

    const { result } = renderMutations();
    await expect(
      result.current.mutations.bulkAccept.mutateAsync({
        suggestion_type: 'assignment',
        min_confidence: 0.5,
      }),
    ).rejects.toThrow('Bulk accept is only available for name suggestions.');

    expect(
      queryClient.getQueryData<SuggestionReviewPage>(reviewPageKey)?.items.map((item) => item.suggestionId),
    ).toEqual(['sugg-a']);
    expect(
      queryClient.getQueryData<TopUnlabeledClustersResponse>(topUnlabeledKey)?.clusters.map((c) => c.id),
    ).toEqual(['cluster-1']);
  });

  it('R1-24: bulkAccept merge type is scoped out (no silent drop)', async () => {
    const mergeRow = {
      ...makeMerge('merge-1'),
      cluster_a_id: 'cluster-1',
      cluster_b_id: 'cluster-2',
      source_cluster_id: 'cluster-1',
      target_cluster_id: 'cluster-2',
      similarity: 0.95,
    };
    queryClient.setQueryData(mergePendingKey, makeMergePage([mergeRow]));
    const topUnlabeledKey = queryKeys.clusters.topUnlabeled('test-tenant');
    queryClient.setQueryData(
      topUnlabeledKey,
      makeTopUnlabeledPage([makeTopCluster('cluster-1'), makeTopCluster('cluster-2')]),
    );

    const { result } = renderMutations();
    await expect(
      result.current.mutations.bulkAccept.mutateAsync({
        suggestion_type: 'merge',
        min_confidence: 0.5,
      }),
    ).rejects.toThrow('Bulk accept is only available for name suggestions.');

    expect(
      queryClient.getQueryData<PendingMergeSuggestionsResponse>(mergePendingKey)?.suggestions.map((s) => s.id),
    ).toEqual(['merge-1']);
    expect(
      queryClient.getQueryData<TopUnlabeledClustersResponse>(topUnlabeledKey)?.clusters.map((c) => c.id),
    ).toEqual(['cluster-1', 'cluster-2']);
  });
});
