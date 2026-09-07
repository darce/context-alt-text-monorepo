import React from 'react';

import {
  GUIDED_LIVE_BLOCKED_REASON,
  GUIDED_LIVE_REASON,
  GUIDED_LIVE_STATUS,
  isGuidedLiveWaiting,
} from '../../guidedPrototype/liveDescription';
import type {
  GuidedLiveBlockedReason,
  GuidedLiveState,
  GuidedLiveStatus,
} from '../../guidedPrototype/liveDescription';
import { useGuidedLiveDescription } from '../../guidedPrototype/useGuidedLiveDescription';
import type { GuidedLiveDescriptionClient } from '../../guidedPrototype/useGuidedLiveDescription';
import type { GuidedScenario } from '../../guidedPrototype/state';

export interface GuidedLiveDescriptionPanelProps {
  scenario: GuidedScenario;
  /** Attachment the live run describes; null when the demo has none configured. */
  mediaId: number | null;
  /** Injected in tests; production uses the describe-run client. */
  client?: GuidedLiveDescriptionClient;
}

/** Every status carries a glyph as well as a colour ([A11Y-06] second channel always). */
const STATUS_ICON: Record<GuidedLiveStatus, string> = {
  [GUIDED_LIVE_STATUS.BLOCKED]: '•',
  [GUIDED_LIVE_STATUS.IDLE]: '•',
  [GUIDED_LIVE_STATUS.QUEUED]: '…',
  [GUIDED_LIVE_STATUS.WARMING]: '…',
  [GUIDED_LIVE_STATUS.DESCRIBING]: '…',
  [GUIDED_LIVE_STATUS.READY]: '✓',
  [GUIDED_LIVE_STATUS.DEGRADED]: '!',
  [GUIDED_LIVE_STATUS.TIMED_OUT]: '!',
  [GUIDED_LIVE_STATUS.UNAVAILABLE]: '×',
  [GUIDED_LIVE_STATUS.CANCELLED]: '×',
};

/** Stable target for the disabled button's aria-describedby. */
const STATUS_LINE_ID = 'guided-live-status-line';

const assertNever = (value: never): never => {
  throw new Error(`Unhandled guided live status: ${String(value)}`);
};

