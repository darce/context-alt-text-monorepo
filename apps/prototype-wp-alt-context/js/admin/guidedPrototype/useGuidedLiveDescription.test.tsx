import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Mock } from 'vitest';

import type { DescribeRunItemsResponse, DescribeRunResponse } from '../api/describeApi';
import { GUIDED_LIVE_STATUS, GUIDED_LIVE_WAIT_CEILING_SECONDS } from './liveDescription';
import { confirmGuidedIdentity, createGuidedScenario } from './state';
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

const decidedScenario = (): GuidedScenario => confirmGuidedIdentity(createGuidedScenario(), 'katy-perry');

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

  describe('what it tells the learner about names', () => {
    it('says the names come from the roster, not from the request', () => {
      const { result } = mount(stubClient());

      expect(result.current.disclosure.namesTravelWithTheRequest).toBe(false);
      expect(result.current.disclosure.namingSource).toBe('roster');
      expect(result.current.disclosure.confirmedHere).toContain('Katy Perry');
    });
  });
});
