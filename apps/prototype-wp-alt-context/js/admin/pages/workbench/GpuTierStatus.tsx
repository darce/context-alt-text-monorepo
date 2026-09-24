/**
 * Always-visible Description Service status chip (GPUFLOW-2 A8).
 *
 * Idle polls `GET gpu/status`; an in-flight run's `gpu_state` wins. Copy names
 * what Describe will do next (INT-10, HAI-18, OBS-08). Wait figures come from
 * the service (`warmup_eta_seconds` / `startup_budget_seconds`) or are omitted
 * (rg-015). Icon + tokenized tone, never colour alone (sr-004).
 */
import { useEffect, useRef, useState, type JSX } from 'react';
import { AlertTriangle, CircleHelp, CircleStop, Flame, Loader2, Zap } from 'lucide-react';
import { __, sprintf } from '@wordpress/i18n';

import { GPU_STATE, type GpuState } from '../../api/describeApi';
import { useGpuServiceStatus } from '../../hooks/useGpuServiceStatus';
import {
  GPU_STATE_ICON,
  GPU_STATE_TONE,
  gpuStatePresentation,
  type GpuStateIcon,
  type GpuStateTone,
} from './gpuStatePresentation';

export const GPU_IDLE_STATUS_ACTION = {
  NONE: 'none',
  REFRESH: 'refresh',
  RETRY: 'retry',
} as const;

export type GpuIdleStatusAction = (typeof GPU_IDLE_STATUS_ACTION)[keyof typeof GPU_IDLE_STATUS_ACTION];

const GPU_STATE_ICON_COMPONENT = {
  [GPU_STATE_ICON.HELP]: CircleHelp,
  [GPU_STATE_ICON.STOPPED]: CircleStop,
  [GPU_STATE_ICON.STARTING]: Loader2,
  [GPU_STATE_ICON.WARMING]: Flame,
  [GPU_STATE_ICON.READY]: Zap,
  [GPU_STATE_ICON.DEGRADED]: AlertTriangle,
} satisfies Record<GpuStateIcon, typeof CircleHelp>;

const gpuStateToneClass = (tone: GpuStateTone): string => {
  switch (tone) {
    case GPU_STATE_TONE.SUCCESS:
      return ' acx-sync-status--success';
    case GPU_STATE_TONE.WARNING:
      return ' acx-sync-status--warning';
    case GPU_STATE_TONE.PENDING:
    case GPU_STATE_TONE.RUNNING:
      return ' acx-sync-status--info';
    case GPU_STATE_TONE.MUTED:
      return '';
    default: {
      const unreachable: never = tone;
      return unreachable;
    }
  }
};

const isPlainObject = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value);

/** Schema `warmup_eta_seconds`: finite, including 0. `-0` normalizes to `0`. */
const finiteEtaSeconds = (value: unknown): number | undefined => {
  if (typeof value !== 'number' || !Number.isFinite(value) || value < 0) {
    return undefined;
  }
  return value === 0 ? 0 : value;
};

/** Schema `startup_budget_seconds`: finite and strictly positive. */
const finiteBudgetSeconds = (value: unknown): number | undefined => {
  if (typeof value !== 'number' || !Number.isFinite(value) || value <= 0) {
    return undefined;
  }
  return value;
};

const etaWaitSeconds = (value: number | null | undefined): number | null => {
  const seconds = finiteEtaSeconds(value);
  return seconds === undefined ? null : Math.round(seconds);
};

const budgetWaitSeconds = (value: number | null | undefined): number | null => {
  const seconds = finiteBudgetSeconds(value);
  return seconds === undefined ? null : Math.round(seconds);
};

export interface GpuWaitFromOperationDetail {
  warmupEtaSeconds?: number;
  startupBudgetSeconds?: number;
}

/**
 * Map scene-describe-multipart operation-error `detail` wait fields.
 * Returns undefined when both fields are absent or invalid; never invents ceilings.
 */
export const gpuWaitFromOperationDetail = (detail: unknown): GpuWaitFromOperationDetail | undefined => {
  if (!isPlainObject(detail)) {
    return undefined;
  }
  const warmupEtaSeconds = finiteEtaSeconds(detail.warmup_eta_seconds);
  const startupBudgetSeconds = finiteBudgetSeconds(detail.startup_budget_seconds);
  if (warmupEtaSeconds === undefined && startupBudgetSeconds === undefined) {
    return undefined;
  }
  const wait: GpuWaitFromOperationDetail = {};
  if (warmupEtaSeconds !== undefined) {
    wait.warmupEtaSeconds = warmupEtaSeconds;
  }
  if (startupBudgetSeconds !== undefined) {
    wait.startupBudgetSeconds = startupBudgetSeconds;
  }
  return wait;
};