const clock = (ms: number): string => {
  const total = Math.max(0, Math.floor(ms / 1000));
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, '0')}`;
};

/**
 * The face gate is the lesson's sequencing, not a data dependency: the panel
 * says two lines up that names come from the roster on the server, so a run
 * submitted with every face still open would return the same sentence. Copy
 * that reads as a requirement teaches the wrong model of what the service
 * needs, so the line names the real reason it is closed (rg-003).
 */
const blockedLine = (reason: GuidedLiveBlockedReason): string =>
  reason === GUIDED_LIVE_BLOCKED_REASON.NO_MEDIA
    ? 'No live photo is configured for this demo, so the live run is off.'
    : "Decide each face match first, then you can describe this photo live. That is the lesson's order, not something the run needs.";

/**
 * One source: the reason the gate is shut travels inside the state, so blocked
 * copy and blocked status cannot describe different moments. The switch is
 * exhaustive for the same reason -- a default that answered "Ready when you
 * are." for an unhandled status paired the idle sentence with a disabled
 * button and called that ready (S1-B-09).
 */
const statusLine = (state: GuidedLiveState): string => {
  switch (state.status) {
    case GUIDED_LIVE_STATUS.BLOCKED:
      return blockedLine(state.blockedReason ?? GUIDED_LIVE_BLOCKED_REASON.NO_FACES_DECIDED);
    case GUIDED_LIVE_STATUS.IDLE:
      return 'Ready when you are.';
    case GUIDED_LIVE_STATUS.QUEUED:
      return 'Queued. Waiting for the service to pick it up.';
    case GUIDED_LIVE_STATUS.WARMING:
      // The honest number, not a spinner: a cold burst really is minutes.
      return 'Starting the GPU. A cold start can take several minutes.';
    case GUIDED_LIVE_STATUS.DESCRIBING:
      return 'Describing the photo now.';
    case GUIDED_LIVE_STATUS.READY:
      return 'Done. The GPU wrote this.';
    case GUIDED_LIVE_STATUS.DEGRADED:
      // Naming the CPU is itself a claim about who wrote the sentence, so it
      // is only made when the run reported the CPU tier.
      return state.reason === GUIDED_LIVE_REASON.CPU_FALLBACK
        ? 'Done, but the GPU was not available, so the CPU wrote this. It is rougher than a GPU description.'
        : 'Done, but the run did not say whether the GPU wrote this.';
    case GUIDED_LIVE_STATUS.TIMED_OUT:
      return 'Stopped waiting. The run may still finish on its own; nothing was applied here.';
    case GUIDED_LIVE_STATUS.CANCELLED:
      // Two different events land here. STOPPED_BY_OPERATOR is this learner
      // pressing Stop; RUN_CANCELLED is the service (or another tab, or an
      // operator) ending the run underneath them. Attributing the second to
      // the first tells someone who did nothing that they did something, and
      // sends them looking for a mistake they did not make.
      return state.reason === GUIDED_LIVE_REASON.RUN_CANCELLED
        ? 'The run was cancelled before it finished. Nothing was applied.'
        : 'You stopped the wait. Nothing was applied.';
    case GUIDED_LIVE_STATUS.UNAVAILABLE:
      return state.reason === GUIDED_LIVE_REASON.EMPTY_DESCRIPTION
        ? 'The run finished with nothing to show. Nothing was applied.'
        : 'The live run could not finish. Nothing was applied.';
    default:
      return assertNever(state.status);
  }
};

/**
 * The live run sits beside the saved draft and never replaces it. Everything
 * here is additive by construction: no terminal state touches the draft, the
 * Apply button, or the lesson's progress ([RLSE-04] every state designed,
 * [HAI-12] output is a proposal).
 */
export const GuidedLiveDescriptionPanel = ({
  scenario,
  mediaId,
  client,
}: GuidedLiveDescriptionPanelProps): React.JSX.Element => {
  const { state, disclosure, canRequest, canCancel, request, cancel } = useGuidedLiveDescription({
    scenario,
    mediaId,
    client,
  });

  const waiting = isGuidedLiveWaiting(state.status);
  const names = disclosure.confirmedHere;

  return (
    <section className="acx-guided-live" aria-labelledby="guided-live-title" data-testid="guided-live">
      <h3 id="guided-live-title">See it run live</h3>

      <p className="acx-guided-live__additive" data-testid="guided-live-additive">
        A live run never changes the draft above, and it never changes what Apply would write.
      </p>

      <p className="acx-guided-live__naming" data-testid="guided-live-naming">
        Names come from your roster on the server, not from this page.{' '}
        {names.length > 0 ? `Confirmed here: ${names.join(', ')}.` : 'You have not confirmed anyone here yet.'}
      </p>

      {/*
        One region, mounted for the panel's whole life, holding both the status
        and the sentence. A blockquote that appears with its own aria-live is
        announced by nothing: a live region has to already exist before its
        contents change, so the result used to be silent for AT users (S1-B-07).
      */}
      <div role="status" aria-live="polite" aria-label="Live run status" className="acx-guided-live__live">
        <p
          id={STATUS_LINE_ID}
          className={`acx-guided-live__status acx-guided-live__status--${state.status}`}
          data-testid="guided-live-status"
        >
          <span className="acx-guided-live__icon" aria-hidden="true" data-testid="guided-live-icon">
            {STATUS_ICON[state.status]}
          </span>{' '}
          {statusLine(state)}
        </p>

        {waiting ? (
          <p className="acx-guided-live__elapsed" data-testid="guided-live-elapsed">
            {/*
              Before the server accepts the run there is no negotiated ceiling,
              only the client's cold-path placeholder. Printing that as "of up
              to 8:30" and then revising it down to 3:00 a second later shrinks
              a promise under someone already waiting. Advertise nothing until
              there is something to advertise.
            */}
            {state.runId === null
              ? clock(state.elapsedMs)
              : `${clock(state.elapsedMs)} of up to ${clock(state.deadlineMs)}`}
          </p>
        ) : null}

        {state.text !== null ? (
          <blockquote className="acx-guided-live__text" data-testid="guided-live-text">
            {state.text}
          </blockquote>
        ) : null}
      </div>

      <div className="acx-guided-live__actions">
        <button
          type="button"
          className="acx-button acx-button--secondary"
          onClick={request}
          disabled={!canRequest}
          // A disabled control with no stated reason is a dead end for anyone
          // who cannot see the sentence next to it (S1-B-08).
          aria-describedby={canRequest ? undefined : STATUS_LINE_ID}
        >
          Describe it live
        </button>
        {canCancel ? (
          <button type="button" className="acx-button acx-button--tertiary" onClick={cancel}>
            Stop waiting
          </button>
        ) : null}
      </div>

    </section>
  );
};
