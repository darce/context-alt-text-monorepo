import { describe, expect, it } from 'vitest';

import {
  GUIDED_LIVE_STATUS,
  GUIDED_LIVE_WAIT_CEILING_SECONDS,
  guidedLiveNamingDisclosure,
  guidedLiveRequestPayload,
  guidedLivePollDelayMs,
  guidedLiveReducer,
  initialGuidedLiveState,
} from './liveDescription';
import type { GuidedLiveState } from './liveDescription';
import { GUIDED_IDENTITY_STATUS, confirmGuidedIdentity, createGuidedScenario } from './state';

const T0 = 1_000_000;

const decided = (state: GuidedLiveState): GuidedLiveState =>
  guidedLiveReducer(state, { kind: 'faces_decided', decided: true });

const started = (): GuidedLiveState => {
  let state = decided(initialGuidedLiveState());
  state = guidedLiveReducer(state, { kind: 'requested', atMs: T0 });
  return guidedLiveReducer(state, { kind: 'accepted', runId: 'run-1', deadlineSeconds: 300, atMs: T0 });
};

describe('guided live description gate', () => {
  it('blocks a live run until every face has been decided', () => {
    const state = guidedLiveReducer(initialGuidedLiveState(), { kind: 'faces_decided', decided: false });
    expect(state.status).toBe(GUIDED_LIVE_STATUS.BLOCKED);
  });

  it('refuses a request while blocked so the model text cannot precede the human decision', () => {
    const blocked = guidedLiveReducer(initialGuidedLiveState(), { kind: 'faces_decided', decided: false });
    const after = guidedLiveReducer(blocked, { kind: 'requested', atMs: T0 });
    expect(after.status).toBe(GUIDED_LIVE_STATUS.BLOCKED);
    expect(after.runId).toBeNull();
  });

  it('opens the run once the faces are decided', () => {
    expect(decided(initialGuidedLiveState()).status).toBe(GUIDED_LIVE_STATUS.IDLE);
    expect(guidedLiveReducer(decided(initialGuidedLiveState()), { kind: 'requested', atMs: T0 }).status).toBe(
      GUIDED_LIVE_STATUS.QUEUED,
    );
  });
});

describe('guided live description bounds', () => {
  it('clamps an over-long server deadline to the client ceiling', () => {
    let state = decided(initialGuidedLiveState());
    state = guidedLiveReducer(state, { kind: 'requested', atMs: T0 });
    state = guidedLiveReducer(state, { kind: 'accepted', runId: 'run-1', deadlineSeconds: 9999, atMs: T0 });
    expect(state.deadlineMs).toBe(GUIDED_LIVE_WAIT_CEILING_SECONDS * 1000);
  });

  it('keeps a server deadline shorter than the ceiling', () => {
    const state = started();
    expect(state.deadlineMs).toBe(300_000);
  });

  it('stops waiting at the deadline and does not retry on its own', () => {
    let state = started();
    state = guidedLiveReducer(state, { kind: 'tick', atMs: T0 + 300_000 });
    expect(state.status).toBe(GUIDED_LIVE_STATUS.TIMED_OUT);

    const late = guidedLiveReducer(state, {
      kind: 'polled',
      phase: 'complete',
      gpu: 'ready',
      atMs: T0 + 301_000,
      text: 'arrived too late',
    });
    expect(late.status).toBe(GUIDED_LIVE_STATUS.TIMED_OUT);
    expect(late.text).toBeNull();
  });

  it('backs off from 500ms to a 5s ceiling', () => {
    expect(guidedLivePollDelayMs(0)).toBe(500);
    expect(guidedLivePollDelayMs(1)).toBe(1000);
    expect(guidedLivePollDelayMs(2)).toBe(2000);
    expect(guidedLivePollDelayMs(3)).toBe(4000);
    expect(guidedLivePollDelayMs(4)).toBe(5000);
    expect(guidedLivePollDelayMs(40)).toBe(5000);
  });
});

describe('guided live description phases', () => {
  it('reports warming and describing as the run progresses', () => {
    let state = started();
    state = guidedLiveReducer(state, { kind: 'polled', phase: 'warming', gpu: 'starting', atMs: T0 + 1000 });
    expect(state.status).toBe(GUIDED_LIVE_STATUS.WARMING);
    state = guidedLiveReducer(state, { kind: 'polled', phase: 'describing', gpu: 'ready', atMs: T0 + 2000 });
    expect(state.status).toBe(GUIDED_LIVE_STATUS.DESCRIBING);
  });

  it('never moves a phase backwards when a poll arrives out of order', () => {
    let state = started();
    state = guidedLiveReducer(state, { kind: 'polled', phase: 'describing', gpu: 'ready', atMs: T0 + 2000 });
    state = guidedLiveReducer(state, { kind: 'polled', phase: 'queued', gpu: 'ready', atMs: T0 + 2500 });
    expect(state.status).toBe(GUIDED_LIVE_STATUS.DESCRIBING);
  });

  it('tracks elapsed time from the request', () => {
    let state = started();
    state = guidedLiveReducer(state, { kind: 'tick', atMs: T0 + 12_000 });
    expect(state.elapsedMs).toBe(12_000);
  });
});

