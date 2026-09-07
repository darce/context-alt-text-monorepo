import { act, render, screen } from '@testing-library/react';
import React from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Mock } from 'vitest';

import type { DescribeRunItemsResponse, DescribeRunResponse } from '../../../api/describeApi';
import { GUIDED_LIVE_WAIT_CEILING_SECONDS } from '../../../guidedPrototype/liveDescription';
import {
  confirmGuidedIdentity,
  createGuidedScenario,
  leaveGuidedIdentityUnidentified,
} from '../../../guidedPrototype/state';
import type { GuidedScenario } from '../../../guidedPrototype/state';
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
const decided = (): GuidedScenario =>
  leaveGuidedIdentityUnidentified(confirmGuidedIdentity(createGuidedScenario(), 'katy-perry'), 'justin-trudeau');

const mount = (client: StubClient, over: { scenario?: GuidedScenario; mediaId?: number | null } = {}) =>
  render(
    <GuidedLiveDescriptionPanel
      scenario={over.scenario ?? decided()}
      mediaId={over.mediaId === undefined ? MEDIA_ID : over.mediaId}
      client={client}
    />,
  );

const runButton = () => screen.getByRole('button', { name: /describe it live/i });

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

  describe('what it refuses to offer', () => {
    it('explains the decision order rather than disabling the button silently', () => {
      mount(stubClient(), { scenario: createGuidedScenario() });

      expect(runButton()).toBeDisabled();
      expect(screen.getByTestId('guided-live-status')).toHaveTextContent(/decide each face match first/i);
    });

    // rg-003: the run does not need the face decisions -- the panel says so two
    // lines up ("Names come from your roster on the server, not from this
    // page"). A gate whose copy reads as a data dependency teaches the wrong
    // model of what the server requires, so the line names the real reason.
    it("says the decision order is the lesson's, not something the run needs", () => {
      mount(stubClient(), { scenario: createGuidedScenario() });

      expect(screen.getByTestId('guided-live-status')).toHaveTextContent(
        "Decide each face match first, then you can describe this photo live. That is the lesson's order, not something the run needs.",
      );
    });

    it('names the missing configuration when the demo has no live photo', () => {
      mount(stubClient(), { mediaId: null });

      expect(runButton()).toBeDisabled();
      expect(screen.getByTestId('guided-live-status')).toHaveTextContent(/no live photo is configured/i);
    });
  });

  describe('the wait', () => {
    it('announces each phase in a polite live region', async () => {
      const client = stubClient();
      mount(client);

      // The live region wraps BOTH the status line and the result sentence, and
      // is mounted for the panel's whole life -- a region that appears at the
      // same moment as its content announces nothing.
      const region = screen.getByRole('status', { name: 'Live run status' });
      expect(region).toHaveAttribute('aria-live', 'polite');
      expect(region).toContainElement(screen.getByTestId('guided-live-status'));

      await press(runButton());
      await settle(600);

      expect(region).toHaveTextContent(/starting the gpu/i);
    });

    it('announces the finished sentence from inside the same live region', async () => {
      const client = stubClient({
        poll: vi.fn<GuidedLiveDescriptionClient['poll']>(() =>
          Promise.resolve(runResponse({ status: 'completed', phase: 'complete', gpu_state: 'ready' })),
        ),
      });
      mount(client);
      const region = screen.getByRole('status', { name: 'Live run status' });

      await press(runButton());
      await settle(1000);

      expect(region).toContainElement(screen.getByTestId('guided-live-text'));
    });

    it('points a disabled run button at the reason it is disabled', () => {
      mount(stubClient(), { mediaId: null });

      const described = runButton().getAttribute('aria-describedby');
      expect(described).toBe(screen.getByTestId('guided-live-status').id);
      expect(screen.getByTestId('guided-live-status')).toHaveTextContent(/no live photo is configured/i);
    });

    it('shows elapsed time against the ceiling it will not exceed', async () => {
      mount(stubClient());

      await press(runButton());
      await settle(65_000);

      // 11:30 is warm-up (8:30) plus generation (3:00) -- the same total the WP
      // proxy discloses in public_deadline_seconds(). The panel used to show
      // 8:30, the warm-up leg alone, and stop before the run could finish.
      expect(screen.getByTestId('guided-live-elapsed')).toHaveTextContent('1:05 of up to 11:30');
    });

    it('says whose budget the ceiling is when the server disclosed none', async () => {
      mount(stubClient());

      await press(runButton());
      await settle(1000);

      expect(screen.getByTestId('guided-live-budget')).toHaveTextContent(/no server budget disclosed/i);
    });

    it('credits the server for the ceiling once it has disclosed one', async () => {
      const client = stubClient({
        submit: vi.fn<GuidedLiveDescriptionClient['submit']>(() =>
          Promise.resolve({ ...runResponse({ gpu_state: 'ready' }), deadline_seconds: 120 }),
        ),
        poll: vi.fn<GuidedLiveDescriptionClient['poll']>(() =>
          Promise.resolve(runResponse({ phase: 'warming', gpu_state: 'ready' })),
        ),
      });
      mount(client);

      await press(runButton());
      await settle(1000);

      expect(screen.getByTestId('guided-live-budget')).toHaveTextContent(/the service disclosed/i);
    });

    it('offers a way to stop and takes it', async () => {
      const client = stubClient();
      mount(client);

      await press(runButton());
      await settle(600);
      await press(screen.getByRole('button', { name: /stop waiting/i }));

      expect(client.cancel).toHaveBeenCalledWith('run-1');
      expect(screen.getByTestId('guided-live-status')).toHaveTextContent(/you stopped the wait/i);
    });

    it('says nothing was applied when it stops at the ceiling', async () => {
      mount(stubClient());

      await press(runButton());
      await settle(GUIDED_LIVE_WAIT_CEILING_SECONDS * 1000 + 2000);

      expect(screen.getByTestId('guided-live-status')).toHaveTextContent(/stopped waiting/i);
      expect(screen.getByTestId('guided-live-status')).toHaveTextContent(/nothing was applied/i);
    });
  });

  describe('when the panel stops waiting on a run that may still be running', () => {
    const timeOut = async (client: StubClient) => {
      mount(client);
      await press(runButton());
      await settle(GUIDED_LIVE_WAIT_CEILING_SECONDS * 1000 + 2000);
    };

    // INT-08: a wait longer than a couple of seconds that is interruptible must
    // offer a side-effect-free way out. Before this, the only exit from a
    // timed-out panel was a full restart that discarded a run the backend was
    // still completing and paid for a second burst.
    it('offers keeping the wait as well as starting over', async () => {
      await timeOut(stubClient());

      expect(screen.getByRole('button', { name: /keep waiting/i })).toBeEnabled();
      expect(screen.getByRole('button', { name: /start over/i })).toBeEnabled();
    });

    it('keeps waiting on the same run rather than submitting a second one', async () => {
      const client = stubClient();
      await timeOut(client);

      await press(screen.getByRole('button', { name: /keep waiting/i }));
      await settle(2000);

      expect(client.submit).toHaveBeenCalledTimes(1);
      expect(client.cancel).not.toHaveBeenCalled();
      expect(screen.getByTestId('guided-live-status')).not.toHaveTextContent(/stopped waiting/i);
      expect(screen.getByTestId('guided-live-elapsed')).toBeInTheDocument();
    });

    it('names both ways out in the live region, not only in the buttons', async () => {
      await timeOut(stubClient());

      const region = screen.getByRole('status', { name: 'Live run status' });
      expect(region).toHaveTextContent(/keep waiting, or start over/i);
      expect(region).toHaveTextContent(/the run may still finish on its own/i);
    });

    it('does not offer to keep waiting when the run itself failed', async () => {
      const client = stubClient({
        poll: vi.fn<GuidedLiveDescriptionClient['poll']>(() =>
          Promise.resolve(runResponse({ status: 'failed', phase: 'failed' })),
        ),
      });
      mount(client);
      await press(runButton());
      await settle(1000);

      expect(screen.queryByRole('button', { name: /keep waiting/i })).toBeNull();
      expect(runButton()).toBeEnabled();
    });
  });

  describe('the result', () => {
    it('shows the live sentence and says the GPU produced it', async () => {
      const client = stubClient({
        poll: vi.fn<GuidedLiveDescriptionClient['poll']>(() =>
          Promise.resolve(runResponse({ status: 'completed', phase: 'complete', gpu_state: 'ready' })),
        ),
      });
      mount(client);

      await press(runButton());
      await settle(1000);

      expect(screen.getByTestId('guided-live-text')).toHaveTextContent('Katy Perry waves from the red carpet.');
      expect(screen.getByTestId('guided-live-status')).toHaveTextContent(/gpu/i);
    });

    it('labels a CPU-tier result as the slower option without naming its model or vendor', async () => {
      const client = stubClient({
        poll: vi.fn<GuidedLiveDescriptionClient['poll']>(() =>
          Promise.resolve(runResponse({ status: 'completed', phase: 'complete', gpu_state: 'degraded' })),
        ),
        items: vi.fn<GuidedLiveDescriptionClient['items']>(() =>
          Promise.resolve(itemsResponse('A person on a red carpet.', 'provisional_cpu')),
        ),
      });
      mount(client);

      await press(runButton());
      await settle(1000);

      expect(screen.getByTestId('guided-live-text')).toHaveTextContent('A person on a red carpet.');
      const status = screen.getByTestId('guided-live-status');
      expect(status).toHaveTextContent(
        'Done. This ran on the slower CPU option, which writes rougher text than the GPU.',
      );
      expect(status).not.toHaveTextContent(/florence|microsoft|local vlm|\b\d+(?:\.\d+)?\s*(?:m|b|million|billion)\b/i);
    });

    it('will not name an engine the run did not report, and still shows the text', async () => {
      const client = stubClient({
        poll: vi.fn<GuidedLiveDescriptionClient['poll']>(() =>
          // A ready gpu_state is a lifecycle snapshot, not proof of authorship.
          Promise.resolve(runResponse({ status: 'completed', phase: 'complete', gpu_state: 'ready' })),
        ),
        items: vi.fn<GuidedLiveDescriptionClient['items']>(() =>
          Promise.resolve(itemsResponse('A person on a red carpet.', null)),
        ),
      });
      mount(client);

      await press(runButton());
      await settle(1000);

      const status = screen.getByTestId('guided-live-status');
      expect(screen.getByTestId('guided-live-text')).toHaveTextContent('A person on a red carpet.');
      expect(status).toHaveTextContent('Done, but the run did not say whether the GPU wrote this.');
      expect(status).not.toHaveTextContent('The GPU wrote this.');
      expect(status).not.toHaveTextContent(/cpu/i);
    });

    it('says a run that finished with nothing to show finished with nothing to show', async () => {
      const client = stubClient({
        poll: vi.fn<GuidedLiveDescriptionClient['poll']>(() =>
          Promise.resolve(runResponse({ status: 'completed', phase: 'complete', gpu_state: 'ready' })),
        ),
        items: vi.fn<GuidedLiveDescriptionClient['items']>(() => Promise.resolve(itemsResponse('   '))),
      });
      mount(client);

      await press(runButton());
      await settle(1000);

      // An empty draft is the silent failure this panel exists to name; the
      // generic could-not-finish line would hide which of the two happened.
      const status = screen.getByTestId('guided-live-status');
      expect(status).toHaveTextContent('The run finished with nothing to show. Nothing was applied.');
      expect(status).not.toHaveTextContent('The live run could not finish.');
      expect(screen.queryByTestId('guided-live-text')).toBeNull();
    });

    it('says the run could not finish when it failed for any other reason', async () => {
      const client = stubClient({
        poll: vi.fn<GuidedLiveDescriptionClient['poll']>(() =>
          Promise.resolve(runResponse({ status: 'failed', phase: 'failed' })),
        ),
      });
      mount(client);

      await press(runButton());
      await settle(1000);

      const status = screen.getByTestId('guided-live-status');
      expect(status).toHaveTextContent('The live run could not finish. Nothing was applied.');
      expect(status).not.toHaveTextContent('nothing to show');
    });

    it('stops rather than polls on a phase this client does not know', async () => {
      const client = stubClient({
        poll: vi.fn<GuidedLiveDescriptionClient['poll']>(() =>
          Promise.resolve(runResponse({ phase: 'reticulating' as DescribeRunResponse['phase'] })),
        ),
      });
      mount(client);

      await press(runButton());
      await settle(2000);

      // Reading an unknown phase as queued polled a finished run all the way to
      // its deadline and then reported a timeout that never happened.
      expect(screen.getByTestId('guided-live-status')).toHaveTextContent(
        'The live run could not finish. Nothing was applied.',
      );
    });

    it('pairs every status with an icon, never colour alone', async () => {
      const client = stubClient({
        poll: vi.fn<GuidedLiveDescriptionClient['poll']>(() =>
          Promise.resolve(runResponse({ status: 'completed', phase: 'complete', gpu_state: 'ready' })),
        ),
      });
      mount(client);

      await press(runButton());
      await settle(1000);

      const icon = screen.getByTestId('guided-live-icon');
      expect(icon).toHaveAttribute('aria-hidden', 'true');
      expect(icon.textContent?.trim()).not.toBe('');
    });
  });

  describe('what it promises the learner', () => {
    it('says a live run never touches the saved draft', () => {
      mount(stubClient());

      expect(screen.getByTestId('guided-live-additive')).toHaveTextContent(/never changes the draft/i);
    });

    it('says the names come from the roster and lists the ones confirmed here', () => {
      mount(stubClient());

      const naming = screen.getByTestId('guided-live-naming');
      expect(naming).toHaveTextContent(/roster/i);
      expect(naming).toHaveTextContent('Katy Perry');
    });
  });

  describe('who stopped the run', () => {
    it('does not blame the learner when the service cancelled the run', async () => {
      // RUN_CANCELLED and STOPPED_BY_OPERATOR are separate reasons for a reason:
      // another tab, an operator, or the service itself can end a run. Telling
      // this learner "You stopped the wait" is a false account of what happened.
      const client = stubClient({
        poll: vi.fn<GuidedLiveDescriptionClient['poll']>(() =>
          Promise.resolve(runResponse({ status: 'cancelled', phase: 'cancelled' })),
        ),
      });
      mount(client);
      await press(runButton());
      await settle(2000);

      const line = screen.getByTestId('guided-live-status').textContent ?? '';
      expect(line).toContain('The run was cancelled');
      expect(line).not.toContain('You stopped');
    });
  });
});
