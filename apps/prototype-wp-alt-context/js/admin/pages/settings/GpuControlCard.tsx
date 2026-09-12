import React from 'react';
import { __ } from '@wordpress/i18n';

import { GPU_STATE, GpuIntentAction, GpuIntentStatus, type GpuStatusResponse } from '../../api/gpuApi';
import { toWorkbench } from '../../navigation/appLinks';
import {
  GPU_STATE_ICON,
  GPU_STATE_TONE,
  GPU_STATE_VOCABULARY,
  gpuStatePresentation,
} from '../workbench/gpuStatePresentation';
import { getGpuControlPollInterval, useGpuControl } from './useGpuControl';

type ConfirmationAction = typeof GpuIntentAction.START | typeof GpuIntentAction.STOP;

const GPU_STATE_GLYPHS: Record<(typeof GPU_STATE_ICON)[keyof typeof GPU_STATE_ICON], string> = {
  [GPU_STATE_ICON.HELP]: '?',
  [GPU_STATE_ICON.STOPPED]: '■',
  [GPU_STATE_ICON.STARTING]: '◌',
  [GPU_STATE_ICON.WARMING]: '♨',
  [GPU_STATE_ICON.READY]: '⚡',
  [GPU_STATE_ICON.DEGRADED]: '⚠',
};

const formatDuration = (seconds: number): string => {
  const bounded = Math.max(0, Math.floor(seconds));
  if (bounded < 60) {
    return `${bounded} s`;
  }
  const minutes = Math.floor(bounded / 60);
  const remainder = bounded % 60;
  return remainder === 0 ? `${minutes} min` : `${minutes} min ${remainder} s`;
};

const stateToneClass = (tone: string): string => {
  switch (tone) {
    case GPU_STATE_TONE.SUCCESS:
      return 'acx-sync-status--success';
    case GPU_STATE_TONE.WARNING:
      return 'acx-sync-status--warning';
    case GPU_STATE_TONE.PENDING:
    case GPU_STATE_TONE.RUNNING:
      return 'acx-sync-status--info';
    case GPU_STATE_TONE.MUTED:
      return '';
    default:
      return '';
  }
};

const relativeAge = (seconds: number | null): string | null => {
  if (seconds === null || !Number.isFinite(seconds) || seconds < 0) {
    return null;
  }
  return formatDuration(seconds);
};

const secondsSinceServerTime = (serverTime: string, epochSeconds: number | null): number | null => {
  if (epochSeconds === null || !Number.isFinite(epochSeconds)) {
    return null;
  }
  const serverMilliseconds = Date.parse(serverTime);
  if (!Number.isFinite(serverMilliseconds)) {
    return null;
  }
  return Math.max(0, serverMilliseconds / 1000 - epochSeconds);
};

const formatClock = (value: string | null): string | null => {
  if (value === null) {
    return null;
  }
  const milliseconds = Date.parse(value);
  if (!Number.isFinite(milliseconds)) {
    return null;
  }
  return new Date(milliseconds).toISOString().slice(11, 19);
};

const formatWarmupEta = (data: GpuStatusResponse): string => {
  const elapsed = secondsSinceServerTime(data.server_time, data.gpu_state.since);
  const remaining = elapsed === null ? 120 : Math.max(0, 120 - elapsed);
  const pollSeconds = Math.round(getGpuControlPollInterval(data) / 1000);
  return `Warming… about ${formatDuration(remaining)} left · polling every ${pollSeconds} s`;
};

const intentLabel = (data: GpuStatusResponse): string => {
  const { intent, intent_status: intentStatus } = data.gpu_state;
  if (intentStatus === GpuIntentStatus.BLOCKED_WORK_IN_FLIGHT) {
    return 'Stop pending — a describe run is in flight; the GPU stops when it ends.';
  }
  if (intent === GpuIntentAction.AUTO) {
    return data.snapshot_fresh
      ? 'Automatic — starts when a describe run needs it, stops after idle.'
      : 'Automatic (from last snapshot) — starts when a describe run needs it, stops after idle.';
  }
  if (intent === GpuIntentAction.START) {
    const expiresAt = formatClock(data.gpu_state.intent_expires_at ?? data.intent?.expires_at ?? null);
    const requestedAt = formatClock(data.intent?.requested_at ?? null);
    const until = expiresAt ? ` until ${expiresAt.slice(0, 5)}` : '';
    const honoured = intentStatus === GpuIntentStatus.HONOURED && requestedAt ? ` · honoured ${requestedAt}` : '';
    const pending = intentStatus === GpuIntentStatus.PENDING ? ' (pending)' : '';
    return `Start requested${until}${pending}${honoured}`;
  }
  return intentStatus === GpuIntentStatus.PENDING ? 'Stop requested (pending)' : 'Stop requested';
};

