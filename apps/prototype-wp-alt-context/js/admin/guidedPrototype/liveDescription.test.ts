import { describe, expect, it } from 'vitest';

import {
  GUIDED_LIVE_BLOCKED_REASON,
  GUIDED_LIVE_REASON,
  GUIDED_LIVE_STATUS,
  GUIDED_LIVE_WAIT_CEILING_SECONDS,
  guidedLiveNamingDisclosure,
  guidedLiveRequestPayload,
  guidedLivePollDelayMs,
  guidedLiveReducer,
  guidedLiveRunMayBeLive,
  initialGuidedLiveState,
} from './liveDescription';
import type { GuidedLiveState } from './liveDescription';
import { GUIDED_IDENTITY_STATUS, confirmGuidedIdentity, createGuidedScenario } from './state';

const T0 = 1_000_000;

const decided = (state: GuidedLiveState): GuidedLiveState =>
  guidedLiveReducer(state, { kind: 'gate_changed', blockedReason: null });

const started = (): GuidedLiveState => {
  let state = decided(initialGuidedLiveState());
  state = guidedLiveReducer(state, { kind: 'requested', atMs: T0 });
  return guidedLiveReducer(state, { kind: 'accepted', runId: 'run-1', deadlineSeconds: 300, atMs: T0 });
};

describe('guided live description gate', () => {
  it('blocks a live run until every face has been decided', () => {
    const state = guidedLiveReducer(initialGuidedLiveState(), { kind: 'gate_changed', blockedReason: GUIDED_LIVE_BLOCKED_REASON.NO_FACES_DECIDED });
    expect(state.status).toBe(GUIDED_LIVE_STATUS.BLOCKED);
  });

  it('refuses a request while blocked so the model text cannot precede the human decision', () => {
    const blocked = guidedLiveReducer(initialGuidedLiveState(), { kind: 'gate_changed', blockedReason: GUIDED_LIVE_BLOCKED_REASON.NO_FACES_DECIDED });
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

    state = guidedLiveReducer(state, { kind: 'gate_changed', blockedReason: GUIDED_LIVE_BLOCKED_REASON.NO_FACES_DECIDED });

    expect(state.status).toBe(GUIDED_LIVE_STATUS.BLOCKED);
    expect(state.runId).toBeNull();
    expect(state.text).toBeNull();
    expect(state.reason).toBeNull();
  });

  it('ignores a poll that lands after the gate closed', () => {
    let state = started();
    state = guidedLiveReducer(state, { kind: 'gate_changed', blockedReason: GUIDED_LIVE_BLOCKED_REASON.NO_FACES_DECIDED });
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
      [GUIDED_LIVE_STATUS.BLOCKED]: () => guidedLiveReducer(ready(), { kind: 'gate_changed', blockedReason: GUIDED_LIVE_BLOCKED_REASON.NO_FACES_DECIDED }),
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
        decided(guidedLiveReducer(ready(), { kind: 'gate_changed', blockedReason: GUIDED_LIVE_BLOCKED_REASON.NO_FACES_DECIDED })),
    };

    for (const [status, reach] of Object.entries(reachers)) {
      const state = reach();
      expect(state.status).toBe(status);
      expect(state.text).toBeNull();
    }
  });
});

