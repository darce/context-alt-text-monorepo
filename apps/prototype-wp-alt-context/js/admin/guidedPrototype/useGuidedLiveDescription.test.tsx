import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Mock } from 'vitest';

import type { DescribeRunItemsResponse, DescribeRunResponse } from '../api/describeApi';
import { GUIDED_LIVE_STATUS, GUIDED_LIVE_WAIT_CEILING_SECONDS } from './liveDescription';
import { confirmGuidedIdentity, createGuidedScenario, leaveGuidedIdentityUnidentified } from './state';
import type { GuidedScenario } from './state';
import { GUIDED_LIVE_WARM_CEILING_SECONDS, useGuidedLiveDescription } from './useGuidedLiveDescription';
import type { GuidedLiveDescriptionClient } from './useGuidedLiveDescription';

const MEDIA_ID = 4211;

const runResponse = (over: Partial<DescribeRunResponse> = {}): DescribeRunResponse => ({
  tenant_id: 'demo',
  run_id: 'run-1',
  status: 'running',
  phase: 'queued',
  completed: 0,
  failed: 0,
  skipped: 0,
  total: 1,
  cancel_requested: false,
  eta_seconds: null,
  gpu_state: 'stopped',
  recognition_enabled: true,
  ...over,
});

const itemsResponse = (
  draft: string | null,
  tier: DescribeRunItemsResponse['items'][number]['tier'] = 'final_gpu',
): DescribeRunItemsResponse => ({
  run_id: 'run-1',
  items: [
    {
      media_id: MEDIA_ID,
      status: 'completed',
      alt_text_draft: draft,
      caption: null,
      provenance: null,
      tier,
      result_generation: 1,
      existing_alt: false,
    },
  ],
});

type StubClient = {
  [K in keyof GuidedLiveDescriptionClient]: Mock<GuidedLiveDescriptionClient[K]>;
};

const stubClient = (over: Partial<StubClient> = {}): StubClient => ({
  submit: vi.fn<GuidedLiveDescriptionClient['submit']>(() => Promise.resolve(runResponse())),
  poll: vi.fn<GuidedLiveDescriptionClient['poll']>(() =>
    Promise.resolve(runResponse({ phase: 'warming', gpu_state: 'starting' })),
  ),
  items: vi.fn<GuidedLiveDescriptionClient['items']>(() =>
    Promise.resolve(itemsResponse('Katy Perry waves from the red carpet.')),
  ),
  cancel: vi.fn<GuidedLiveDescriptionClient['cancel']>(() =>
    Promise.resolve(runResponse({ status: 'cancelled', phase: 'cancelled' })),
  ),
  ...over,
});

/** Every face answered: one confirmed, one deliberately left unidentified. */
const decidedScenario = (): GuidedScenario =>
  leaveGuidedIdentityUnidentified(confirmGuidedIdentity(createGuidedScenario(), 'katy-perry'), 'justin-trudeau');

/** One face answered, one still open -- the gate must stay shut. */
const halfDecidedScenario = (): GuidedScenario => confirmGuidedIdentity(createGuidedScenario(), 'katy-perry');

/** No confirmations at all, but nothing left open either. */
const allUnidentifiedScenario = (): GuidedScenario =>
  leaveGuidedIdentityUnidentified(
    leaveGuidedIdentityUnidentified(createGuidedScenario(), 'katy-perry'),
    'justin-trudeau',
  );

const mount = (client: StubClient, over: { scenario?: GuidedScenario; mediaId?: number | null } = {}) =>
  renderHook(() =>
    useGuidedLiveDescription({
      scenario: over.scenario ?? decidedScenario(),
      mediaId: over.mediaId === undefined ? MEDIA_ID : over.mediaId,
      client,
    }),
  );

/** Run a user gesture and flush the promises it starts. */
const press = async (gesture: () => void) => {
  await act(async () => {
    gesture();
    await vi.advanceTimersByTimeAsync(0);
  });
};

const settle = async (ms: number) => {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
};