describe('guided live description terminal states', () => {
  it('carries the live text through on a warm completion', () => {
    let state = started();
    state = guidedLiveReducer(state, {
      kind: 'polled',
      phase: 'complete',
      gpu: 'ready',
      tier: 'final_gpu',
      atMs: T0 + 5000,
      text: 'Two people shake hands at a podium.',
    });
    expect(state.status).toBe(GUIDED_LIVE_STATUS.READY);
    expect(state.reason).toBeNull();
    expect(state.text).toBe('Two people shake hands at a podium.');
  });

  it('marks a completion that ran without the GPU as degraded, not as a plain success', () => {
    let state = started();
    state = guidedLiveReducer(state, {
      kind: 'polled',
      phase: 'complete',
      gpu: 'degraded',
      tier: 'provisional_cpu',
      atMs: T0 + 5000,
      text: 'A shorter description.',
    });
    expect(state.status).toBe(GUIDED_LIVE_STATUS.DEGRADED);
    expect(state.reason).toBe('cpu_fallback');
    expect(state.text).toBe('A shorter description.');
  });

  // gpu_state is a lifecycle snapshot that may be stale by the time the item
  // lands, so it can never stand in for the tier as proof of authorship.
  it.each(['ready', 'unknown', 'stopped', 'degraded'] as const)(
    'refuses to claim a tierless completion for the GPU when gpu_state is %s',
    (gpu) => {
      let state = started();
      state = guidedLiveReducer(state, {
        kind: 'polled',
        phase: 'complete',
        gpu,
        atMs: T0 + 5000,
        text: 'A description of unknown origin.',
      });
      expect(state.status).toBe(GUIDED_LIVE_STATUS.DEGRADED);
      expect(state.reason).toBe('tier_unreported');
      expect(state.text).toBe('A description of unknown origin.');
    },
  );

  it('does not let a ready gpu_state override a cpu tier', () => {
    let state = started();
    state = guidedLiveReducer(state, {
      kind: 'polled',
      phase: 'complete',
      gpu: 'ready',
      tier: 'provisional_cpu',
      atMs: T0 + 5000,
      text: 'A shorter description.',
    });
    expect(state.status).toBe(GUIDED_LIVE_STATUS.DEGRADED);
    expect(state.reason).toBe('cpu_fallback');
  });

  // A run in flight was started against an identity answer that no longer
  // holds, so re-opening a face must stop the wait rather than let a poll land
  // a sentence into a blocked panel.
  it('fences a run still in flight when a face is re-opened', () => {
    let state = started();
    state = guidedLiveReducer(state, { kind: 'accepted', runId: 'run-1', deadlineSeconds: 510, atMs: T0 + 100 });
    expect(state.runId).toBe('run-1');

    state = guidedLiveReducer(state, { kind: 'faces_decided', decided: false });

    expect(state.status).toBe(GUIDED_LIVE_STATUS.BLOCKED);
    expect(state.runId).toBeNull();
    expect(state.text).toBeNull();
    expect(state.reason).toBeNull();
  });

  it('ignores a poll that lands after the gate closed', () => {
    let state = started();
    state = guidedLiveReducer(state, { kind: 'faces_decided', decided: false });
    state = guidedLiveReducer(state, {
      kind: 'polled',
      phase: 'complete',
      gpu: 'ready',
      tier: 'final_gpu',
      atMs: T0 + 5000,
      text: 'A sentence written against a stale answer.',
    });

    expect(state.status).toBe(GUIDED_LIVE_STATUS.BLOCKED);
    expect(state.text).toBeNull();
  });

  it('treats a completion with no description as a failure rather than an empty success', () => {
    let state = started();
    state = guidedLiveReducer(state, { kind: 'polled', phase: 'complete', gpu: 'ready', atMs: T0 + 5000, text: '' });
    expect(state.status).toBe(GUIDED_LIVE_STATUS.UNAVAILABLE);
    expect(state.reason).toBe('empty_description');
    expect(state.text).toBeNull();
  });

  it('reports a failed phase as unavailable and keeps the reason', () => {
    let state = started();
    state = guidedLiveReducer(state, {
      kind: 'polled',
      phase: 'failed',
      gpu: 'unknown',
      atMs: T0 + 5000,
      reason: 'backend_unreachable',
    });
    expect(state.status).toBe(GUIDED_LIVE_STATUS.UNAVAILABLE);
    expect(state.reason).toBe('backend_unreachable');
    expect(state.text).toBeNull();
  });

  it('stops on cancel and ignores every later poll', () => {
    let state = started();
    state = guidedLiveReducer(state, { kind: 'cancelled' });
    expect(state.status).toBe(GUIDED_LIVE_STATUS.CANCELLED);
    state = guidedLiveReducer(state, { kind: 'polled', phase: 'complete', gpu: 'ready', atMs: T0 + 9000, text: 'late' });
    expect(state.status).toBe(GUIDED_LIVE_STATUS.CANCELLED);
    expect(state.text).toBeNull();
  });

  it('clears the previous live text when the learner asks for another run', () => {
    let state = started();
    state = guidedLiveReducer(state, { kind: 'polled', phase: 'complete', gpu: 'ready', atMs: T0 + 5000, text: 'first' });
    state = guidedLiveReducer(state, { kind: 'requested', atMs: T0 + 60_000 });
    expect(state.status).toBe(GUIDED_LIVE_STATUS.QUEUED);
    expect(state.text).toBeNull();
    expect(state.elapsedMs).toBe(0);
  });

  it('holds no live text in any state that is not ready or degraded', () => {
    // The old version of this test asserted that a hand-written list of status
    // constants did not contain READY, which is true of the literal and says
    // nothing about the reducer. Drive the machine into each state instead --
    // every one of them reached from a READY state that DOES hold text, so a
    // reducer that forgot to clear it fails here (S1-B-10).
    const ready = (): GuidedLiveState =>
      guidedLiveReducer(started(), {
        kind: 'polled',
        phase: 'complete',
        gpu: 'ready',
        atMs: T0 + 1000,
        tier: 'final_gpu',
        text: 'A live sentence that must not survive the next state.',
      });
    expect(ready().text).not.toBeNull();

    const reachers: Record<string, () => GuidedLiveState> = {
      [GUIDED_LIVE_STATUS.BLOCKED]: () => guidedLiveReducer(ready(), { kind: 'faces_decided', decided: false }),
      [GUIDED_LIVE_STATUS.QUEUED]: () => guidedLiveReducer(ready(), { kind: 'requested', atMs: T0 + 60_000 }),
      [GUIDED_LIVE_STATUS.WARMING]: () =>
        guidedLiveReducer(started(), { kind: 'polled', phase: 'warming', gpu: 'starting', atMs: T0 + 1000 }),
      [GUIDED_LIVE_STATUS.DESCRIBING]: () =>
        guidedLiveReducer(started(), { kind: 'polled', phase: 'describing', gpu: 'ready', atMs: T0 + 1000 }),
      [GUIDED_LIVE_STATUS.TIMED_OUT]: () =>
        guidedLiveReducer(started(), { kind: 'tick', atMs: T0 + GUIDED_LIVE_WAIT_CEILING_SECONDS * 1000 }),
      [GUIDED_LIVE_STATUS.UNAVAILABLE]: () =>
        guidedLiveReducer(started(), { kind: 'failed', reason: 'submit_failed' }),
      [GUIDED_LIVE_STATUS.CANCELLED]: () => guidedLiveReducer(started(), { kind: 'cancelled' }),
      [GUIDED_LIVE_STATUS.IDLE]: () =>
        decided(guidedLiveReducer(ready(), { kind: 'faces_decided', decided: false })),
    };

    for (const [status, reach] of Object.entries(reachers)) {
      const state = reach();
      expect(state.status).toBe(status);
      expect(state.text).toBeNull();
    }
  });
});

