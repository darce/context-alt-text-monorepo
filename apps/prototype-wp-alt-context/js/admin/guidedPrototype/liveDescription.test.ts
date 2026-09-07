import { describe, expect, it } from 'vitest';

import {
  GUIDED_LIVE_BLOCKED_REASON,
  GUIDED_LIVE_DEADLINE_CEILING_SECONDS,
  GUIDED_LIVE_DEADLINE_FLOOR_SECONDS,
  GUIDED_LIVE_DEADLINE_SLACK_MS,
  GUIDED_LIVE_GPU_WARMUP_CEILING_SECONDS,
  GUIDED_LIVE_KEEP_WAITING_SECONDS,
  GUIDED_LIVE_REASON,
  GUIDED_LIVE_STATUS,
  GUIDED_LIVE_WAIT_CEILING_SECONDS,
  guidedLiveNamingDisclosure,
  isGuidedLiveDeadlineDisclosed,
  guidedLiveRequestPayload,
  guidedLivePollDelayMs,
  guidedLiveReducer,
  guidedLiveRunMayBeLive,
  initialGuidedLiveState,
  resolveGuidedLiveDeadlineMs,
} from './liveDescription';
import { GUIDED_LIVE_WARM_CEILING_SECONDS } from './useGuidedLiveDescription';
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
  it('clamps an over-long local fallback deadline to the client ceiling', () => {
    let state = decided(initialGuidedLiveState());
    state = guidedLiveReducer(state, { kind: 'requested', atMs: T0 });
    state = guidedLiveReducer(state, { kind: 'accepted', runId: 'run-1', deadlineSeconds: 9999, atMs: T0 });
    expect(state.deadlineMs).toBe(GUIDED_LIVE_WAIT_CEILING_SECONDS * 1000);
  });

  it('keeps a local fallback deadline shorter than the ceiling', () => {
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
    expect(state.reason).toBe(GUIDED_LIVE_REASON.CPU_TIER);
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
    expect(state.reason).toBe(GUIDED_LIVE_REASON.CPU_TIER);
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

describe('the deadline only ever moves in the learner\'s favour', () => {
  it('lets the server set the wait it will actually honour, including downward', () => {
    // The server is the authority on its own work, so acceptance replaces the
    // client's cold placeholder outright. The learner is protected from seeing
    // that placeholder revised by the panel, which advertises no ceiling until
    // a run id exists -- not by freezing the client's guess in the reducer.
    const queued = guidedLiveReducer(decided(initialGuidedLiveState()), { kind: 'requested', atMs: T0 });
    expect(queued.runId).toBeNull();
    expect(queued.deadlineMs).toBe(GUIDED_LIVE_WAIT_CEILING_SECONDS * 1000);

    const accepted = guidedLiveReducer(queued, { kind: 'accepted', runId: 'run-warm', deadlineSeconds: 180, atMs: T0 + 3_000 });

    expect(accepted.runId).toBe('run-warm');
    expect(accepted.deadlineMs).toBe(180_000);
  });

  it('keeps the run id when acceptance itself lands past the deadline', () => {
    // Timing out is right here, but dropping the id is not: a run the server
    // just confirmed is exactly the one that still needs cancelling.
    const queued = guidedLiveReducer(decided(initialGuidedLiveState()), { kind: 'requested', atMs: T0 });
    const accepted = guidedLiveReducer(queued, {
      kind: 'accepted',
      runId: 'run-late',
      deadlineSeconds: 180,
      atMs: T0 + GUIDED_LIVE_WAIT_CEILING_SECONDS * 1000 + 1,
    });

    expect(accepted.status).toBe(GUIDED_LIVE_STATUS.TIMED_OUT);
    expect(accepted.runId).toBe('run-late');
    expect(guidedLiveRunMayBeLive(accepted)).toBe(true);
  });
});

describe('a description already in the browser is not thrown away', () => {
  it('shows a completed sentence that arrives with the poll that times out', () => {
    // The deadline exists to bound an unbounded wait, not to discard an answer
    // the client is holding. Telling the learner "the run may still finish on
    // its own" while the sentence sits in the same payload is a lie.
    const state = guidedLiveReducer(started(), {
      kind: 'polled',
      phase: 'complete',
      gpu: 'ready',
      tier: 'final_gpu',
      text: 'A real GPU sentence.',
      atMs: T0 + 300_001,
    });

    expect(state.status).toBe(GUIDED_LIVE_STATUS.READY);
    expect(state.text).toBe('A real GPU sentence.');
  });

  it('still times out when the late poll carries no answer', () => {
    const state = guidedLiveReducer(started(), {
      kind: 'polled',
      phase: 'describing',
      gpu: 'ready',
      atMs: T0 + 300_001,
    });

    expect(state.status).toBe(GUIDED_LIVE_STATUS.TIMED_OUT);
    expect(state.reason).toBe(GUIDED_LIVE_REASON.CLIENT_DEADLINE);
  });
});

describe('blocked reason never outlives the block', () => {
  it('clears the reason when the gate re-opens from a non-blocked state', () => {
    // status and blockedReason are independent fields, so nothing structural
    // stops a stale reason riding out of BLOCKED. The panel reads the reason
    // with a fallback that would then name the wrong obstacle.
    const stale = { ...started(), blockedReason: GUIDED_LIVE_BLOCKED_REASON.NO_MEDIA };
    const reopened = guidedLiveReducer(stale, { kind: 'gate_changed', blockedReason: null });

    expect(reopened.blockedReason).toBeNull();
  });
});

describe('the deadline bounds every action, not just the clock', () => {
  it('shows a completion that arrives just after the deadline rather than discarding it', () => {
    const state = guidedLiveReducer(started(), {
      kind: 'polled',
      phase: 'complete',
      gpu: 'ready',
      atMs: T0 + 300_001,
      tier: 'final_gpu',
      text: 'A sentence the GPU already paid for.',
    });

    // This reverses the earlier rule that a late completion is refused. That
    // rule bounded the wrong thing: the deadline exists so a learner is never
    // left waiting indefinitely, and once the sentence is in the browser there
    // is no wait left to bound. Refusing it here threw away work the burst had
    // already been billed for and told the learner "the run may still finish
    // on its own" while holding its result -- a false statement.
    //
    // The bound still binds everywhere it means something: `tick` and every
    // non-complete poll below still time out at 5:00. Note too that atMs is
    // sampled after the items round trip that carried this payload, so the
    // millisecond that pushes a completion over is often fetch latency rather
    // than the run.
    expect(state.status).toBe(GUIDED_LIVE_STATUS.READY);
    expect(state.text).toBe('A sentence the GPU already paid for.');
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

describe('resolveGuidedLiveDeadlineMs: the server budget the client is willing to trust', () => {
  const WARM_CEILING_MS = GUIDED_LIVE_WARM_CEILING_SECONDS * 1000;
  const COLD_CEILING_MS = GUIDED_LIVE_WAIT_CEILING_SECONDS * 1000;

  it('adopts a disclosed budget that is inside the warm ceiling, plus slack', () => {
    expect(resolveGuidedLiveDeadlineMs(WARM_CEILING_MS, 60, 'ready')).toBe(60_000 + GUIDED_LIVE_DEADLINE_SLACK_MS);
    expect(resolveGuidedLiveDeadlineMs(WARM_CEILING_MS, 60, 'ready')).toBe(75_000);
  });

  it('lets a warm run honor a disclosed generation budget above the local ceiling', () => {
    expect(resolveGuidedLiveDeadlineMs(WARM_CEILING_MS, 240, 'ready')).toBe(
      240_000 + GUIDED_LIVE_DEADLINE_SLACK_MS,
    );
    expect(resolveGuidedLiveDeadlineMs(WARM_CEILING_MS, 240, 'ready')).not.toBe(WARM_CEILING_MS);
  });

  // Replaces an assertion that pinned the bug: the old formula ran the same
  // min() for the cold branch as for the warm one, so a cold run whose server
  // disclosed its 180s GENERATION budget waited 195s -- while the scale-to-zero
  // pod is still allowed 510s just to load weights. `deadline_seconds` excludes
  // warm-up by contract, so the client owes that leg itself.
  it('cold start: adds the warm-up leg the disclosed budget explicitly excludes', () => {
    expect(resolveGuidedLiveDeadlineMs(COLD_CEILING_MS, 60, 'stopped')).toBe(
      (60 + GUIDED_LIVE_GPU_WARMUP_CEILING_SECONDS) * 1000 + GUIDED_LIVE_DEADLINE_SLACK_MS,
    );
    expect(resolveGuidedLiveDeadlineMs(COLD_CEILING_MS, 60, 'stopped')).toBe(585_000);
  });

  it('does not time a cold run out at 3:15 on the service default budget', () => {
    // The reported run: cold GPU, `deadline_seconds: 180`. The old formula gave
    // 195_000 and flipped the panel to TIMED_OUT at 3:15 while the run was
    // healthy and finished minutes later. The disclosed generation budget now
    // remains authoritative, with the cold warm-up leg added back.
    const resolved = resolveGuidedLiveDeadlineMs(COLD_CEILING_MS, 180, 'stopped');

    expect(resolved).toBeGreaterThan(195_000);
    expect(resolved).toBe(180_000 + GUIDED_LIVE_GPU_WARMUP_CEILING_SECONDS * 1000 + GUIDED_LIVE_DEADLINE_SLACK_MS);
  });

  it('adds the warm-up leg to a disclosed 240-second budget on unknown GPU state', () => {
    expect(resolveGuidedLiveDeadlineMs(COLD_CEILING_MS, 240, 'unknown')).toBe(
      (240 + GUIDED_LIVE_GPU_WARMUP_CEILING_SECONDS) * 1000 + GUIDED_LIVE_DEADLINE_SLACK_MS,
    );
  });

  it('owes the warm-up leg on every gpu state except ready', () => {
    for (const gpu of ['unknown', 'stopped', 'starting', 'warming', 'degraded'] as const) {
      expect(resolveGuidedLiveDeadlineMs(COLD_CEILING_MS, 60, gpu), gpu).toBe(585_000);
    }
    expect(resolveGuidedLiveDeadlineMs(COLD_CEILING_MS, 60, 'ready')).toBe(75_000);
  });

  it('stays consistent with the proxy: warm-up plus generation is the whole ceiling', () => {
    // src/api/class-public-demo-describe-controller.php::public_deadline_seconds()
    // returns $warmup + $inference. The client's cold ceiling is the same sum.
    expect(GUIDED_LIVE_WAIT_CEILING_SECONDS).toBe(
      GUIDED_LIVE_GPU_WARMUP_CEILING_SECONDS + GUIDED_LIVE_WARM_CEILING_SECONDS,
    );
  });

  it('falls back to the local ceiling when the server discloses nothing', () => {
    expect(resolveGuidedLiveDeadlineMs(WARM_CEILING_MS, null, 'ready')).toBe(WARM_CEILING_MS);
    expect(resolveGuidedLiveDeadlineMs(WARM_CEILING_MS, undefined, 'ready')).toBe(WARM_CEILING_MS);
    expect(resolveGuidedLiveDeadlineMs(COLD_CEILING_MS, null, 'stopped')).toBe(COLD_CEILING_MS);
  });

  it('falls back to the local ceiling on a disclosed value that is not usable', () => {
    expect(resolveGuidedLiveDeadlineMs(WARM_CEILING_MS, Number.NaN, 'ready')).toBe(WARM_CEILING_MS);
    expect(resolveGuidedLiveDeadlineMs(WARM_CEILING_MS, -1, 'ready')).toBe(WARM_CEILING_MS);
    expect(resolveGuidedLiveDeadlineMs(WARM_CEILING_MS, 0, 'ready')).toBe(WARM_CEILING_MS);
    expect(resolveGuidedLiveDeadlineMs(WARM_CEILING_MS, Number.POSITIVE_INFINITY, 'ready')).toBe(WARM_CEILING_MS);
    expect(resolveGuidedLiveDeadlineMs(WARM_CEILING_MS, '60' as unknown as number, 'ready')).toBe(WARM_CEILING_MS);
  });

  it('refuses a budget below the trust floor rather than declaring a healthy run timed out', () => {
    // A misconfigured ACX_DESCRIPTION_TIMEOUT_SECONDS=1, or a truncated number
    // in a proxied body, used to resolve to 16s and time the panel out sixteen
    // seconds into a healthy run with no path back up.
    expect(resolveGuidedLiveDeadlineMs(COLD_CEILING_MS, 1, 'ready')).toBe(COLD_CEILING_MS);
    expect(resolveGuidedLiveDeadlineMs(COLD_CEILING_MS, 29, 'ready')).toBe(COLD_CEILING_MS);
    expect(resolveGuidedLiveDeadlineMs(COLD_CEILING_MS, 0.5, 'ready')).toBe(COLD_CEILING_MS);
  });

  it('refuses a budget just above the generation trust ceiling', () => {
    expect(resolveGuidedLiveDeadlineMs(WARM_CEILING_MS, GUIDED_LIVE_DEADLINE_CEILING_SECONDS + 1, 'ready')).toBe(
      WARM_CEILING_MS,
    );
  });

  it('accepts a budget exactly at the floor, so the band has a boundary and not a gap', () => {
    expect(GUIDED_LIVE_DEADLINE_FLOOR_SECONDS).toBe(30);
    expect(resolveGuidedLiveDeadlineMs(COLD_CEILING_MS, GUIDED_LIVE_DEADLINE_FLOOR_SECONDS, 'ready')).toBe(
      GUIDED_LIVE_DEADLINE_FLOOR_SECONDS * 1000 + GUIDED_LIVE_DEADLINE_SLACK_MS,
    );
  });

  it('names the same band from the predicate the resolver uses', () => {
    expect(isGuidedLiveDeadlineDisclosed(180)).toBe(true);
    expect(isGuidedLiveDeadlineDisclosed(GUIDED_LIVE_DEADLINE_CEILING_SECONDS)).toBe(true);
    expect(isGuidedLiveDeadlineDisclosed(1)).toBe(false);
    expect(isGuidedLiveDeadlineDisclosed(null)).toBe(false);
    expect(isGuidedLiveDeadlineDisclosed('180')).toBe(false);
    expect(isGuidedLiveDeadlineDisclosed(GUIDED_LIVE_DEADLINE_CEILING_SECONDS + 1)).toBe(false);
  });
});

describe('the reducer adopts the server-disclosed deadline once, at accept', () => {
  const acceptedWith = (over: {
    deadlineSeconds?: number;
    gpu?: 'ready' | 'stopped' | 'starting';
    disclosedDeadlineSeconds?: number | null;
  } = {}): GuidedLiveState => {
    let state = decided(initialGuidedLiveState());
    state = guidedLiveReducer(state, { kind: 'requested', atMs: T0 });
    return guidedLiveReducer(state, {
      kind: 'accepted',
      runId: 'run-1',
      deadlineSeconds: over.deadlineSeconds ?? GUIDED_LIVE_WARM_CEILING_SECONDS,
      gpu: over.gpu ?? 'ready',
      disclosedDeadlineSeconds: over.disclosedDeadlineSeconds,
      atMs: T0,
    });
  };

  it('sets deadlineMs from the disclosed budget on accept', () => {
    expect(acceptedWith({ disclosedDeadlineSeconds: 60 }).deadlineMs).toBe(75_000);
  });

  it('ignores a different deadline_seconds carried on a later poll -- a server bug, not a resize', () => {
    let state = acceptedWith({ disclosedDeadlineSeconds: 60 });
    expect(state.deadlineMs).toBe(75_000);

    state = guidedLiveReducer(state, {
      kind: 'polled',
      phase: 'warming',
      gpu: 'ready',
      atMs: T0 + 1000,
      disclosedDeadlineSeconds: 900,
    });
    expect(state.deadlineMs).toBe(75_000);
    expect(state.disclosedDeadlineSeconds).toBe(60);
  });

  it('keeps the local ceiling when the server discloses nothing on accept', () => {
    expect(acceptedWith().deadlineMs).toBe(GUIDED_LIVE_WARM_CEILING_SECONDS * 1000);
    expect(acceptedWith().disclosedDeadlineSeconds).toBeNull();
  });

  it('keeps the disclosed budget verbatim, not folded into the deadline it produced', () => {
    // The number itself is what makes a later re-derivation with a newly owed
    // warm-up leg possible; a boolean "something was disclosed" latch could not.
    expect(acceptedWith({ disclosedDeadlineSeconds: 400 }).disclosedDeadlineSeconds).toBe(400);
  });

  it('lets a first disclosure arrive on a poll when the accept carried none', () => {
    let state = acceptedWith({ deadlineSeconds: GUIDED_LIVE_WAIT_CEILING_SECONDS, gpu: 'stopped' });
    expect(state.disclosedDeadlineSeconds).toBeNull();

    state = guidedLiveReducer(state, {
      kind: 'polled',
      phase: 'warming',
      gpu: 'starting',
      atMs: T0 + 1000,
      disclosedDeadlineSeconds: 60,
    });

    expect(state.disclosedDeadlineSeconds).toBe(60);
  });
});

describe('a legitimate extension stays reachable for the whole run', () => {
  const acceptedWarmThenCold = (disclosed: number | null): GuidedLiveState => {
    let state = decided(initialGuidedLiveState());
    state = guidedLiveReducer(state, { kind: 'requested', atMs: T0 });
    // The submit read gpu_state 'ready', so the warm pin was chosen.
    state = guidedLiveReducer(state, {
      kind: 'accepted',
      runId: 'run-1',
      deadlineSeconds: GUIDED_LIVE_WARM_CEILING_SECONDS,
      gpu: 'ready',
      disclosedDeadlineSeconds: disclosed,
      atMs: T0,
    });
    // ...then the pod was reaped, or the read raced, and poll #2 says cold.
    return guidedLiveReducer(state, {
      kind: 'deadline_raised',
      deadlineSeconds: GUIDED_LIVE_WAIT_CEILING_SECONDS,
      gpu: 'stopped',
    });
  };

  it('lifts a warm-pinned deadline when a poll reveals a cold GPU', () => {
    // Regression: a one-way "the server disclosed something" latch suppressed
    // every later deadline_raised, so this run timed out at 3:00 against a
    // server budget of 400s plus a 510s warm-up it had not yet begun.
    const state = acceptedWarmThenCold(400);

    expect(state.deadlineMs).toBeGreaterThan(GUIDED_LIVE_WARM_CEILING_SECONDS * 1000);
    expect(state.deadlineMs).toBe(
      400_000 + GUIDED_LIVE_GPU_WARMUP_CEILING_SECONDS * 1000 + GUIDED_LIVE_DEADLINE_SLACK_MS,
    );
  });

  it('re-derives the raise from the disclosed budget, not from the raw ceiling', () => {
    // Disclosed 60s of generation plus the 510s warm-up now owed. The disclosure
    // still governs, and is measured against the leg the run actually has to
    // pay without being capped by the local whole-wait ceiling.
    const state = acceptedWarmThenCold(60);

    expect(state.deadlineMs).toBe(585_000);
  });

  it('never shrinks the wait, however the raise resolves', () => {
    let state = decided(initialGuidedLiveState());
    state = guidedLiveReducer(state, { kind: 'requested', atMs: T0 });
    state = guidedLiveReducer(state, {
      kind: 'accepted',
      runId: 'run-1',
      deadlineSeconds: GUIDED_LIVE_WAIT_CEILING_SECONDS,
      gpu: 'stopped',
      atMs: T0,
    });
    const wide = state.deadlineMs;

    state = guidedLiveReducer(state, {
      kind: 'deadline_raised',
      deadlineSeconds: GUIDED_LIVE_WARM_CEILING_SECONDS,
      gpu: 'ready',
    });

    expect(state.deadlineMs).toBe(wide);
  });

  it('is idempotent: the same raise applied twice changes nothing', () => {
    const once = acceptedWarmThenCold(60);
    const twice = guidedLiveReducer(once, {
      kind: 'deadline_raised',
      deadlineSeconds: GUIDED_LIVE_WAIT_CEILING_SECONDS,
      gpu: 'stopped',
    });

    expect(twice.deadlineMs).toBe(once.deadlineMs);
  });
});

describe('keeping the wait is offered instead of only a restart', () => {
  const timedOut = (): GuidedLiveState => {
    let state = decided(initialGuidedLiveState());
    state = guidedLiveReducer(state, { kind: 'requested', atMs: T0 });
    state = guidedLiveReducer(state, {
      kind: 'accepted',
      runId: 'run-1',
      deadlineSeconds: GUIDED_LIVE_WARM_CEILING_SECONDS,
      gpu: 'ready',
      atMs: T0,
    });
    state = guidedLiveReducer(state, { kind: 'polled', phase: 'describing', gpu: 'ready', atMs: T0 + 1000 });
    return guidedLiveReducer(state, { kind: 'tick', atMs: T0 + GUIDED_LIVE_WARM_CEILING_SECONDS * 1000 + 1 });
  };

  it('times out holding the run id, so there is something to keep waiting on', () => {
    const state = timedOut();
    expect(state.status).toBe(GUIDED_LIVE_STATUS.TIMED_OUT);
    expect(state.runId).toBe('run-1');
    expect(guidedLiveRunMayBeLive(state)).toBe(true);
  });

  it('resumes the same run under a fresh window rather than starting a second burst', () => {
    const state = timedOut();
    const resumed = guidedLiveReducer(state, { kind: 'wait_resumed', atMs: T0 });

    expect(resumed.runId).toBe('run-1');
    expect(resumed.reason).toBeNull();
    expect(resumed.deadlineMs).toBe(state.elapsedMs + GUIDED_LIVE_KEEP_WAITING_SECONDS * 1000);
    expect(resumed.deadlineMs).toBeGreaterThan(state.elapsedMs);
  });

  it('resumes at the phase the run had actually reached, not back at queued', () => {
    const resumed = guidedLiveReducer(timedOut(), { kind: 'wait_resumed', atMs: T0 });

    expect(resumed.status).toBe(GUIDED_LIVE_STATUS.DESCRIBING);
  });

  it('polls again once resumed instead of staying stopped', () => {
    let state = guidedLiveReducer(timedOut(), { kind: 'wait_resumed', atMs: T0 });
    const at = state.elapsedMs + 1000;
    state = guidedLiveReducer(state, {
      kind: 'polled',
      phase: 'complete',
      gpu: 'ready',
      tier: 'final_gpu',
      atMs: T0 + at,
      text: 'It finished after all.',
    });

    expect(state.status).toBe(GUIDED_LIVE_STATUS.READY);
    expect(state.text).toBe('It finished after all.');
  });

  it('refuses to resume a state that is not a timed-out run', () => {
    const blocked = initialGuidedLiveState();
    expect(guidedLiveReducer(blocked, { kind: 'wait_resumed', atMs: T0 })).toBe(blocked);

    const waiting = started();
    expect(guidedLiveReducer(waiting, { kind: 'wait_resumed', atMs: T0 })).toBe(waiting);

    const withoutRun = { ...timedOut(), runId: null };
    expect(guidedLiveReducer(withoutRun, { kind: 'wait_resumed', atMs: T0 })).toBe(withoutRun);
  });
});
