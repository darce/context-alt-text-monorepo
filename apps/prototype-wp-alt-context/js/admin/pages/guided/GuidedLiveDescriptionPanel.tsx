import React from 'react';

import { GUIDED_LIVE_STATUS, isGuidedLiveWaiting } from '../../guidedPrototype/liveDescription';
import type { GuidedLiveState, GuidedLiveStatus } from '../../guidedPrototype/liveDescription';
import { useGuidedLiveDescription } from '../../guidedPrototype/useGuidedLiveDescription';
import type {
  GuidedLiveBlockedReason,
  GuidedLiveDescriptionClient,
} from '../../guidedPrototype/useGuidedLiveDescription';
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

const clock = (ms: number): string => {
  const total = Math.max(0, Math.floor(ms / 1000));
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, '0')}`;
};

const blockedLine = (reason: GuidedLiveBlockedReason): string =>
  reason === 'no_media'
    ? 'No live photo is configured for this demo, so the live run is off.'
    : 'Decide each face match first. Then you can describe this photo live.';

const statusLine = (state: GuidedLiveState, blockedReason: GuidedLiveBlockedReason | null): string => {
  if (blockedReason !== null) {
    return blockedLine(blockedReason);
  }

  switch (state.status) {
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
      return 'Done, but the GPU was not available, so the CPU wrote this. It is rougher than a GPU description.';
    case GUIDED_LIVE_STATUS.TIMED_OUT:
      return 'Stopped waiting. The run may still finish on its own; nothing was applied here.';
    case GUIDED_LIVE_STATUS.CANCELLED:
      return 'You stopped the wait. Nothing was applied.';
    case GUIDED_LIVE_STATUS.UNAVAILABLE:
      return state.reason === 'empty_description'
        ? 'The run finished with nothing to show. Nothing was applied.'
        : 'The live run could not finish. Nothing was applied.';
    default:
      return 'Ready when you are.';
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
  const { state, disclosure, blockedReason, canRequest, canCancel, request, cancel } = useGuidedLiveDescription({
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

      <p
        role="status"
        aria-live="polite"
        aria-label="Live run status"
        className={`acx-guided-live__status acx-guided-live__status--${state.status}`}
        data-testid="guided-live-status"
      >
        <span className="acx-guided-live__icon" aria-hidden="true" data-testid="guided-live-icon">
          {STATUS_ICON[state.status]}
        </span>{' '}
        {statusLine(state, blockedReason)}
      </p>

      {waiting ? (
        <p className="acx-guided-live__elapsed" data-testid="guided-live-elapsed">
          {clock(state.elapsedMs)} of up to {clock(state.deadlineMs)}
        </p>
      ) : null}

      <div className="acx-guided-live__actions">
        <button type="button" className="acx-button acx-button--secondary" onClick={request} disabled={!canRequest}>
          Describe it live
        </button>
        {canCancel ? (
          <button type="button" className="acx-button acx-button--tertiary" onClick={cancel}>
            Stop waiting
          </button>
        ) : null}
      </div>

      {state.text !== null ? (
        <blockquote className="acx-guided-live__text" data-testid="guided-live-text">
          {state.text}
        </blockquote>
      ) : null}
    </section>
  );
};
