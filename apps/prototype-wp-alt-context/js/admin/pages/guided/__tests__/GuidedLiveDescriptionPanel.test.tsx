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

      expect(screen.getByTestId('guided-live-elapsed')).toHaveTextContent('1:05 of up to 8:30');
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

    it('shows a CPU result as the rougher thing it is, and still shows it', async () => {
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
      expect(screen.getByTestId('guided-live-status')).toHaveTextContent(/cpu/i);
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
});