const formatStoppedWait = (seconds: number, kind: 'about' | 'up to'): string => {
  if (seconds >= 60) {
    const minutes = Math.max(1, Math.round(seconds / 60));
    return kind === 'about'
      ? sprintf(__('about %d min', 'alt-context'), minutes)
      : sprintf(__('up to %d min', 'alt-context'), minutes);
  }
  return kind === 'about'
    ? sprintf(__('about %ds', 'alt-context'), seconds)
    : sprintf(__('up to %ds', 'alt-context'), seconds);
};

const startingHeadline = (
  warmupEtaSeconds: number | null | undefined,
  startupBudgetSeconds: number | null | undefined,
): string => {
  const eta = etaWaitSeconds(warmupEtaSeconds);
  if (eta !== null) {
    return sprintf(__('Description Service is starting… about %ds', 'alt-context'), eta);
  }
  const budget = budgetWaitSeconds(startupBudgetSeconds);
  if (budget !== null) {
    return sprintf(__('Description Service is starting… up to %ds', 'alt-context'), budget);
  }
  return __('Description Service is starting…', 'alt-context');
};

const stoppedHeadline = (
  warmupEtaSeconds: number | null | undefined,
  startupBudgetSeconds: number | null | undefined,
): string => {
  const eta = etaWaitSeconds(warmupEtaSeconds);
  const budget = eta === null ? budgetWaitSeconds(startupBudgetSeconds) : null;
  const wait =
    eta !== null
      ? formatStoppedWait(eta, 'about')
      : budget !== null
        ? formatStoppedWait(budget, 'up to')
        : null;
  if (wait === null) {
    return __('Description Service is off — it starts when you describe', 'alt-context');
  }
  return sprintf(__('Description Service is off — it starts when you describe (%s)', 'alt-context'), wait);
};

const readyHeadline = (computeTier: string | null | undefined, modelId: string | null | undefined): string => {
  const tier = typeof computeTier === 'string' && computeTier.trim() !== '' ? computeTier : null;
  const model = typeof modelId === 'string' && modelId.trim() !== '' ? modelId : null;
  if (tier !== null && model !== null) {
    return sprintf(__('Description Service: ready · %1$s · %2$s', 'alt-context'), tier, model);
  }
  if (model !== null) {
    return sprintf(__('Description Service: ready · %s', 'alt-context'), model);
  }
  if (tier !== null) {
    return sprintf(__('Description Service: ready · %s', 'alt-context'), tier);
  }
  return __('Description Service is ready', 'alt-context');
};

export interface GpuTierStatusProps {
  /** Run-owned GPU state; authoritative while `isRunPending` is true. */
  gpuState?: GpuState | null;
  /** Pause idle polling while a describe run or Suggest is in flight. */
  isRunPending?: boolean;
  warmupEtaSeconds?: number | null;
  startupBudgetSeconds?: number | null;
  computeTier?: string | null;
  modelId?: string | null;
}

interface GpuIdleStatusView {
  displayedState: GpuState;
  headline: string;
  detail: string | null;
  action: GpuIdleStatusAction;
}

interface GpuIdleRunInput {
  isRunPending: boolean;
  gpuState: GpuState | null;
  warmupEtaSeconds: number | null | undefined;
  startupBudgetSeconds: number | null | undefined;
  computeTier: string | null | undefined;
  modelId: string | null | undefined;
}

interface GpuIdlePollInput {
  gpuState: GpuState;
  snapshotFresh: boolean;
  isLoading: boolean;
  isError: boolean;
  hasPayload: boolean;
}

