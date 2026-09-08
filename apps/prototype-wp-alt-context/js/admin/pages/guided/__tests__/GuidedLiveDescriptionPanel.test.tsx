import { act, render, screen } from '@testing-library/react';
import React from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Mock } from 'vitest';

import type { DescribeRunItemsResponse, DescribeRunResponse } from '../../../api/describeApi';
import { guidedCopy } from '../../../guidedPrototype/copy';
import { GUIDED_LIVE_WAIT_CEILING_SECONDS } from '../../../guidedPrototype/liveDescription';
import type { GuidedLiveDescriptionClient } from '../../../guidedPrototype/useGuidedLiveDescription';
import { GuidedLiveDescriptionPanel } from '../GuidedLiveDescriptionPanel';

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

type ClientOp = keyof GuidedLiveDescriptionClient;

type RecordingClient = {
  [K in ClientOp]: Mock<GuidedLiveDescriptionClient[K]>;
} & {
  calls: Array<{ op: ClientOp; args: unknown[] }>;
};

const stubClient = (
  over: Partial<{ [K in ClientOp]: GuidedLiveDescriptionClient[K] }> = {},
): RecordingClient => {
  const calls: RecordingClient['calls'] = [];
  const record =
    <K extends ClientOp>(op: K, impl: GuidedLiveDescriptionClient[K]): Mock<GuidedLiveDescriptionClient[K]> =>
      vi.fn<GuidedLiveDescriptionClient[K]>((...args: Parameters<GuidedLiveDescriptionClient[K]>) => {
        calls.push({ op, args: [...args] });
        return impl(...args);
      });

  return {
    calls,
    submit: record('submit', over.submit ?? (() => Promise.resolve(runResponse()))),
    poll: record(
      'poll',
      over.poll ?? (() => Promise.resolve(runResponse({ phase: 'warming', gpu_state: 'starting' }))),
    ),
    items: record(
      'items',
      over.items ?? (() => Promise.resolve(itemsResponse('Katy Perry waves from the red carpet.'))),
    ),
    cancel: record(
      'cancel',
      over.cancel ?? (() => Promise.resolve(runResponse({ status: 'cancelled', phase: 'cancelled' }))),
    ),
  };
};

const mount = (
  client: RecordingClient,
  over: {
    mediaId?: number | null;
    onWaitingChange?: (waiting: boolean) => void;
    key?: React.Key;
  } = {},
) =>
  render(
    <GuidedLiveDescriptionPanel
      key={over.key}
      mediaId={over.mediaId === undefined ? MEDIA_ID : over.mediaId}
      client={client}
      onWaitingChange={over.onWaitingChange}
    />,
  );

const submitButton = () => screen.getByRole('button', { name: guidedCopy('live.submit') });
const retryButton = () => screen.getByRole('button', { name: guidedCopy('live.retry') });

const press = async (button: HTMLElement) => {
  await act(async () => {
    button.click();
    await vi.advanceTimersByTimeAsync(0);
  });
};

const settle = async (ms: number) => {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
};