describe('blocked is one fact, not two that have to be kept in step', () => {
  it('seeds the reason it is blocked for, so the first paint already agrees with itself', () => {
    const state = initialGuidedLiveState(GUIDED_LIVE_BLOCKED_REASON.NO_MEDIA);
    expect(state.status).toBe(GUIDED_LIVE_STATUS.BLOCKED);
    expect(state.blockedReason).toBe(GUIDED_LIVE_BLOCKED_REASON.NO_MEDIA);
  });

  it('opens with no reason to be blocked when the gate is already clear', () => {
    const state = initialGuidedLiveState(null);
    expect(state.status).toBe(GUIDED_LIVE_STATUS.IDLE);
    expect(state.blockedReason).toBeNull();
  });

  it('carries the closing reason into the state rather than beside it', () => {
    const state = guidedLiveReducer(started(), {
      kind: 'gate_changed',
      blockedReason: GUIDED_LIVE_BLOCKED_REASON.NO_FACES_DECIDED,
    });
    expect(state.status).toBe(GUIDED_LIVE_STATUS.BLOCKED);
    expect(state.blockedReason).toBe(GUIDED_LIVE_BLOCKED_REASON.NO_FACES_DECIDED);
    expect(state.text).toBeNull();
    expect(state.runId).toBeNull();
  });

  it('holds a reason in exactly the blocked status and in no other', () => {
    const seen: GuidedLiveState[] = [];
    let state = guidedLiveReducer(initialGuidedLiveState(), {
      kind: 'gate_changed',
      blockedReason: null,
    });
    seen.push(state);
    state = guidedLiveReducer(state, { kind: 'requested', atMs: T0 });
    seen.push(state);
    state = guidedLiveReducer(state, { kind: 'accepted', runId: 'run-1', deadlineSeconds: 300, atMs: T0 });
    seen.push(state);
    state = guidedLiveReducer(state, { kind: 'polled', phase: 'warming', gpu: 'starting', atMs: T0 + 1 });
    seen.push(state);
    state = guidedLiveReducer(state, { kind: 'tick', atMs: T0 + 300_001 });
    seen.push(state);
    state = guidedLiveReducer(state, {
      kind: 'gate_changed',
      blockedReason: GUIDED_LIVE_BLOCKED_REASON.NO_MEDIA,
    });
    seen.push(state);

    // The comment the panel used to carry as a promise, asserted instead: the
    // two cannot disagree because there is only one of them.
    for (const step of seen) {
      expect(step.blockedReason === null).toBe(step.status !== GUIDED_LIVE_STATUS.BLOCKED);
    }
  });

  it('names every non-success reason from one vocabulary', () => {
    const timedOut = guidedLiveReducer(started(), { kind: 'tick', atMs: T0 + 300_001 });
    expect(timedOut.reason).toBe(GUIDED_LIVE_REASON.CLIENT_DEADLINE);

    const stopped = guidedLiveReducer(started(), { kind: 'cancelled' });
    expect(stopped.reason).toBe(GUIDED_LIVE_REASON.STOPPED_BY_OPERATOR);

    const empty = guidedLiveReducer(started(), {
      kind: 'polled',
      phase: 'complete',
      gpu: 'ready',
      atMs: T0 + 1,
      tier: 'final_gpu',
      text: '   ',
    });
    expect(empty.reason).toBe(GUIDED_LIVE_REASON.EMPTY_DESCRIPTION);
  });
});

describe('which runs the server may still be paying for', () => {
  it('counts every waiting phase, because the burst is running throughout', () => {
    let state = started();
    expect(guidedLiveRunMayBeLive(state)).toBe(true);
    state = guidedLiveReducer(state, { kind: 'polled', phase: 'warming', gpu: 'starting', atMs: T0 + 1000 });
    expect(guidedLiveRunMayBeLive(state)).toBe(true);
    state = guidedLiveReducer(state, { kind: 'polled', phase: 'describing', gpu: 'ready', atMs: T0 + 2000 });
    expect(guidedLiveRunMayBeLive(state)).toBe(true);
  });

  it('counts a timed-out run, because giving up on screen stops no GPU', () => {
    const state = guidedLiveReducer(started(), { kind: 'tick', atMs: T0 + 300_001 });
    expect(state.status).toBe(GUIDED_LIVE_STATUS.TIMED_OUT);
    expect(guidedLiveRunMayBeLive(state)).toBe(true);
  });

  it('counts no state the server has already reported finished or stopped', () => {
    const finished = guidedLiveReducer(started(), {
      kind: 'polled',
      phase: 'complete',
      gpu: 'ready',
      atMs: T0 + 1000,
      tier: 'final_gpu',
      text: 'Done.',
    });
    expect(finished.status).toBe(GUIDED_LIVE_STATUS.READY);
    expect(guidedLiveRunMayBeLive(finished)).toBe(false);

    const stopped = guidedLiveReducer(started(), { kind: 'cancelled' });
    expect(guidedLiveRunMayBeLive(stopped)).toBe(false);

    const failed = guidedLiveReducer(started(), { kind: 'failed', reason: 'poll_failed' });
    expect(guidedLiveRunMayBeLive(failed)).toBe(false);
  });

  it('counts nothing before the server has named a run', () => {
    expect(guidedLiveRunMayBeLive(initialGuidedLiveState())).toBe(false);
    const requested = guidedLiveReducer(decided(initialGuidedLiveState()), { kind: 'requested', atMs: T0 });
    expect(requested.runId).toBeNull();
    expect(guidedLiveRunMayBeLive(requested)).toBe(false);
  });
});

describe('the deadline bounds every action, not just the clock', () => {
  it('refuses a completion that arrives after the deadline the learner was promised', () => {
    const state = guidedLiveReducer(started(), {
      kind: 'polled',
      phase: 'complete',
      gpu: 'ready',
      atMs: T0 + 300_001,
      tier: 'final_gpu',
      text: 'A late sentence nobody is still waiting for.',
    });

    // A bound the run can outlive by resolving between two ticks is not a
    // bound. The learner was told the wait stops at 5:00; it stops at 5:00.
    expect(state.status).toBe(GUIDED_LIVE_STATUS.TIMED_OUT);
    expect(state.reason).toBe('client_deadline');
    expect(state.text).toBeNull();
  });

  it('honours a completion that lands one millisecond inside the deadline', () => {
    const state = guidedLiveReducer(started(), {
      kind: 'polled',
      phase: 'complete',
      gpu: 'ready',
      atMs: T0 + 299_999,
      tier: 'final_gpu',
      text: 'In time.',
    });

    expect(state.status).toBe(GUIDED_LIVE_STATUS.READY);
    expect(state.text).toBe('In time.');
  });

  it('times out a progress poll that lands after the deadline instead of extending the wait', () => {
    const state = guidedLiveReducer(started(), {
      kind: 'polled',
      phase: 'describing',
      gpu: 'ready',
      atMs: T0 + 300_001,
    });

    expect(state.status).toBe(GUIDED_LIVE_STATUS.TIMED_OUT);
    expect(state.reason).toBe('client_deadline');
  });
});