const leaseLabel = (data: GpuStatusResponse): string => {
  const runningSince = formatClock(data.gpu_state.instance_running_since);
  const expiresAt = formatClock(data.gpu_state.lease_expires_at);
  if (!runningSince) {
    return 'Lease: —';
  }
  return expiresAt
    ? `Lease: running since ${runningSince} · auto-stops by ${expiresAt.slice(0, 5)} (lease cap)`
    : `Lease: running since ${runningSince}`;
};

const loadAgeLabel = (data: GpuStatusResponse): string => {
  const age = relativeAge(secondsSinceServerTime(data.server_time, data.load.written_at));
  if (!age) {
    return 'load snapshot age unavailable';
  }
  return `load snapshot ${age} ago${data.load.fresh ? '' : ' (stale)'}`;
};

const startDisabledReason = (data: GpuStatusResponse): string => {
  switch (data.gpu_state.state) {
    case GPU_STATE.STOPPED:
      return 'already stopped';
    case GPU_STATE.STARTING:
      return 'already starting';
    case GPU_STATE.WARMING:
      return 'already warming';
    case GPU_STATE.READY:
      return 'already running';
    case GPU_STATE.DEGRADED:
      return data.gpu_state.intent === GpuIntentAction.START ? 'already requested' : '';
    case GPU_STATE.UNKNOWN:
      return data.gpu_state.intent === GpuIntentAction.START ? 'already requested' : '';
    default: {
      const unreachable: never = data.gpu_state.state;
      return unreachable;
    }
  }
};

const errorCopy = (error: unknown): string => {
  const message = error instanceof Error ? error.message : '';
  return message.includes('502')
    ? 'Could not reach the description service (502). Retrying in 15 s.'
    : 'Could not reach the description service. Retrying in 15 s.';
};

