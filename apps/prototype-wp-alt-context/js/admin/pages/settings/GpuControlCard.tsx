import React from 'react';
import { __, sprintf } from '@wordpress/i18n';

import { GPU_STATE, GpuIntentAction, GpuIntentStatus, type GpuStatusResponse } from '../../api/gpuApi';
import { toWorkbench } from '../../navigation/appLinks';
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

const errorCopy = (error: unknown): string => {
  const message = error instanceof Error ? error.message : '';
  return message.includes('502')
    ? 'Could not reach the description service (502). Retrying in 15 s.'
    : 'Could not reach the description service. Retrying in 15 s.';
};

const UNAVAILABLE_REASON = {
  NOT_CONFIGURED: 'not_configured',
  API_KEY_MISSING: 'api_key_missing',
  CIRCUIT_OPEN: 'circuit_open',
  UPSTREAM_5XX: 'upstream_5xx',
  UPSTREAM_4XX: 'upstream_4xx',
  TIMEOUT: 'timeout',
  CONTRACT_MISMATCH: 'contract_mismatch',
} as const;

const UNAVAILABLE_SERVICE = {
  RECOGNITION: 'recognition',
  SCENE: 'scene',
} as const;

interface ServiceUnavailable {
  reason: string;
  service: string;
  http_status: number | null;
  retry_after_seconds: number | null;
  checked_at: string;
}

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value);

const parseUnavailable = (value: unknown): ServiceUnavailable | null => {
  if (!isRecord(value)) {
    return null;
  }
  if (typeof value.reason !== 'string' || value.reason.trim() === '') {
    return null;
  }
  if (typeof value.service !== 'string' || value.service.trim() === '') {
    return null;
  }
  if (value.http_status !== null && value.http_status !== undefined) {
    if (typeof value.http_status !== 'number' || !Number.isFinite(value.http_status)) {
      return null;
    }
  }
  if (value.retry_after_seconds !== null && value.retry_after_seconds !== undefined) {
    if (typeof value.retry_after_seconds !== 'number' || !Number.isFinite(value.retry_after_seconds)) {
      return null;
    }
  }
  if (typeof value.checked_at !== 'string' || value.checked_at.trim() === '') {
    return null;
  }
  return {
    reason: value.reason,
    service: value.service,
    http_status: typeof value.http_status === 'number' ? value.http_status : null,
    retry_after_seconds: typeof value.retry_after_seconds === 'number' ? value.retry_after_seconds : null,
    checked_at: value.checked_at,
  };
};

const readUnavailable = (source: unknown): ServiceUnavailable | null => {
  if (!isRecord(source)) {
    return null;
  }
  const direct = parseUnavailable(source.unavailable);
  if (direct) {
    return direct;
  }
  if (typeof source.bodyPreview !== 'string') {
    return null;
  }
  try {
    const parsed: unknown = JSON.parse(source.bodyPreview);
    if (!isRecord(parsed)) {
      return null;
    }
    const fromRoot = parseUnavailable(parsed.unavailable);
    if (fromRoot) {
      return fromRoot;
    }
    return isRecord(parsed.data) ? parseUnavailable(parsed.data.unavailable) : null;
  } catch {
    return null;
  }
};

const unavailableServiceLabel = (service: string): string => {
  switch (service) {
    case UNAVAILABLE_SERVICE.RECOGNITION:
      return __('Recognition service', 'alt-context');
    case UNAVAILABLE_SERVICE.SCENE:
      return __('Description service', 'alt-context');
    default:
      return __('Service', 'alt-context');
  }
};

const unavailableReasonCopy = (reason: string): { why: string; fix: string } => {
  switch (reason) {
    case UNAVAILABLE_REASON.NOT_CONFIGURED:
      return {
        why: __('it is not configured', 'alt-context'),
        fix: __('Set the API URL in Settings.', 'alt-context'),
      };
    case UNAVAILABLE_REASON.API_KEY_MISSING:
      return {
        why: __('the API key is missing', 'alt-context'),
        fix: __('Add the API key in Settings.', 'alt-context'),
      };
    case UNAVAILABLE_REASON.CIRCUIT_OPEN:
      return {
        why: __('the circuit breaker is open', 'alt-context'),
        fix: __('Wait for the cooldown, then Retry.', 'alt-context'),
      };
    case UNAVAILABLE_REASON.UPSTREAM_5XX:
      return {
        why: __('it returned a server error', 'alt-context'),
        fix: __('Retry in a moment. If it continues, check the service logs.', 'alt-context'),
      };
    case UNAVAILABLE_REASON.UPSTREAM_4XX:
      return {
        why: __('it rejected the request', 'alt-context'),
        fix: __('Check the API URL and key in Settings.', 'alt-context'),
      };
    case UNAVAILABLE_REASON.TIMEOUT:
      return {
        why: __('it did not respond in time', 'alt-context'),
        fix: __('Retry. If it continues, check that the host is reachable.', 'alt-context'),
      };
    case UNAVAILABLE_REASON.CONTRACT_MISMATCH:
      return {
        why: __('it returned a response this plugin does not recognize', 'alt-context'),
        fix: __('Confirm the plugin and service are on compatible versions.', 'alt-context'),
      };
    default:
      return {
        why: sprintf(__('an unexpected error occurred (%s)', 'alt-context'), reason),
        fix: __('Retry. If it continues, check Settings and the service logs.', 'alt-context'),
      };
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
    refetch,
    canStart,
    startBlockedReason,
    canStop,
    stopBlockedReason,
    canReturnToAuto,
    requestIntent,
    isIntentPending,
  } = useGpuControl();
  const [confirmation, setConfirmation] = React.useState<ConfirmationAction | null>(null);
  const [clearedConfirmationReason, setClearedConfirmationReason] = React.useState<string | null>(null);
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
  const unavailable = readUnavailable(data) ?? readUnavailable(error);
  const unavailableService = unavailable ? unavailableServiceLabel(unavailable.service) : null;
  const unavailableCopy = unavailable ? unavailableReasonCopy(unavailable.reason) : null;
  const lastChecked = unavailable ? formatClock(unavailable.checked_at) : null;
  const retryInSeconds = unavailable ? retryCountdownSeconds(unavailable.retry_after_seconds) : null;

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
      requestIntent(action);
    } else if (action === GpuIntentAction.STOP && canStop) {
      requestIntent(action);
    }
    setConfirmation(null);
  };

  const refreshControl = (
    <button
      type="button"
      className="acx-button acx-button--tertiary"
      onClick={() => void refetch()}
      disabled={isFetching}
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
          <span className="notice-error">{errorCopy(error)}</span>
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
                onClick={() => requestIntent(GpuIntentAction.AUTO)}
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