describe('what a live run is allowed to send', () => {
  it('carries only the media id, because no describe request accepts caller-supplied names', () => {
    expect(guidedLiveRequestPayload(42)).toEqual({ media_ids: [42] });
  });

  it('discloses that names come from the roster and not from the practice answers', () => {
    const scenario = confirmGuidedIdentity(createGuidedScenario(), 'katy-perry');
    const disclosure = guidedLiveNamingDisclosure(scenario);
    expect(disclosure.namesTravelWithTheRequest).toBe(false);
    expect(disclosure.namingSource).toBe('roster');
    expect(disclosure.confirmedHere).toEqual(['Katy Perry']);
  });

  it('reports nothing confirmed on an untouched scenario', () => {
    const scenario = createGuidedScenario();
    expect(guidedLiveNamingDisclosure(scenario).confirmedHere).toEqual([]);
    expect(scenario.identities.every((i) => i.status === GUIDED_IDENTITY_STATUS.UNCONFIRMED)).toBe(true);
  });
});
describe('degraded detection comes from the result tier', () => {
  it('treats a provisional CPU tier as degraded even when the gpu label says ready', () => {
    let state = started();
    state = guidedLiveReducer(state, {
      kind: 'polled',
      phase: 'complete',
      gpu: 'ready',
      tier: 'provisional_cpu',
      atMs: T0 + 5000,
      text: 'A shorter description.',
    });
    expect(state.status).toBe(GUIDED_LIVE_STATUS.DEGRADED);
  });

  it('treats a final GPU tier as ready even when the gpu label is unknown', () => {
    let state = started();
    state = guidedLiveReducer(state, {
      kind: 'polled',
      phase: 'complete',
      gpu: 'unknown',
      tier: 'final_gpu',
      atMs: T0 + 5000,
      text: 'A full description.',
    });
    expect(state.status).toBe(GUIDED_LIVE_STATUS.READY);
  });
});
