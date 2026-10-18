import React from 'react';
import { __, sprintf } from '@wordpress/i18n';
import { AlertTriangle } from 'lucide-react';

import { GPU_STATE, GpuIntentAction, GpuIntentStatus, type GpuStatusResponse } from '../../api/gpuApi';
import { toWorkbench } from '../../navigation/appLinks';
import { toUserMessage } from '../../utils/appError';
import {
  readUnavailable,
  unavailableReasonCopy,
  unavailableServiceLabel,
} from '../../utils/serviceUnavailable';
import { GPU_STATE_ICON, GPU_STATE_TONE, gpuStatePresentation } from '../workbench/gpuStatePresentation';
import { useGpuControl } from './useGpuControl';

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

const formatClock = (value: string | number | null): string | null => {
  if (value === null) {
    return null;
  }
  const milliseconds = typeof value === 'number' ? value : Date.parse(value);
  if (!Number.isFinite(milliseconds)) {
    return null;
  }
  return new Date(milliseconds).toISOString().slice(11, 19);
};

const toOperatorReason = (reason: string | null | undefined): string | null => {
  if (!reason) {
    return null;
  }
  return reason
    .replace(/GPU/g, 'service')
    .replace('service state is unknown', 'Service state is unknown')
    .replace('Lifecycle telemetry is stale', 'Service status is out of date');
};

const intentLabel = (data: GpuStatusResponse): string => {
  const { intent, intent_status: intentStatus } = data.gpu_state;
  if (
    intentStatus === GpuIntentStatus.BLOCKED_WORK_IN_FLIGHT ||
    (intent === GpuIntentAction.STOP && data.load.has_work)
  ) {
    return 'Stopping after the current work finishes until idle';
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
    return 'Run limit: —';
  }
  return expiresAt
    ? `Run limit: running since ${runningSince} · auto-stops by ${expiresAt.slice(0, 5)} (service run limit)`
    : `Run limit: running since ${runningSince}`;
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

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value);

const errorHttpDetails = (error: unknown): { status: number | null; code: string | null } => {
  if (!isRecord(error)) {
    return { status: null, code: null };
  }

  let status = typeof error.status === 'number' && Number.isFinite(error.status) ? error.status : null;
  let code = typeof error.code === 'string' && error.code.trim() !== '' ? error.code : null;
  if (isRecord(error.data)) {
    if (status === null && typeof error.data.status === 'number' && Number.isFinite(error.data.status)) {
      status = error.data.status;
    }
    if (code === null && typeof error.data.code === 'string' && error.data.code.trim() !== '') {
      code = error.data.code;
    }
  }

  if (typeof error.bodyPreview === 'string') {
    try {
      const payload: unknown = JSON.parse(error.bodyPreview);
      if (isRecord(payload)) {
        if (code === null && typeof payload.code === 'string' && payload.code.trim() !== '') {
          code = payload.code;
        }
        if (isRecord(payload.data)) {
          if (status === null && typeof payload.data.status === 'number' && Number.isFinite(payload.data.status)) {
            status = payload.data.status;
          }
          if (code === null && typeof payload.data.code === 'string' && payload.data.code.trim() !== '') {
            code = payload.data.code;
          }
        }
      }
    } catch {
      // Non-JSON bodies (for example, a proxy error page) do not carry a WP_Error code.
    }
  }

  return { status, code };
};

const errorCauseCopy = (error: unknown): string => {
  const { status, code } = errorHttpDetails(error);
  if (status !== null && code !== null) {
    return sprintf(__('HTTP %1$d (%2$s)', 'alt-context'), status, code);
  }
  if (status !== null) {
    return sprintf(__('HTTP %d', 'alt-context'), status);
  }
  if (code !== null) {
    return sprintf(__('WordPress error: %s', 'alt-context'), code);
  }
  return toUserMessage(error, __('The request could not be completed. Check Settings and the service logs.', 'alt-context'));
};

const pollCountdownSeconds = (pollIntervalMs: number | false): number | null => {
  if (typeof pollIntervalMs !== 'number' || !Number.isFinite(pollIntervalMs) || pollIntervalMs <= 0) {
    return null;
  }
  return Math.ceil(pollIntervalMs / 1000);
};

