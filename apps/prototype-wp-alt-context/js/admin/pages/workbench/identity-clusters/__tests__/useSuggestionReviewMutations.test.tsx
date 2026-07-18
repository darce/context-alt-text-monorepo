/**
 * E21-5 Slice 2 — gated advance + undo hold concurrency tests.
 *
 * Named exit criteria: rapid double-action, unmount-during-window, post-window
 * failure re-surface, undo-cancel=0, commit=1, advance-only-on-success,
 * invalidation presence, hold/failure announce.
 */

import type { ReactNode } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, render, renderHook, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { queryKeys } from '../../../../api/queryKeys';
import { DATA_SOURCE } from '../../../../api/recognition/types';
import * as recognitionApi from '../../../../api/recognition';
import {
  SUGGESTION_PROJECTION_INVALIDATION_EVENTS,
  type SuggestionProjectionInvalidationEvent,
} from '../suggestionProjection';
import type { ProjectedSuggestion } from '../suggestionProjection';
import type { SuggestionReviewPage } from '../useSuggestionReviewQueries';
import {
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

const reviewPageKey = queryKeys.suggestions.projection.reviewPage(0);

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

const crossFamilyQueryKey = (target: string): readonly unknown[] => {
  switch (target) {
    case 'clusters.all':
      return queryKeys.clusters.all;
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
    expect(spy).toHaveBeenCalledWith({ queryKey: crossFamilyQueryKey(target) });
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

  it('unmount-during-window: unmount with held commit fires exactly 1 POST and no state update after unmount', async () => {
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
    });

    expect(recognitionApi.acceptSuggestion).toHaveBeenCalledTimes(1);
    expect(recognitionApi.acceptSuggestion).toHaveBeenCalledWith('sugg-a');
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
});

describe('useSuggestionReviewMutations announce harness', () => {
  let queryClient: QueryClient;
  let bulkActionRef: { current: boolean };

  beforeEach(() => {
    vi.clearAllMocks();
    vi.useFakeTimers();
    bulkActionRef = { current: false };
    queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('renders role=status hold and persistent role=alert on failure with retry', async () => {
    vi.mocked(recognitionApi.acceptSuggestion)
      .mockRejectedValueOnce(new Error('fail'))
      .mockResolvedValueOnce({
        suggestion_id: 'sugg-a',
        resolution: 'accepted',
        identity_id: 'identity-a',
        cluster_id: 'cluster-1',
        message: 'ok',
      });

    const Harness = function Harness() {
      const api = useSuggestionReviewMutations({ queryClient, bulkActionRef });
      return (
        <div>
          <button type="button" onClick={() => void api.scheduleAccept('sugg-a')}>
            Accept
          </button>
          <button
            type="button"
            onClick={() => {
              void api.flushHeld();
            }}
          >
            Flush
          </button>
          {(api.hold.phase === 'holding' || api.hold.phase === 'committing') && (
            <div role="status">
              {api.holdAnnounce}
              {api.hold.phase === 'holding' ? (
                <button type="button" onClick={api.undoHold}>
                  Undo
                </button>
              ) : null}
            </div>
          )}
          {api.hold.phase === 'failed' && (
            <div role="alert">
              {api.hold.errorMessage}
              <button
                type="button"
                onClick={() => {
                  void api.retryFailure();
                }}
              >
                Retry
              </button>
            </div>
          )}
        </div>
      );
    }

    render(
      <QueryClientProvider client={queryClient}>
        <Harness />
      </QueryClientProvider>,
    );

    act(() => {
      screen.getByRole('button', { name: 'Accept' }).click();
    });

    expect(screen.getByRole('status')).toHaveTextContent('Saving… — Undo');
    expect(screen.getByRole('button', { name: 'Undo' })).toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();

    await act(async () => {
      screen.getByRole('button', { name: 'Flush' }).click();
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(screen.getByRole('alert')).toBeInTheDocument();

    // Persistent: still present after more ticks.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10_000);
    });
    expect(screen.getByRole('alert')).toBeInTheDocument();
    expect(screen.queryByRole('status')).not.toBeInTheDocument();

    await act(async () => {
      screen.getByRole('button', { name: 'Retry' }).click();
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(recognitionApi.acceptSuggestion).toHaveBeenCalledTimes(2);
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });
});