export const GpuControlCard = (): React.JSX.Element => {
  const {
    data,
    isLoading,
    isError,
    error,
    refetch,
    canStart,
    canStop,
    stopBlockedReason,
    canReturnToAuto,
    requestIntent,
    isIntentPending,
  } = useGpuControl();
  const [confirmation, setConfirmation] = React.useState<ConfirmationAction | null>(null);
  const displayedState = data && data.snapshot_fresh ? data.gpu_state.state : GPU_STATE.UNKNOWN;

  const confirm = (): void => {
    if (confirmation === null) {
      return;
    }
    requestIntent(confirmation);
    setConfirmation(null);
  };

  return (
    <section className="acx-target-card acx-gpu-control" aria-labelledby="acx-gpu-control-title">
      <h3 id="acx-gpu-control-title" className="acx-settings__section-title">
        {__('Settings › Burst GPU', 'alt-context')}
      </h3>

      <div
        id="z-gpu-state-chip"
        data-testid="z-gpu-state-chip"
        className="acx-sync-status acx-gpu-control__state-chip"
        role="status"
        aria-live="polite"
        aria-atomic="true"
      >
        {isLoading && !data ? <span>{__('Loading GPU status…', 'alt-context')}</span> : null}
        {isError ? <span className="notice-error">{errorCopy(error)}</span> : null}
        {data
          ? (() => {
              const presentation = gpuStatePresentation(displayedState);
              const age = relativeAge(data.snapshot_age_seconds);
              const snapshotText = data.snapshot_fresh
                ? age
                  ? `snapshot ${age} ago`
                  : 'snapshot age unavailable'
                : age
                  ? `last snapshot ${age} ago (stale)`
                  : 'last snapshot age unavailable (stale)';
              return (
                <span data-tone={presentation.tone} className={stateToneClass(presentation.tone)}>
                  <span aria-hidden="true" className="acx-gpu-control__state-icon">
                    {GPU_STATE_GLYPHS[presentation.icon]}
                  </span>{' '}
                  <span>{`${GPU_STATE_VOCABULARY.tierPrefix} ${presentation.label}`}</span>
                  {` · ${snapshotText}`}
                </span>
              );
            })()
          : null}
      </div>

      {data ? (
        <>
          <div id="z-gpu-intent" data-testid="z-gpu-intent" className="acx-gpu-control__row">
            <strong>{__('Intent:', 'alt-context')}</strong> {intentLabel(data)}
          </div>
          <div id="z-gpu-lease" data-testid="z-gpu-lease" className="acx-gpu-control__row">
            {leaseLabel(data)}
          </div>
          <div id="z-gpu-load" data-testid="z-gpu-load" className="acx-gpu-control__row">
            <strong>{__('Load:', 'alt-context')}</strong>{' '}
            {data.load.has_work ? __('describe run in flight', 'alt-context') : __('no work in flight', 'alt-context')}{' '}
            ({loadAgeLabel(data)})
          </div>
          <div id="z-gpu-cost" data-testid="z-gpu-cost" className="acx-gpu-control__row">
            {__('Cost: ≈$2.00 / GPU-hour · warm-up ≈2 min · never runs longer than the 60 min cap', 'alt-context')}
          </div>

          {!data.snapshot_fresh ? (
            <p className="notice inline notice-warning" data-testid="gpu-stale-notice">
              {__(
                'Lifecycle telemetry is stale. Refresh before starting the GPU. Stop and automatic requests may be delayed.',
                'alt-context',
              )}
            </p>
          ) : null}

          {displayedState === GPU_STATE.STARTING || displayedState === GPU_STATE.WARMING ? (
            <p data-testid="gpu-warmup-eta">{formatWarmupEta(data)}</p>
          ) : null}

          <div id="z-gpu-controls" data-testid="z-gpu-controls" className="acx-gpu-control__actions">
            <button
              type="button"
              className="acx-button acx-button--primary"
              onClick={() => setConfirmation(GpuIntentAction.START)}
              disabled={!canStart || isIntentPending}
            >
              <span aria-hidden="true">▶</span> {__('Start GPU', 'alt-context')}
            </button>
            {!canStart && startDisabledReason(data) ? <span>disabled: {startDisabledReason(data)}</span> : null}

            <button
              type="button"
              className="acx-button acx-button--secondary"
              onClick={() => setConfirmation(GpuIntentAction.STOP)}
              disabled={!canStop || isIntentPending}
            >
              <span aria-hidden="true">■</span> {__('Stop GPU', 'alt-context')}
            </button>
            {!canStop && stopBlockedReason ? <span>disabled: {stopBlockedReason}</span> : null}

            {canReturnToAuto ? (
              <button
                type="button"
                className="acx-button acx-button--secondary"
                onClick={() => requestIntent(GpuIntentAction.AUTO)}
                disabled={isIntentPending}
              >
                <span aria-hidden="true">↺</span> {__('Return to automatic', 'alt-context')}
              </button>
            ) : null}

            {displayedState === GPU_STATE.READY ? (
              <a className="acx-button acx-button--secondary" href={toWorkbench()}>
                <span aria-hidden="true">→</span> {__('Go to Workbench', 'alt-context')}
              </a>
            ) : null}

            <button type="button" className="acx-button acx-button--tertiary" onClick={() => void refetch()}>
              <span aria-hidden="true">↻</span> {__('Refresh', 'alt-context')}
            </button>
          </div>

          {confirmation === GpuIntentAction.START ? (
            <div id="z-start-preview" data-testid="z-start-preview" className="notice inline notice-warning">
              <p>
                {__(
                  'Starts the A10 now (≈$2.00/h). Ready in about 2 min. Returns to automatic after 30 min unless work keeps it busy; the 60 min lease cap still applies.',
                  'alt-context',
                )}
              </p>
              <div id="z-start-actions" data-testid="z-start-actions">
                <button
                  type="button"
                  className="acx-button acx-button--primary"
                  onClick={confirm}
                  disabled={isIntentPending}
                >
                  {__('Confirm start', 'alt-context')}
                </button>{' '}
                <button
                  type="button"
                  className="acx-button acx-button--secondary"
                  onClick={() => setConfirmation(null)}
                  disabled={isIntentPending}
                >
                  {__('Cancel', 'alt-context')}
                </button>
              </div>
            </div>
          ) : null}

          {confirmation === GpuIntentAction.STOP ? (
            <div id="z-stop-preview" data-testid="z-stop-preview" className="notice inline notice-warning">
              <p>
                {__(
                  'Requests shutdown when idle. If a describe run is in flight, shutdown is deferred. The separate lease cap can still stop the GPU to limit costs.',
                  'alt-context',
                )}
              </p>
              <div id="z-stop-actions" data-testid="z-stop-actions">
                <button
                  type="button"
                  className="acx-button acx-button--primary"
                  onClick={confirm}
                  disabled={isIntentPending}
                >
                  {__('Confirm stop', 'alt-context')}
                </button>{' '}
                <button
                  type="button"
                  className="acx-button acx-button--secondary"
                  onClick={() => setConfirmation(null)}
                  disabled={isIntentPending}
                >
                  {__('Cancel', 'alt-context')}
                </button>
              </div>
            </div>
          ) : null}
        </>
      ) : null}

      {isError ? (
        <button type="button" className="acx-button acx-button--secondary" onClick={() => void refetch()}>
          {__('Retry', 'alt-context')}
        </button>
      ) : null}
    </section>
  );
};
