import React, { useEffect, useRef } from 'react';

import { guidedCopy } from '../../guidedPrototype/copy';
import {
  GUIDED_LIVE_BRIEF_STATUS,
  GUIDED_LIVE_REASON,
  GUIDED_LIVE_STATUS,
  guidedLiveBriefStatus,
  isGuidedLiveWaiting,
} from '../../guidedPrototype/liveDescription';
import type {
  GuidedLiveBriefStatus,
  GuidedLiveState,
} from '../../guidedPrototype/liveDescription';
import { useGuidedLiveDescription } from '../../guidedPrototype/useGuidedLiveDescription';
import type { GuidedLiveDescriptionClient } from '../../guidedPrototype/useGuidedLiveDescription';

export interface GuidedLiveDescriptionPanelProps {
  mediaId: number | null;
  client?: GuidedLiveDescriptionClient;
  onWaitingChange?: (waiting: boolean) => void;
}

/** Every status carries a glyph as well as a colour ([A11Y-06] second channel always). */
const STATUS_ICON: Record<GuidedLiveBriefStatus, string> = {
  [GUIDED_LIVE_BRIEF_STATUS.UNAVAILABLE]: '×',
  [GUIDED_LIVE_BRIEF_STATUS.IDLE]: '•',
  [GUIDED_LIVE_BRIEF_STATUS.PENDING]: '…',
  [GUIDED_LIVE_BRIEF_STATUS.SUCCEEDED]: '✓',
  [GUIDED_LIVE_BRIEF_STATUS.FAILED]: '!',
  [GUIDED_LIVE_BRIEF_STATUS.TIMED_OUT]: '!',
  [GUIDED_LIVE_BRIEF_STATUS.STOPPED]: '×',
};

const STATUS_LINE_ID = 'guided-live-status-line';

const assertNever = (value: never): never => {
  throw new Error(`Unhandled guided live brief status: ${String(value)}`);
};