describe('useGuidedLiveDescription', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.clearAllMocks();
  });

  describe('the gate', () => {
    it('starts blocked while no face has been decided and refuses to submit', async () => {
      const client = stubClient();
      const { result } = mount(client, { scenario: createGuidedScenario() });

      expect(result.current.state.status).toBe(GUIDED_LIVE_STATUS.BLOCKED);
      expect(result.current.canRequest).toBe(false);

      await press(() => result.current.request());

      expect(client.submit).not.toHaveBeenCalled();
      expect(result.current.state.status).toBe(GUIDED_LIVE_STATUS.BLOCKED);
    });

    it('stays blocked without a media id, because there is nothing live to describe', () => {
      const { result } = mount(stubClient(), { mediaId: null });

      expect(result.current.state.status).toBe(GUIDED_LIVE_STATUS.BLOCKED);
      expect(result.current.canRequest).toBe(false);
      expect(result.current.blockedReason).toBe('no_media');
    });

    it('stays blocked while one of two faces is still unanswered', () => {
      const { result } = mount(stubClient(), { scenario: halfDecidedScenario() });

      expect(result.current.state.status).toBe(GUIDED_LIVE_STATUS.BLOCKED);
      expect(result.current.blockedReason).toBe('no_faces_decided');
    });

    it('unblocks when every face is answered, even if none was confirmed', () => {
      const { result } = mount(stubClient(), { scenario: allUnidentifiedScenario() });

      expect(result.current.state.status).toBe(GUIDED_LIVE_STATUS.IDLE);
      expect(result.current.blockedReason).toBeNull();
      expect(result.current.canRequest).toBe(true);
    });

    it('unblocks once a face is decided and a media id exists', () => {
      const { result } = mount(stubClient());

      expect(result.current.state.status).toBe(GUIDED_LIVE_STATUS.IDLE);
      expect(result.current.canRequest).toBe(true);
      expect(result.current.blockedReason).toBeNull();
    });
  });

  describe('a run that works', () => {
    it('submits the media id alone and reports the phases it is told', async () => {
      const client = stubClient();
      const { result } = mount(client);

      await press(() => result.current.request());

      expect(client.submit).toHaveBeenCalledWith(MEDIA_ID);
      expect(result.current.state.runId).toBe('run-1');

      await settle(600);
      expect(result.current.state.status).toBe(GUIDED_LIVE_STATUS.WARMING);

      client.poll.mockResolvedValue(runResponse({ phase: 'describing', gpu_state: 'ready' }));
      await settle(1200);
      expect(result.current.state.status).toBe(GUIDED_LIVE_STATUS.DESCRIBING);
    });

    it('reads the finished text from the run items and lands ready', async () => {
      const client = stubClient({
        poll: vi.fn<GuidedLiveDescriptionClient['poll']>(() =>
          Promise.resolve(runResponse({ status: 'completed', phase: 'complete', gpu_state: 'ready' })),
        ),
      });
      const { result } = mount(client);

      await press(() => result.current.request());
      await settle(1000);

      expect(client.items).toHaveBeenCalledWith('run-1');
      expect(result.current.state.status).toBe(GUIDED_LIVE_STATUS.READY);
      expect(result.current.state.text).toBe('Katy Perry waves from the red carpet.');
    });

    it('calls the run degraded when the item came back on the CPU tier', async () => {
      const client = stubClient({
        poll: vi.fn<GuidedLiveDescriptionClient['poll']>(() =>
          Promise.resolve(runResponse({ status: 'completed', phase: 'complete', gpu_state: 'degraded' })),
        ),
        items: vi.fn<GuidedLiveDescriptionClient['items']>(() =>
          Promise.resolve(itemsResponse('A person on a red carpet.', 'provisional_cpu')),
        ),
      });
      const { result } = mount(client);

      await press(() => result.current.request());
      await settle(1000);

      expect(result.current.state.status).toBe(GUIDED_LIVE_STATUS.DEGRADED);
      expect(result.current.state.reason).toBe('cpu_fallback');
    });

    it('takes the warm ceiling when the GPU is already up, the cold one otherwise', async () => {
      const warm = stubClient({
        submit: vi.fn<GuidedLiveDescriptionClient['submit']>(() =>
          Promise.resolve(runResponse({ gpu_state: 'ready' })),
        ),
      });
      const { result: warmResult } = mount(warm);
      await press(() => warmResult.current.request());
      expect(warmResult.current.state.deadlineMs).toBe(GUIDED_LIVE_WARM_CEILING_SECONDS * 1000);

      const cold = stubClient();
      const { result: coldResult } = mount(cold);
      await press(() => coldResult.current.request());
      expect(coldResult.current.state.deadlineMs).toBe(GUIDED_LIVE_WAIT_CEILING_SECONDS * 1000);
    });
  });

  describe('a run that does not', () => {
    it('reports an unavailable run when the submit itself fails', async () => {
      const client = stubClient({
        submit: vi.fn<GuidedLiveDescriptionClient['submit']>(() => Promise.reject(new Error('backend unreachable'))),
      });
      const { result } = mount(client);

      await press(() => result.current.request());

      expect(result.current.state.status).toBe(GUIDED_LIVE_STATUS.UNAVAILABLE);
      expect(result.current.state.reason).toBe('submit_failed');
    });

    it('times out at the ceiling and never retries on its own', async () => {
      const client = stubClient();
      const { result } = mount(client);

      await press(() => result.current.request());
      await settle(GUIDED_LIVE_WAIT_CEILING_SECONDS * 1000 + 2000);

      expect(result.current.state.status).toBe(GUIDED_LIVE_STATUS.TIMED_OUT);
      expect(client.submit).toHaveBeenCalledTimes(1);
    });

    it('stops polling once the wait is over', async () => {
      const client = stubClient();
      const { result } = mount(client);

      await press(() => result.current.request());
      await settle(GUIDED_LIVE_WAIT_CEILING_SECONDS * 1000 + 2000);
      const pollsAtTimeout = client.poll.mock.calls.length;

      await settle(30_000);
      expect(client.poll.mock.calls.length).toBe(pollsAtTimeout);
    });

    it('cancels the server run and lands cancelled', async () => {
      const client = stubClient();
      const { result } = mount(client);

      await press(() => result.current.request());
      await settle(600);
      await press(() => result.current.cancel());

      expect(client.cancel).toHaveBeenCalledWith('run-1');
      expect(result.current.state.status).toBe(GUIDED_LIVE_STATUS.CANCELLED);
    });

    it('still lands cancelled locally when the cancel call fails', async () => {
      const client = stubClient({
        cancel: vi.fn<GuidedLiveDescriptionClient['cancel']>(() => Promise.reject(new Error('nope'))),
      });
      const { result } = mount(client);

      await press(() => result.current.request());
      await settle(600);
      await press(() => result.current.cancel());

      expect(result.current.state.status).toBe(GUIDED_LIVE_STATUS.CANCELLED);
    });
  });

  describe('the poll chain', () => {
    it('keeps polling after the backoff grows past the tick interval', async () => {
      // Regression: the poll timer used to be keyed on elapsed time, so the 1s
      // tick cleared and re-armed it every second. Once the backoff exceeded
      // 1000ms the poll simply never fired and the run hung until the deadline.
      const client = stubClient();
      const { result } = mount(client);

      await press(() => result.current.request());
      await settle(60_000);

      // 500 + 1000 + 2000 + 4000 + 5000... -- far more than the ~1 poll the
      // torn-down timer managed before it stalled for good.
      expect(client.poll.mock.calls.length).toBeGreaterThan(8);
      expect(result.current.state.status).toBe(GUIDED_LIVE_STATUS.WARMING);
    });

    it('stops on a terminal run status even when the phase still reads running', async () => {
      const client = stubClient({
        poll: vi.fn<GuidedLiveDescriptionClient['poll']>(() =>
          Promise.resolve(runResponse({ status: 'completed_with_errors', phase: 'describing', gpu_state: 'ready' })),
        ),
      });
      const { result } = mount(client);

      await press(() => result.current.request());
      await settle(1000);

      expect(result.current.state.status).toBe(GUIDED_LIVE_STATUS.READY);
      expect(result.current.state.text).toBe('Katy Perry waves from the red carpet.');
    });

    it('gives the wait its cold budget back when a poll reveals a cold GPU', async () => {
      const client = stubClient({
        submit: vi.fn<GuidedLiveDescriptionClient['submit']>(() =>
          Promise.resolve(runResponse({ gpu_state: 'ready' })),
        ),
      });
      const { result } = mount(client);

      await press(() => result.current.request());
      expect(result.current.state.deadlineMs).toBe(GUIDED_LIVE_WARM_CEILING_SECONDS * 1000);

      await settle(1000);
      expect(result.current.state.deadlineMs).toBe(GUIDED_LIVE_WAIT_CEILING_SECONDS * 1000);
    });

    it('never shrinks the deadline once a poll has widened it', async () => {
      const client = stubClient();
      const { result } = mount(client);

      await press(() => result.current.request());
      client.poll.mockResolvedValue(runResponse({ phase: 'describing', gpu_state: 'ready' }));
      await settle(2000);

      expect(result.current.state.deadlineMs).toBe(GUIDED_LIVE_WAIT_CEILING_SECONDS * 1000);
    });

    it('says nothing rather than describing the wrong photo when the item is missing', async () => {
      const client = stubClient({
        poll: vi.fn<GuidedLiveDescriptionClient['poll']>(() =>
          Promise.resolve(runResponse({ status: 'completed', phase: 'complete', gpu_state: 'ready' })),
        ),
        items: vi.fn<GuidedLiveDescriptionClient['items']>(() =>
          Promise.resolve({
            run_id: 'run-1',
            items: [{ ...itemsResponse('Someone else entirely.').items[0], media_id: MEDIA_ID + 1 }],
          }),
        ),
      });
      const { result } = mount(client);

      await press(() => result.current.request());
      await settle(1000);

      expect(result.current.state.status).toBe(GUIDED_LIVE_STATUS.UNAVAILABLE);
      expect(result.current.state.reason).toBe('item_missing');
      expect(result.current.state.text).toBeNull();
    });

    it('retries a timeout but gives up on a hard poll failure', async () => {
      const transient = stubClient({
        poll: vi.fn<GuidedLiveDescriptionClient['poll']>(() =>
          Promise.reject(Object.assign(new Error('slow'), { name: 'TimeoutError' })),
        ),
      });
      const { result: transientResult } = mount(transient);
      await press(() => transientResult.current.request());
      await settle(4000);

      expect(transient.poll.mock.calls.length).toBeGreaterThan(1);
      expect(transientResult.current.state.status).toBe(GUIDED_LIVE_STATUS.QUEUED);

      const hard = stubClient({
        poll: vi.fn<GuidedLiveDescriptionClient['poll']>(() => Promise.reject(new Error('500 from the route'))),
      });
      const { result: hardResult } = mount(hard);
      await press(() => hardResult.current.request());
      await settle(1000);

      expect(hard.poll).toHaveBeenCalledTimes(1);
      expect(hardResult.current.state.status).toBe(GUIDED_LIVE_STATUS.UNAVAILABLE);
      expect(hardResult.current.state.reason).toBe('poll_failed');
    });

    it('cancels a run the learner stopped waiting for while the submit was in flight', async () => {
      let release: (run: DescribeRunResponse) => void = () => undefined;
      const client = stubClient({
        submit: vi.fn<GuidedLiveDescriptionClient['submit']>(
          () =>
            new Promise<DescribeRunResponse>((resolve) => {
              release = resolve;
            }),
        ),
      });
      const { result } = mount(client);

      await press(() => result.current.request());
      await press(() => result.current.cancel());
      expect(result.current.state.status).toBe(GUIDED_LIVE_STATUS.CANCELLED);

      await act(async () => {
        release(runResponse({ run_id: 'run-late' }));
        await vi.advanceTimersByTimeAsync(0);
      });

      // The burst is already running on the server; a cancel that never leaves
      // the browser leaves the GPU billing for a wait nobody is watching.
      expect(client.cancel).toHaveBeenCalledWith('run-late');
    });
  });

  describe('what it tells the learner about names', () => {
    it('says the names come from the roster, not from the request', () => {
      const { result } = mount(stubClient());

      expect(result.current.disclosure.namesTravelWithTheRequest).toBe(false);
      expect(result.current.disclosure.namingSource).toBe('roster');
      expect(result.current.disclosure.confirmedHere).toContain('Katy Perry');
    });
  });

  describe('re-opening a face mid-run', () => {
    it('stops the wait and cancels the run on the server', async () => {
      const client = stubClient();
      const { result, rerender } = renderHook(
        ({ scenario }: { scenario: GuidedScenario }) =>
          useGuidedLiveDescription({ scenario, mediaId: MEDIA_ID, client }),
        { initialProps: { scenario: decidedScenario() } },
      );

      await press(() => result.current.request());
      expect(result.current.state.runId).toBe('run-1');

      await act(async () => {
        rerender({ scenario: halfDecidedScenario() });
        await vi.advanceTimersByTimeAsync(0);
      });

      expect(result.current.state.status).toBe(GUIDED_LIVE_STATUS.BLOCKED);
      expect(result.current.canRequest).toBe(false);
      // The burst the run started keeps costing money until the server hears
      // about it, so the screen stopping is not enough on its own.
      expect(client.cancel).toHaveBeenCalledWith('run-1');
    });

    it('cancels a run whose id only arrives after the gate closed', async () => {
      // The gate can close while the submit is still on the wire. There is no
      // run id to cancel at that instant, but the server is about to hand one
      // back for a burst no panel owns any more.
      let handBackRunId: (run: DescribeRunResponse) => void = () => undefined;
      const client = stubClient({
        submit: vi.fn<GuidedLiveDescriptionClient['submit']>(
          () =>
            new Promise<DescribeRunResponse>((resolve) => {
              handBackRunId = resolve;
            }),
        ),
      });
      const { result, rerender } = renderHook(
        ({ scenario }: { scenario: GuidedScenario }) =>
          useGuidedLiveDescription({ scenario, mediaId: MEDIA_ID, client }),
        { initialProps: { scenario: decidedScenario() } },
      );

      await press(() => result.current.request());
      expect(client.submit).toHaveBeenCalledTimes(1);
      expect(result.current.state.runId).toBeNull();

      await act(async () => {
        rerender({ scenario: halfDecidedScenario() });
        await vi.advanceTimersByTimeAsync(0);
      });
      expect(result.current.state.status).toBe(GUIDED_LIVE_STATUS.BLOCKED);

      await act(async () => {
        handBackRunId(runResponse({ run_id: 'run-orphan' }));
        await vi.advanceTimersByTimeAsync(0);
      });

      expect(client.cancel).toHaveBeenCalledWith('run-orphan');
      expect(result.current.state.runId).toBeNull();
    });

    it('does not cancel anything when the gate closes with no run in flight', async () => {
      const client = stubClient();
      const { rerender } = renderHook(
        ({ scenario }: { scenario: GuidedScenario }) =>
          useGuidedLiveDescription({ scenario, mediaId: MEDIA_ID, client }),
        { initialProps: { scenario: decidedScenario() } },
      );

      await act(async () => {
        rerender({ scenario: halfDecidedScenario() });
        await vi.advanceTimersByTimeAsync(0);
      });

      expect(client.cancel).not.toHaveBeenCalled();
    });
  });

  describe('a run outlives no panel that owns it', () => {
    it('cancels an in-flight run when the panel unmounts', async () => {
      const client = stubClient();
      const { result, unmount } = mount(client);

      await press(() => result.current.request());
      expect(result.current.state.status).toBe(GUIDED_LIVE_STATUS.QUEUED);

      await act(async () => {
        unmount();
        await vi.advanceTimersByTimeAsync(0);
      });

      // Reset practice remounts the panel under a new key, so unmount -- not a
      // prop change -- is the only signal the burst has lost its owner.
      expect(client.cancel).toHaveBeenCalledWith('run-1');
    });

    it('cancels a run whose submit resolves after the panel is gone', async () => {
      let release: (run: DescribeRunResponse) => void = () => undefined;
      const client = stubClient({
        submit: vi.fn<GuidedLiveDescriptionClient['submit']>(
          () =>
            new Promise<DescribeRunResponse>((resolve) => {
              release = resolve;
            }),
        ),
      });
      const { result, unmount } = mount(client);

      await press(() => result.current.request());
      expect(client.submit).toHaveBeenCalledTimes(1);

      await act(async () => {
        unmount();
        await vi.advanceTimersByTimeAsync(0);
      });

      await act(async () => {
        release(runResponse({ run_id: 'run-late' }));
        await vi.advanceTimersByTimeAsync(0);
      });

      // The run exists on the server the moment submit resolves, whether or not
      // anything is left on screen to show it.
      expect(client.cancel).toHaveBeenCalledWith('run-late');
    });

    it('does not cancel anything when a panel with no run in flight unmounts', async () => {
      const client = stubClient();
      const { unmount } = mount(client);

      await act(async () => {
        unmount();
        await vi.advanceTimersByTimeAsync(0);
      });

      expect(client.cancel).not.toHaveBeenCalled();
    });

    it('does not cancel a run the server already finished when the learner asks for another', async () => {
      const client = stubClient({
        poll: vi.fn<GuidedLiveDescriptionClient['poll']>(() =>
          Promise.resolve(runResponse({ status: 'completed', phase: 'complete', gpu_state: 'ready', completed: 1 })),
        ),
      });
      const { result } = mount(client);

      await press(() => result.current.request());
      await settle(2000);
      expect(result.current.state.status).toBe(GUIDED_LIVE_STATUS.READY);

      await press(() => result.current.request());

      // Cancelling a finished run buys nothing and costs a request; only a run
      // the server may still be working on is worth stopping.
      expect(client.cancel).not.toHaveBeenCalled();
      expect(client.submit).toHaveBeenCalledTimes(2);
    });

    it('cancels the timed-out run before a retry starts a second one', async () => {
      const client = stubClient();
      const { result } = mount(client);

      await press(() => result.current.request());
      await settle(GUIDED_LIVE_WAIT_CEILING_SECONDS * 1000 + 1000);
      expect(result.current.state.status).toBe(GUIDED_LIVE_STATUS.TIMED_OUT);

      await press(() => result.current.request());

      // Timing out stops the screen, not the burst. Starting a second run while
      // the first may still be on a GPU is the one-live-run rule breaking.
      expect(client.cancel).toHaveBeenCalledWith('run-1');
      expect(client.submit).toHaveBeenCalledTimes(2);
    });
  });


  describe('a run the panel walks away from is still cancelled', () => {
    it('cancels the run when the service reports a phase this client cannot read', () => {
      // Giving up on an unreadable phase stops only the browser's polling. The
      // run keeps its place on the single-GPU pool unless someone says stop.
      const client = stubClient({
        poll: vi.fn<GuidedLiveDescriptionClient['poll']>(() =>
          Promise.resolve(runResponse({ status: 'running', phase: 'teleporting' as never })),
        ),
      });
      return (async () => {
        const { result } = mount(client);
        await press(() => result.current.request());
        await settle(2000);

        expect(result.current.state.status).toBe(GUIDED_LIVE_STATUS.UNAVAILABLE);
        expect(client.cancel).toHaveBeenCalledWith('run-1');
      })();
    });

    it('cancels the run when polling fails in a way waiting cannot heal', async () => {
      const client = stubClient({
        poll: vi.fn<GuidedLiveDescriptionClient['poll']>(() => Promise.reject(new Error('500 from the proxy'))),
      });
      const { result } = mount(client);
      await press(() => result.current.request());
      await settle(2000);

      expect(result.current.state.status).toBe(GUIDED_LIVE_STATUS.UNAVAILABLE);
      expect(client.cancel).toHaveBeenCalledWith('run-1');
    });
  });

  describe('one learner gesture never pays for two live runs', () => {
    it('waits for the cancel to be accepted before submitting the retry', async () => {
      // The service only REQUESTS cancellation; a worker observes it later. Firing
      // cancel and submit in the same tick means both runs can be live at once on
      // a pool that has room for one.
      let releaseCancel: () => void = () => undefined;
      const client = stubClient({
        cancel: vi.fn<GuidedLiveDescriptionClient['cancel']>(
          () => new Promise((resolve) => { releaseCancel = () => resolve(runResponse({ status: 'cancelled' })); }),
        ),
      });
      const { result } = mount(client);
      await press(() => result.current.request());
      await settle(0);
      await act(async () => {
        await vi.advanceTimersByTimeAsync(GUIDED_LIVE_WAIT_CEILING_SECONDS * 1000 + 1000);
      });
      expect(result.current.state.status).toBe(GUIDED_LIVE_STATUS.TIMED_OUT);
      expect(client.submit).toHaveBeenCalledTimes(1);

      await press(() => result.current.request());

      expect(client.cancel).toHaveBeenCalledWith('run-1');
      expect(client.submit).toHaveBeenCalledTimes(1);

      await act(async () => {
        releaseCancel();
        await vi.advanceTimersByTimeAsync(0);
      });

      expect(client.submit).toHaveBeenCalledTimes(2);
    });

    it('still retries when the cancel is refused, rather than stranding the learner', async () => {
      const client = stubClient({
        cancel: vi.fn<GuidedLiveDescriptionClient['cancel']>(() => Promise.reject(new Error('403 expired nonce'))),
      });
      const { result } = mount(client);
      await press(() => result.current.request());
      await act(async () => {
        await vi.advanceTimersByTimeAsync(GUIDED_LIVE_WAIT_CEILING_SECONDS * 1000 + 1000);
      });

      await press(() => result.current.request());

      expect(client.submit).toHaveBeenCalledTimes(2);
    });
  });

});