const intentFailureCopy = (
  action: typeof GpuIntentAction.START | typeof GpuIntentAction.STOP | typeof GpuIntentAction.AUTO | null,
  error: unknown,
): string | null => {
  if (error == null || readUnavailable(error) !== null) {
    return null;
  }
  switch (action) {
    case GpuIntentAction.START:
      return __('Start request failed', 'alt-context');
    case GpuIntentAction.STOP:
      return __('Stop request failed', 'alt-context');
    default:
      return null;
  }
};

const retryCountdownSeconds = (retryAfterSeconds: number | null): number | null => {
  if (retryAfterSeconds === null || !Number.isFinite(retryAfterSeconds) || retryAfterSeconds <= 0) {
    return null;
  }
  return Math.floor(retryAfterSeconds);
};

export const GpuControlCard = (): React.JSX.Element => {
  const {
    data,
    isLoading,
    isFetching,
    isError,
    error,
    errorUpdatedAt,
    dataUpdatedAt,
    pollIntervalMs,
    refetch,
    canStart,
    startBlockedReason,
    canStop,
    stopBlockedReason,
    canReturnToAuto,
    requestIntent,
    isIntentPending,
    intentError,
  } = useGpuControl();
  const [confirmation, setConfirmation] = React.useState<ConfirmationAction | null>(null);
  const [clearedConfirmationReason, setClearedConfirmationReason] = React.useState<string | null>(null);
  const [lastIntentAction, setLastIntentAction] = React.useState<
    typeof GpuIntentAction.START | typeof GpuIntentAction.STOP | typeof GpuIntentAction.AUTO | null
  >(null);
  const startHeld = !canStart || isIntentPending;
  const stopHeld = !canStop || isIntentPending;
  const pendingReason = isIntentPending ? __('a service request is already in flight', 'alt-context') : null;
  const startReason = startHeld
    ? pendingReason ||
      toOperatorReason(startBlockedReason) ||
      (data && startDisabledReason(data)) ||
      __('Service start is unavailable', 'alt-context')
    : null;
  const stopReason = !canStop ? stopBlockedReason : pendingReason;
  const displayedState = data && data.snapshot_fresh ? data.gpu_state.state : GPU_STATE.UNKNOWN;
  const unavailable = readUnavailable(data) ?? readUnavailable(intentError) ?? readUnavailable(error);
  const unavailableService = unavailable ? unavailableServiceLabel(unavailable.service) : null;
  const unavailableCopy = unavailable ? unavailableReasonCopy(unavailable.reason) : null;
  const lastChecked = unavailable ? formatClock(unavailable.checked_at) : null;
  const retryInSeconds = unavailable ? retryCountdownSeconds(unavailable.retry_after_seconds) : null;
  const errorLastChecked = formatClock(errorUpdatedAt > 0 ? errorUpdatedAt : dataUpdatedAt > 0 ? dataUpdatedAt : null);
  const errorRetryInSeconds = pollCountdownSeconds(pollIntervalMs);
  const intentFailureNotice = intentFailureCopy(lastIntentAction, intentError);

  const submitIntent = (
    action: typeof GpuIntentAction.START | typeof GpuIntentAction.STOP | typeof GpuIntentAction.AUTO,
  ): void => {
    setLastIntentAction(action);
    requestIntent(action);
  };

  React.useEffect(() => {
    if (confirmation === null) {
      return;
    }
    const selectedStillAllowed = confirmation === GpuIntentAction.START ? canStart : canStop;
    if (selectedStillAllowed) {
      return;
    }
    const reason =
      confirmation === GpuIntentAction.START
        ? toOperatorReason(startBlockedReason) ||
          (data ? startDisabledReason(data) : null) ||
          __('Service start is unavailable', 'alt-context')
        : stopBlockedReason || __('Service stop is unavailable', 'alt-context');
    setClearedConfirmationReason(reason);
    setConfirmation(null);
  }, [confirmation, canStart, canStop, startBlockedReason, stopBlockedReason, data]);

  const confirm = (): void => {
    const action = confirmation;
    if (action === GpuIntentAction.START && canStart) {
      submitIntent(action);
    } else if (action === GpuIntentAction.STOP && canStop) {
      submitIntent(action);
    }
    setConfirmation(null);
  };

  const refreshControl = (
    <button
      type="button"
      className="acx-button acx-button--tertiary"
      onClick={() => void refetch()}
      disabled={isFetching}
      aria-busy={isFetching}
    >
      <span aria-hidden="true">↻</span> {__('Refresh', 'alt-context')}
    </button>
  );

  const retryControl = (
    <button
      type="button"
      className="acx-button acx-button--tertiary"
      onClick={() => void refetch()}
      disabled={isFetching}
      aria-busy={isFetching}
    >
      {isFetching ? __('Fetching…', 'alt-context') : __('Retry', 'alt-context')}
    </button>
  );

  return (
    <section className="acx-target-card acx-gpu-control" aria-labelledby="acx-gpu-control-title">
      <h3 id="acx-gpu-control-title" className="acx-settings__section-title">
        {__('Settings › Description Service', 'alt-context')}
      </h3>

      <div
        id="z-gpu-state-chip"
        data-testid="z-gpu-state-chip"
        className="acx-sync-status acx-gpu-control__state-chip"
        role="status"
        aria-live="polite"
        aria-atomic="true"
      >
        {isLoading && !data ? <span>{__('Loading service status…', 'alt-context')}</span> : null}
        {unavailable && unavailableService && unavailableCopy ? (
          <span
            data-testid="gpu-unavailable-status"
            data-tone={GPU_STATE_TONE.WARNING}
            className={stateToneClass(GPU_STATE_TONE.WARNING)}
          >
            <span aria-hidden="true" className="acx-gpu-control__state-icon" data-testid="gpu-unavailable-icon">
              {GPU_STATE_GLYPHS[GPU_STATE_ICON.DEGRADED]}
            </span>{' '}
            <span>
              {sprintf(
                __('%s is unavailable because %s.', 'alt-context'),
                unavailableService,
                unavailableCopy.why,
              )}
            </span>{' '}
            <span>{unavailableCopy.fix}</span>
            {lastChecked ? (
              <>
                {' '}
                <span>{sprintf(__('Last checked %s', 'alt-context'), lastChecked)}</span>
              </>
            ) : null}
            {retryInSeconds !== null ? (
              <>
                {' '}
                <span>{sprintf(__('Retry in %d s', 'alt-context'), retryInSeconds)}</span>
              </>
            ) : null}
            {isFetching ? (
              <>
                {' '}
                <span>{__('Checking service status…', 'alt-context')}</span>
              </>
            ) : null}
          </span>
        ) : isError ? (
          <span
            data-testid="gpu-control-error-status"
            data-tone={GPU_STATE_TONE.WARNING}
            className={stateToneClass(GPU_STATE_TONE.WARNING)}
          >
            <AlertTriangle
              className="acx-gpu-control__state-icon"
              size={16}
              aria-hidden="true"
              data-testid="gpu-control-error-icon"
            />{' '}
            <span>{__('Description Service (GPU control) unavailable', 'alt-context')}</span>{' '}
            <span>{sprintf(__('Cause: %s', 'alt-context'), errorCauseCopy(error))}</span>
            {errorLastChecked ? (
              <>
                {' '}
                <span>{sprintf(__('Last checked %s', 'alt-context'), errorLastChecked)}</span>
              </>
            ) : null}
            {errorRetryInSeconds !== null ? (
              <>
                {' '}
                <span>{sprintf(__('Retrying in %d s', 'alt-context'), errorRetryInSeconds)}</span>
              </>
            ) : null}
            {isFetching ? (
              <>
                {' '}
                <span>{__('Checking service status…', 'alt-context')}</span>
              </>
            ) : null}
          </span>
        ) : null}
        {intentFailureNotice ? (
          <span className="notice-error" role="alert" data-testid="gpu-intent-failure">
            <AlertTriangle
              className="acx-gpu-control__state-icon"
              size={16}
              aria-hidden="true"
              data-testid="gpu-intent-failure-icon"
            />{' '}
            <span>{intentFailureNotice}</span>
          </span>
        ) : null}
        {clearedConfirmationReason ? (
          <span data-testid="gpu-confirmation-cleared-reason">{clearedConfirmationReason}</span>
        ) : null}
        {data && !unavailable
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
                  <span>{`${__('Service:', 'alt-context')} ${presentation.label}`}</span>
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
            {__(
              'Cost: ≈$2.00 / service-hour · warm-up ≈2 min · never runs longer than the 60-minute maximum',
              'alt-context',
            )}
          </div>

          {!data.snapshot_fresh ? (
            <p className="notice inline notice-warning" data-testid="gpu-stale-notice">
              {__(
                'Service status is out of date. Refresh before starting the service. ' +
                  'Stop and automatic requests may be delayed.',
                'alt-context',
              )}
            </p>
          ) : null}

          {displayedState === GPU_STATE.STARTING || displayedState === GPU_STATE.WARMING ? (
            <p data-testid="gpu-warmup-eta">{__('Warming up, this can take a few minutes', 'alt-context')}</p>
          ) : null}

          <div id="z-gpu-controls" data-testid="z-gpu-controls" className="acx-gpu-control__actions">
            {displayedState !== GPU_STATE.UNKNOWN ? (
              <>
                <button
                  type="button"
                  className="acx-button acx-button--primary"
                  onClick={() => {
                    if (!startHeld) {
                      setClearedConfirmationReason(null);
                      setConfirmation(GpuIntentAction.START);
                    }
                  }}
                  aria-disabled={startHeld ? true : undefined}
                  aria-describedby={startReason ? 'z-gpu-start-reason' : undefined}
                >
                  <span aria-hidden="true">▶</span> {__('Start service', 'alt-context')}
                </button>
                {startReason ? <span id="z-gpu-start-reason">disabled: {startReason}</span> : null}

                <button
                  type="button"
                  className="acx-button acx-button--secondary"
                  onClick={() => {
                    if (!stopHeld) {
                      setClearedConfirmationReason(null);
                      setConfirmation(GpuIntentAction.STOP);
                    }
                  }}
                  aria-disabled={stopHeld ? true : undefined}
                  aria-describedby={stopReason ? 'z-gpu-stop-reason' : undefined}
                >
                  <span aria-hidden="true">■</span> {__('Stop service', 'alt-context')}
                </button>
                {stopReason ? <span id="z-gpu-stop-reason">disabled: {stopReason}</span> : null}

                {displayedState === GPU_STATE.READY ? (
                  <a className="acx-button acx-button--secondary" href={toWorkbench()}>
                    <span aria-hidden="true">→</span> {__('Go to Workbench', 'alt-context')}
                  </a>
                ) : null}
              </>
            ) : null}

            {canReturnToAuto ? (
              <button
                type="button"
                className="acx-button acx-button--secondary"
                onClick={() => submitIntent(GpuIntentAction.AUTO)}
                disabled={isIntentPending}
              >
                <span aria-hidden="true">↺</span> {__('Return to automatic', 'alt-context')}
              </button>
            ) : null}

            {refreshControl}
          </div>

          {confirmation === GpuIntentAction.START ? (
            <div id="z-start-preview" data-testid="z-start-preview" className="notice inline notice-warning">
              <p>
                {__(
                  'Starts the description service now (≈$2.00/h). Ready in about 2 min. ' +
                    'Returns to automatic after 30 min unless work keeps it busy; the 60-minute maximum still applies.',
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
                {data.load.has_work
                  ? __('Stop after the current run finishes?', 'alt-context')
                  : __(
                      'Requests shutdown when idle. If a describe run is in flight, shutdown is deferred. ' +
                        'The service run limit can still stop the service to limit costs.',
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

      {isError && !data ? (
        <div id="z-gpu-controls" data-testid="z-gpu-controls" className="acx-gpu-control__actions">
          {unavailable ? retryControl : refreshControl}
        </div>
      ) : null}
    </section>
  );
};