describe('GuidedLiveDescriptionPanel', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.clearAllMocks();
  });

  describe('T14 live panel is optional and inert when opened', () => {
    it('is a closed details disclosure and starts no request until the action is pressed', async () => {
      const client = stubClient();
      mount(client);

      const panel = screen.getByTestId('guided-live');
      expect(panel.tagName).toBe('DETAILS');
      expect(panel).not.toHaveAttribute('open');
      expect(screen.getByText(guidedCopy('live.title'))).toBeInTheDocument();
      expect(screen.getAllByText(guidedCopy('live.intro')).length).toBeGreaterThan(0);
      expect(screen.getByTestId('guided-live-naming')).toHaveTextContent(guidedCopy('live.names'));

      await act(async () => {
        screen.getByText(guidedCopy('live.title')).click();
      });

      expect(client.submit).not.toHaveBeenCalled();
      expect(client.calls).toEqual([]);
      expect(submitButton()).toBeEnabled();
    });

    it('does not gate availability on face choices', () => {
      mount(stubClient());

      expect(submitButton()).toBeEnabled();
      expect(screen.getByTestId('guided-live-status')).not.toHaveTextContent(/decide each face match first/i);
    });
  });

  describe('T23 live network contract gate', () => {
    it('renders live.request_unverified and disables the action when not verified', () => {
      const client = stubClient();
      mount(client, { mediaId: null });

      expect(submitButton()).toBeDisabled();
      expect(screen.getByTestId('guided-live-status')).toHaveTextContent(guidedCopy('live.request_unverified'));
      expect(submitButton().getAttribute('aria-describedby')).toBe(screen.getByTestId('guided-live-status').id);
    });
  });

  describe('T15 T18 live request is isolated', () => {
    it('sends the media id only and never calls apply or a roster write', async () => {
      const client = stubClient({
        poll: () => Promise.resolve(runResponse({ status: 'completed', phase: 'complete', gpu_state: 'ready' })),
      });
      mount(client);

      expect(screen.getAllByText(guidedCopy('live.request_confirmed')).length).toBeGreaterThan(0);
      expect(screen.getByText(guidedCopy('live.details'))).toBeInTheDocument();
      expect(screen.getByTestId('guided-live-payload')).toHaveTextContent(String(MEDIA_ID));

      await press(submitButton());
      await settle(1000);

      expect(client.submit).toHaveBeenCalledTimes(1);
      expect(client.submit).toHaveBeenCalledWith(MEDIA_ID);
      expect(client.submit.mock.calls[0]).toEqual([MEDIA_ID]);
      expect(client.calls.map((entry) => entry.op)).toEqual(expect.arrayContaining(['submit', 'poll', 'items']));
      expect(client.calls.every((entry) => entry.op === 'submit' || entry.op === 'poll' || entry.op === 'items')).toBe(
        true,
      );
      expect(screen.getByTestId('guided-live-text')).toHaveTextContent('Katy Perry waves from the red carpet.');
      expect(screen.getAllByText(guidedCopy('live.output_label')).length).toBeGreaterThan(0);
    });
  });

  describe('T16 pending, failure, empty, timeout, stop-waiting, retry', () => {
    it('announces pending from guidedCopy and disables a duplicate request', async () => {
      const client = stubClient();
      mount(client);

      const region = screen.getByRole('status', { name: 'Live run status' });
      expect(region).toHaveAttribute('aria-live', 'polite');

      await press(submitButton());
      await settle(600);

      expect(screen.getByTestId('guided-live-status')).toHaveTextContent(guidedCopy('live.pending'));
      expect(submitButton()).toBeDisabled();
      expect(screen.getByRole('button', { name: guidedCopy('live.stop_waiting') })).toBeEnabled();
    });

    it('shows elapsed time against the ceiling it will not exceed', async () => {
      mount(stubClient());

      await press(submitButton());
      await settle(65_000);

      expect(screen.getByTestId('guided-live-elapsed')).toHaveTextContent('1:05 of up to 11:30');
    });

    it('says whose budget the ceiling is when the server disclosed none', async () => {
      mount(stubClient());

      await press(submitButton());
      await settle(1000);

      expect(screen.getByTestId('guided-live-budget')).toHaveTextContent(/no server budget disclosed/i);
    });

    it('credits the server for the ceiling once it has disclosed one', async () => {
      const client = stubClient({
        submit: () => Promise.resolve({ ...runResponse({ gpu_state: 'ready' }), deadline_seconds: 120 }),
        poll: () => Promise.resolve(runResponse({ phase: 'warming', gpu_state: 'ready' })),
      });
      mount(client);

      await press(submitButton());
      await settle(1000);

      expect(screen.getByTestId('guided-live-budget')).toHaveTextContent(/the service disclosed/i);
    });

    it('stops waiting with live.stopped and does not claim the server job stopped', async () => {
      const client = stubClient();
      mount(client);

      await press(submitButton());
      await settle(600);
      await press(screen.getByRole('button', { name: guidedCopy('live.stop_waiting') }));

      expect(client.cancel).toHaveBeenCalledWith('run-1');
      expect(screen.getByTestId('guided-live-status')).toHaveTextContent(guidedCopy('live.stopped'));
    });

    it('names a timeout without implying server cancellation', async () => {
      mount(stubClient());

      await press(submitButton());
      await settle(GUIDED_LIVE_WAIT_CEILING_SECONDS * 1000 + 2000);

      expect(screen.getByTestId('guided-live-status')).toHaveTextContent(guidedCopy('live.timed_out'));
      expect(screen.getByTestId('guided-live-status')).not.toHaveTextContent(/cancelled/i);
    });

    it('keeps waiting on the same run rather than submitting a second one', async () => {
      const client = stubClient();
      mount(client);
      await press(submitButton());
      await settle(GUIDED_LIVE_WAIT_CEILING_SECONDS * 1000 + 2000);

      expect(screen.getByRole('button', { name: /keep waiting/i })).toBeEnabled();
      await press(screen.getByRole('button', { name: /keep waiting/i }));
      await settle(2000);

      expect(client.submit).toHaveBeenCalledTimes(1);
      expect(client.cancel).not.toHaveBeenCalled();
      expect(screen.getByTestId('guided-live-elapsed')).toBeInTheDocument();
    });

    it('retries after failure with a new request token', async () => {
      const client = stubClient({
        poll: () => Promise.resolve(runResponse({ status: 'failed', phase: 'failed' })),
      });
      mount(client);

      await press(submitButton());
      await settle(1000);

      expect(screen.getByTestId('guided-live-status')).toHaveTextContent(guidedCopy('live.failed'));
      expect(retryButton()).toBeEnabled();

      await press(retryButton());
      expect(client.submit).toHaveBeenCalledTimes(2);
    });

    it('names an empty description with live.no_result', async () => {
      const client = stubClient({
        poll: () => Promise.resolve(runResponse({ status: 'completed', phase: 'complete', gpu_state: 'ready' })),
        items: () => Promise.resolve(itemsResponse('   ')),
      });
      mount(client);

      await press(submitButton());
      await settle(1000);

      expect(screen.getByTestId('guided-live-status')).toHaveTextContent(guidedCopy('live.no_result'));
      expect(screen.queryByTestId('guided-live-text')).toBeNull();
    });

    it('does not invent a percentage while pending', async () => {
      mount(stubClient());
      await press(submitButton());
      await settle(600);
      expect(screen.getByTestId('guided-live')).not.toHaveTextContent(/%/);
    });
  });

  describe('T17 reset and stale results', () => {
    it('ignores a stale poll after remount', async () => {
      let releaseItems: (items: DescribeRunItemsResponse) => void = () => undefined;
      const client = stubClient({
        poll: () => Promise.resolve(runResponse({ status: 'completed', phase: 'complete', gpu_state: 'ready' })),
        items: () =>
          new Promise<DescribeRunItemsResponse>((resolve) => {
            releaseItems = resolve;
          }),
      });
      const first = mount(client, { key: 'one' });

      await press(submitButton());
      await settle(600);
      first.unmount();

      mount(client, { key: 'two' });
      expect(screen.queryByTestId('guided-live-text')).toBeNull();
      expect(screen.getByTestId('guided-live-status')).toHaveTextContent(guidedCopy('live.request_confirmed'));

      await act(async () => {
        releaseItems(itemsResponse('A stale sentence from the previous panel.'));
        await vi.advanceTimersByTimeAsync(0);
      });

      expect(screen.queryByTestId('guided-live-text')).toBeNull();
      expect(screen.getByTestId('guided-live-status')).not.toHaveTextContent('A stale sentence from the previous panel.');
    });
  });

  describe('onWaitingChange', () => {
    it('fires true then false as the wait starts and ends', async () => {
      const seen: boolean[] = [];
      const client = stubClient({
        poll: () => Promise.resolve(runResponse({ status: 'completed', phase: 'complete', gpu_state: 'ready' })),
      });
      mount(client, { onWaitingChange: (waiting) => seen.push(waiting) });

      await press(submitButton());
      await settle(1000);

      expect(seen).toContain(true);
      expect(seen).toContain(false);
      expect(seen.indexOf(true)).toBeLessThan(seen.lastIndexOf(false));
    });
  });

  describe('the result', () => {
    it('shows the live sentence as read-only output', async () => {
      const client = stubClient({
        poll: () => Promise.resolve(runResponse({ status: 'completed', phase: 'complete', gpu_state: 'ready' })),
      });
      mount(client);

      await press(submitButton());
      await settle(1000);

      expect(screen.getByTestId('guided-live-text')).toHaveTextContent('Katy Perry waves from the red carpet.');
      expect(screen.getByTestId('guided-live-status')).toHaveTextContent(guidedCopy('live.complete'));
    });

    it('still shows CPU-tier text without claiming a GPU result', async () => {
      const client = stubClient({
        poll: () => Promise.resolve(runResponse({ status: 'completed', phase: 'complete', gpu_state: 'degraded' })),
        items: () => Promise.resolve(itemsResponse('A person on a red carpet.', 'provisional_cpu')),
      });
      mount(client);

      await press(submitButton());
      await settle(1000);

      expect(screen.getByTestId('guided-live-text')).toHaveTextContent('A person on a red carpet.');
      expect(screen.getByTestId('guided-live-status')).toHaveTextContent(guidedCopy('live.complete'));
      expect(screen.getByTestId('guided-live-status')).not.toHaveTextContent(
        /florence|microsoft|local vlm|\b\d+(?:\.\d+)?\s*(?:m|b|million|billion)\b/i,
      );
    });

    it('pairs every status with an icon, never colour alone', async () => {
      const client = stubClient({
        poll: () => Promise.resolve(runResponse({ status: 'completed', phase: 'complete', gpu_state: 'ready' })),
      });
      mount(client);

      await press(submitButton());
      await settle(1000);

      const icon = screen.getByTestId('guided-live-icon');
      expect(icon).toHaveAttribute('aria-hidden', 'true');
      expect(icon.textContent?.trim()).not.toBe('');
    });
  });
});