const clock = (ms: number): string => {
  const total = Math.max(0, Math.floor(ms / 1000));
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, '0')}`;
};

const timedOutStatus = (): string =>
  guidedCopy('live.timed_out', {
    keepWaiting: guidedCopy('live.keep_waiting'),
    retry: guidedCopy('live.retry'),
  });

const statusLine = (state: GuidedLiveState): string => {
  const brief = guidedLiveBriefStatus(state);
  switch (brief) {
    case GUIDED_LIVE_BRIEF_STATUS.UNAVAILABLE:
      return guidedCopy('live.request_unverified');
    case GUIDED_LIVE_BRIEF_STATUS.IDLE:
      return guidedCopy('live.request_confirmed');
    case GUIDED_LIVE_BRIEF_STATUS.PENDING:
      return guidedCopy('live.pending');
    case GUIDED_LIVE_BRIEF_STATUS.SUCCEEDED:
      return guidedCopy('live.complete');
    case GUIDED_LIVE_BRIEF_STATUS.FAILED:
      return state.reason === GUIDED_LIVE_REASON.EMPTY_DESCRIPTION
        ? guidedCopy('live.no_result')
        : guidedCopy('live.failed');
    case GUIDED_LIVE_BRIEF_STATUS.TIMED_OUT:
      return timedOutStatus();
    case GUIDED_LIVE_BRIEF_STATUS.STOPPED:
      return guidedCopy('live.stopped');
    default:
      return assertNever(brief);
  }
};

const elapsedLine = (state: GuidedLiveState): string =>
  state.runId === null
    ? clock(state.elapsedMs)
    : guidedCopy('live.elapsed_of_up_to', {
        elapsed: clock(state.elapsedMs),
        deadline: clock(state.deadlineMs),
      });

const budgetLine = (state: GuidedLiveState): string =>
  state.disclosedDeadlineSeconds === null
    ? guidedCopy('live.budget_local')
    : guidedCopy('live.budget_disclosed', {
        generation: clock(state.disclosedDeadlineSeconds * 1000),
        deadline: clock(state.deadlineMs),
      });

const actionLabel = (state: GuidedLiveState): string => {
  if (
    state.status === GUIDED_LIVE_STATUS.IDLE ||
    state.status === GUIDED_LIVE_STATUS.BLOCKED ||
    isGuidedLiveWaiting(state.status)
  ) {
    return guidedCopy('live.submit');
  }
  return guidedCopy('live.retry');
};

/**
 * Optional live generation, isolated from the recorded walkthrough. Never
 * writes the demo copy, the draft, or WordPress media.
 */
export const GuidedLiveDescriptionPanel = ({
  mediaId,
  client,
  onWaitingChange,
}: GuidedLiveDescriptionPanelProps): React.JSX.Element => {
  const { state, canRequest, canCancel, canKeepWaiting, request, cancel, keepWaiting } =
    useGuidedLiveDescription({ mediaId, client });

  const waiting = isGuidedLiveWaiting(state.status);
  const brief = guidedLiveBriefStatus(state);
  const verified = brief !== GUIDED_LIVE_BRIEF_STATUS.UNAVAILABLE;
  const onWaitingChangeRef = useRef(onWaitingChange);
  onWaitingChangeRef.current = onWaitingChange;

  useEffect(() => {
    onWaitingChangeRef.current?.(waiting);
  }, [waiting]);

  return (
    <details className="acx-guided-live" data-testid="guided-live">
      <summary id="guided-live-title">{guidedCopy('live.title')}</summary>

      <p className="acx-guided-live__intro">{guidedCopy('live.intro')}</p>

      <p className="acx-guided-live__naming" data-testid="guided-live-naming">
        {guidedCopy('live.names')}
      </p>

      {verified ? (
        <>
          <p className="acx-guided-live__confirmed">{guidedCopy('live.request_confirmed')}</p>
          <details className="acx-guided-live__details">
            <summary>{guidedCopy('live.details')}</summary>
            <p data-testid="guided-live-payload">{mediaId === null ? '' : String(mediaId)}</p>
            <p>{guidedCopy('live.output_label')}</p>
          </details>
        </>
      ) : null}

      <div
        role="status"
        aria-live="polite"
        aria-label={guidedCopy('live.status_label')}
        className="acx-guided-live__live"
      >
        <p
          id={STATUS_LINE_ID}
          className={`acx-guided-live__status acx-guided-live__status--${brief}`}
          data-testid="guided-live-status"
        >
          <span className="acx-guided-live__icon" aria-hidden="true" data-testid="guided-live-icon">
            {STATUS_ICON[brief]}
          </span>{' '}
          {statusLine(state)}
        </p>

        {waiting ? (
          <p className="acx-guided-live__elapsed" data-testid="guided-live-elapsed">
            {elapsedLine(state)}
          </p>
        ) : null}

        {waiting && state.runId !== null ? (
          <p className="acx-guided-live__budget" data-testid="guided-live-budget">
            {budgetLine(state)}
          </p>
        ) : null}

        {state.text !== null ? (
          <figure className="acx-guided-live__result">
            <figcaption>{guidedCopy('live.output_label')}</figcaption>
            <blockquote className="acx-guided-live__text" data-testid="guided-live-text">
              {state.text}
            </blockquote>
          </figure>
        ) : null}

        {canKeepWaiting ? (
          <div className="acx-guided-live__recovery">
            <button type="button" className="acx-button acx-button--secondary" onClick={keepWaiting}>
              {guidedCopy('live.keep_waiting')}
            </button>
            <button
              type="button"
              className="acx-button acx-button--tertiary"
              onClick={request}
              disabled={!canRequest}
              aria-describedby={STATUS_LINE_ID}
            >
              {guidedCopy('live.retry')}
            </button>
          </div>
        ) : null}
      </div>

      <div className="acx-guided-live__actions">
        {canKeepWaiting ? null : (
          <button
            type="button"
            className="acx-button acx-button--secondary"
            onClick={request}
            disabled={!canRequest}
            aria-describedby={canRequest ? undefined : STATUS_LINE_ID}
          >
            {actionLabel(state)}
          </button>
        )}
        {canCancel ? (
          <button type="button" className="acx-button acx-button--tertiary" onClick={cancel}>
            {guidedCopy('live.stop_waiting')}
          </button>
        ) : null}
      </div>
    </details>
  );
};