describe('every guard earns its place', () => {
  const terminalStates = (): readonly (readonly [string, GuidedLiveState])[] => [
    [
      'ready',
      guidedLiveReducer(started(), {
        kind: 'polled',
        phase: 'complete',
        gpu: 'ready',
        atMs: T0 + 1,
        tier: 'final_gpu',
        text: 'Done.',
      }),
    ],
    [
      'degraded',
      guidedLiveReducer(started(), {
        kind: 'polled',
        phase: 'complete',
        gpu: 'ready',
        atMs: T0 + 1,
        tier: 'provisional_cpu',
        text: 'Rougher.',
      }),
    ],
    ['timed_out', guidedLiveReducer(started(), { kind: 'tick', atMs: T0 + 300_001 })],
    ['cancelled', guidedLiveReducer(started(), { kind: 'cancelled' })],
    ['unavailable', guidedLiveReducer(started(), { kind: 'failed', reason: GUIDED_LIVE_REASON.POLL_FAILED })],
  ];

  it('closes the gate from every terminal state, not only from a waiting one', () => {
    for (const [label, state] of terminalStates()) {
      const closed = guidedLiveReducer(state, {
        kind: 'gate_changed',
        blockedReason: GUIDED_LIVE_BLOCKED_REASON.NO_FACES_DECIDED,
      });
      expect(closed.status, label).toBe(GUIDED_LIVE_STATUS.BLOCKED);
      expect(closed.text, label).toBeNull();
      expect(closed.runId, label).toBeNull();
    }
    const fromIdle = guidedLiveReducer(decided(initialGuidedLiveState()), {
      kind: 'gate_changed',
      blockedReason: GUIDED_LIVE_BLOCKED_REASON.NO_MEDIA,
    });
    expect(fromIdle.status).toBe(GUIDED_LIVE_STATUS.BLOCKED);
  });

  it('leaves a run alone when the gate opens on a state that was never blocked', () => {
    for (const [label, state] of terminalStates()) {
      expect(guidedLiveReducer(state, { kind: 'gate_changed', blockedReason: null }), label).toBe(state);
    }
  });

  it('refuses a second request while a run is already waiting', () => {
    const waiting = started();
    expect(guidedLiveReducer(waiting, { kind: 'requested', atMs: T0 + 5000 })).toBe(waiting);
  });

  it('ignores an acceptance or a widened deadline once the run is no longer waiting', () => {
    for (const [label, state] of terminalStates()) {
      expect(
        guidedLiveReducer(state, { kind: 'accepted', runId: 'run-2', deadlineSeconds: 60, atMs: T0 }),
        label,
      ).toBe(state);
      expect(guidedLiveReducer(state, { kind: 'deadline_raised', deadlineSeconds: 510 }), label).toBe(state);
    }
  });

  it('ignores a tick with no run to time', () => {
    const blocked = initialGuidedLiveState();
    expect(guidedLiveReducer(blocked, { kind: 'tick', atMs: T0 })).toBe(blocked);
    const requestedWithoutStart = { ...started(), startedAtMs: null };
    expect(guidedLiveReducer(requestedWithoutStart, { kind: 'tick', atMs: T0 })).toBe(requestedWithoutStart);
  });

  it('ignores every late action once a run has ended', () => {
    for (const [label, state] of terminalStates()) {
      expect(
        guidedLiveReducer(state, { kind: 'polled', phase: 'complete', gpu: 'ready', atMs: T0 + 2, text: 'Late.' }),
        label,
      ).toBe(state);
      expect(guidedLiveReducer(state, { kind: 'cancelled' }), label).toBe(state);
      expect(guidedLiveReducer(state, { kind: 'failed', reason: GUIDED_LIVE_REASON.RUN_FAILED }), label).toBe(state);
      expect(guidedLiveReducer(state, { kind: 'tick', atMs: T0 + 2 }), label).toBe(state);
    }
  });

  it('refuses to absorb an action it does not handle', () => {
    // A silent `return state` default is how a new action ships doing nothing.
    expect(() =>
      guidedLiveReducer(started(), { kind: 'not_a_real_action' } as unknown as Parameters<
        typeof guidedLiveReducer
      >[1]),
    ).toThrow(/Unhandled guided live action/);
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