const resolveIdleServiceStatusView = (run: GpuIdleRunInput, poll: GpuIdlePollInput): GpuIdleStatusView => {
  if (poll.isError && !run.isRunPending) {
    return {
      displayedState: GPU_STATE.UNKNOWN,
      headline: __('Description Service idle — status not checked', 'alt-context'),
      detail: null,
      action: GPU_IDLE_STATUS_ACTION.RETRY,
    };
  }

  if (!run.isRunPending && !poll.hasPayload) {
    return {
      displayedState: GPU_STATE.UNKNOWN,
      headline: poll.isLoading
        ? __('Description Service: checking status…', 'alt-context')
        : __('Description Service idle — status not checked', 'alt-context'),
      detail: null,
      action: poll.isLoading ? GPU_IDLE_STATUS_ACTION.NONE : GPU_IDLE_STATUS_ACTION.RETRY,
    };
  }

  const idleState: GpuState = poll.snapshotFresh ? poll.gpuState : GPU_STATE.UNKNOWN;
  const displayedState: GpuState = run.isRunPending ? (run.gpuState ?? GPU_STATE.UNKNOWN) : idleState;
  const treatAsStale = !run.isRunPending && displayedState === GPU_STATE.UNKNOWN;

  if (treatAsStale) {
    return {
      displayedState,
      headline: __('Description Service status is out of date', 'alt-context'),
      detail: null,
      action: GPU_IDLE_STATUS_ACTION.REFRESH,
    };
  }

  switch (displayedState) {
    case GPU_STATE.STOPPED:
      return {
        displayedState,
        headline: stoppedHeadline(run.warmupEtaSeconds, run.startupBudgetSeconds),
        detail: null,
        action: GPU_IDLE_STATUS_ACTION.NONE,
      };
    case GPU_STATE.STARTING:
    case GPU_STATE.WARMING:
      return {
        displayedState,
        headline: startingHeadline(run.warmupEtaSeconds, run.startupBudgetSeconds),
        detail: null,
        action: GPU_IDLE_STATUS_ACTION.NONE,
      };
    case GPU_STATE.READY:
      return {
        displayedState,
        headline: readyHeadline(run.computeTier, run.modelId),
        detail: null,
        action: GPU_IDLE_STATUS_ACTION.NONE,
      };
    case GPU_STATE.DEGRADED:
      return {
        displayedState,
        headline: __('Description Service is unavailable', 'alt-context'),
        detail: null,
        action: GPU_IDLE_STATUS_ACTION.NONE,
      };
    case GPU_STATE.UNKNOWN:
      return {
        displayedState,
        headline: __('Description Service status is out of date', 'alt-context'),
        detail: null,
        action: GPU_IDLE_STATUS_ACTION.REFRESH,
      };
    default: {
      const unreachable: never = displayedState;
      return unreachable;
    }
  }
};

export const GpuTierStatus = ({
  gpuState: runGpuState = null,
  isRunPending = false,
  warmupEtaSeconds = null,
  startupBudgetSeconds = null,
  computeTier = null,
  modelId = null,
}: GpuTierStatusProps): JSX.Element => {
  const status = useGpuServiceStatus({ isRunPending });
  const view = resolveIdleServiceStatusView(
    {
      isRunPending,
      gpuState: runGpuState,
      warmupEtaSeconds,
      startupBudgetSeconds,
      computeTier,
      modelId,
    },
    {
      gpuState: status.gpuState,
      snapshotFresh: status.snapshotFresh,
      isLoading: status.isLoading,
      isError: status.isError,
      hasPayload: status.data !== undefined,
    },
  );
  const presentation = gpuStatePresentation(view.displayedState);
  const Icon = GPU_STATE_ICON_COMPONENT[presentation.icon];
  const spin = presentation.icon === GPU_STATE_ICON.STARTING;
  const previousStateRef = useRef<GpuState | null>(null);
  const [announcement, setAnnouncement] = useState('');

  useEffect(() => {
    if (previousStateRef.current === null) {
      previousStateRef.current = view.displayedState;
      return;
    }
    if (previousStateRef.current === view.displayedState) {
      return;
    }
    previousStateRef.current = view.displayedState;
    setAnnouncement(view.headline);
  }, [view.displayedState, view.headline]);

  const actionLabel =
    view.action === GPU_IDLE_STATUS_ACTION.RETRY
      ? __('Check status', 'alt-context')
      : view.action === GPU_IDLE_STATUS_ACTION.REFRESH
        ? __('Refresh', 'alt-context')
        : null;

  return (
    <>
      <div
        className={`acx-sync-status acx-media-selection__gpu-tier-status${gpuStateToneClass(presentation.tone)}`}
        role="status"
        aria-live="off"
        aria-label={view.headline}
        data-gpu-state={view.displayedState}
        data-gpu-terminal={presentation.terminal}
      >
        <span className="acx-media-selection__detail-chip">
          <Icon className={spin ? 'acx-media-selection__bulk-describe-spin' : undefined} aria-hidden="true" size={16} />
          {view.headline}
        </span>
        {view.detail ? <span className="acx-sync-status__label">{view.detail}</span> : null}
        {actionLabel ? (
          <button type="button" className="button" onClick={status.refetch}>
            {actionLabel}
          </button>
        ) : null}
      </div>
      <div className="screen-reader-text" aria-live="polite" aria-atomic="true" data-testid="gpu-tier-status-live">
        {announcement}
      </div>
    </>
  );
};
