/**
 * GPU lifecycle -> operator presentation strategy (sr-007).
 *
 * This is the single owner of GPU-state labels and severity/icon choices. The
 * presentation table is exhaustive over the frontend GpuState union; unknown
 * wire values are narrowed to UNKNOWN at the describeApi boundary.
 */
import { __, _n, sprintf } from '@wordpress/i18n';

import { GPU_STATE, type GpuState } from '../../api/describeApi';
import { WARMING_OBSERVATION_STATUS, type WarmingObservation } from '../../utils/warmingDeadline';

/** Run-scoped wait copy: an unavailable observation is not proof of warm-up. */
export const descriptionWaitPresentation = (observation?: WarmingObservation): { headline: string; detail: string } => {
  if (observation?.status === WARMING_OBSERVATION_STATUS.OVERDUE) {
    return {
      headline: __('Description service is taking longer than expected', 'alt-context'),
      detail: __('This description run is still waiting. Check its status or cancel the run.', 'alt-context'),
    };
  }
  if (observation?.status === WARMING_OBSERVATION_STATUS.WAITING) {
    return {
      headline: __('Waiting for description service…', 'alt-context'),
      detail: __(
        'Remaining descriptions are waiting for the service. Results will be available as drafts.',
        'alt-context',
      ),
    };
  }
  return {
    headline: __('Description service status unavailable', 'alt-context'),
    detail: __('Startup could not be confirmed. Check the run status or cancel this description run.', 'alt-context'),
  };
};

export const GPU_STATE_ICON = {
  HELP: 'circle-help',
  STOPPED: 'circle-stop',
  STARTING: 'loader',
  WARMING: 'flame',
  READY: 'zap',
  DEGRADED: 'triangle-alert',
} as const;

export type GpuStateIcon = (typeof GPU_STATE_ICON)[keyof typeof GPU_STATE_ICON];

export const GPU_STATE_TONE = {
  MUTED: 'muted',
  PENDING: 'pending',
  RUNNING: 'running',
  SUCCESS: 'success',
  WARNING: 'warning',
} as const;

export type GpuStateTone = (typeof GPU_STATE_TONE)[keyof typeof GPU_STATE_TONE];

export interface GpuStatePresentation {
  label: string;
  icon: GpuStateIcon;
  tone: GpuStateTone;
  terminal: boolean;
}

type HumanCountLocale =
  | { kind: 'localized'; tag: string }
  | { kind: 'neutral-raw'; reason: 'missing' | 'invalid' | 'unsupported' | 'unavailable' };

const resolveHumanCountLocale = (raw: string | null): HumanCountLocale => {
  const requested = raw?.trim();
  if (!requested) {
    return { kind: 'neutral-raw', reason: 'missing' };
  }
  if (
    typeof Intl === 'undefined' ||
    typeof Intl.getCanonicalLocales !== 'function' ||
    typeof Intl.NumberFormat !== 'function' ||
    typeof Intl.NumberFormat.supportedLocalesOf !== 'function'
  ) {
    return { kind: 'neutral-raw', reason: 'unavailable' };
  }
  let tag: string | undefined;
  try {
    [tag] = Intl.getCanonicalLocales(requested);
  } catch {
    return { kind: 'neutral-raw', reason: 'invalid' };
  }
  if (tag === undefined) {
    return { kind: 'neutral-raw', reason: 'invalid' };
  }
  try {
    return Intl.NumberFormat.supportedLocalesOf([tag], { localeMatcher: 'lookup' }).includes(tag)
      ? { kind: 'localized', tag }
      : { kind: 'neutral-raw', reason: 'unsupported' };
  } catch {
    return { kind: 'neutral-raw', reason: 'unavailable' };
  }
};

const formatHumanCount = (count: number, uiLocale: string | null): string => {
  const locale = resolveHumanCountLocale(uiLocale);
  if (locale.kind === 'localized') {
    try {
      return new Intl.NumberFormat(locale.tag, { style: 'decimal', maximumFractionDigits: 0 }).format(count);
    } catch {
      // Capability failures retain usable copy with deliberate, ungrouped raw numbers.
      return String(count);
    }
  }
  return String(count);
};

/** Centralized GPU copy consumed by the chip and its calm consequence line. */
export const GPU_STATE_VOCABULARY = {
  tierPrefix: __('GPU tier:', 'alt-context'),
  notReported: __('not reported', 'alt-context'),
  stopped: __('stopped', 'alt-context'),
  starting: __('starting', 'alt-context'),
  warming: __('warming', 'alt-context'),
  ready: __('ready', 'alt-context'),
  degraded: __('degraded', 'alt-context'),
  notReportedNotice: __('GPU tier not reported. Describing can still continue on CPU.', 'alt-context'),
  stoppedNotice: __('Will warm on start (~2 min)', 'alt-context'),
  startingNotice: __('GPU is starting. CPU drafts stay available while it gets ready.', 'alt-context'),
  warmingNotice: __('GPU is warming. Review results for each description’s compute tier.', 'alt-context'),
  readyNotice: __('GPU ready. Review results for each description’s compute tier.', 'alt-context'),
  degradedNotice: (_draftCount: number): string =>
    __('GPU unavailable. Existing results remain available; review each description’s compute tier.', 'alt-context'),
  warmingToast: __('GPU warming — this run is waiting for the description service', 'alt-context'),
  readyToast: __('GPU ready — review results for compute tiers', 'alt-context'),
  degradedToast: __('GPU unavailable — no descriptions returned yet', 'alt-context'),
  degradedToastWithDrafts: (draftCount: number, uiLocale: string | null): string =>
    sprintf(
      _n(
        'GPU unavailable — %s draft ready to review',
        'GPU unavailable — %s drafts ready to review',
        draftCount,
        'alt-context',
      ),
      formatHumanCount(draftCount, uiLocale),
    ),
  doneToastWithoutDrafts: __('Description run finished — no drafts returned.', 'alt-context'),
  doneToast: (draftCount: number): string =>
    sprintf(_n('%d draft ready to review', '%d drafts ready to review', draftCount, 'alt-context'), draftCount),
  failedToastWarmupTimeout: __('GPU warm-up timed out. Retry to continue.', 'alt-context'),
  failedToastDescribePoll: __('Lost connection to the describe run.', 'alt-context'),
  failedToastGpuUnavailable: __('Description Service status unavailable', 'alt-context'),
  failedToastCancelled: __('Run cancelled', 'alt-context'),
  failedToastScanFailed: __('People identification failed.', 'alt-context'),
  failedToastFailed: __('Describe run failed.', 'alt-context'),
  failedToastGeneric: __('Run failed', 'alt-context'),
  failedToastWithReason: (reason: string): string => sprintf(__('Run failed (%s)', 'alt-context'), reason),
  backToRun: __('Back to run', 'alt-context'),
  backToRunAltText: __('Return to the active describe run', 'alt-context'),
  reviewResults: __('Review results', 'alt-context'),
  reviewResultsAltText: __('Review the active describe run results', 'alt-context'),
  reviewDrafts: (draftCount: number): string =>
    sprintf(_n('Review %d draft', 'Review %d drafts', draftCount, 'alt-context'), draftCount),
  reviewDraftsAltText: __('Open the review queue for this run', 'alt-context'),
  retry: __('Retry', 'alt-context'),
  retryAltText: __('Retry the failed run', 'alt-context'),
} as const;

export const GPU_STATE_PRESENTATION = {
  [GPU_STATE.UNKNOWN]: {
    label: GPU_STATE_VOCABULARY.notReported,
    icon: GPU_STATE_ICON.HELP,
    tone: GPU_STATE_TONE.MUTED,
    terminal: false,
  },
  [GPU_STATE.STOPPED]: {
    label: GPU_STATE_VOCABULARY.stopped,
    icon: GPU_STATE_ICON.STOPPED,
    tone: GPU_STATE_TONE.PENDING,
    terminal: true,
  },
  [GPU_STATE.STARTING]: {
    label: GPU_STATE_VOCABULARY.starting,
    icon: GPU_STATE_ICON.STARTING,
    tone: GPU_STATE_TONE.PENDING,
    terminal: false,
  },
  [GPU_STATE.WARMING]: {
    label: GPU_STATE_VOCABULARY.warming,
    icon: GPU_STATE_ICON.WARMING,
    tone: GPU_STATE_TONE.RUNNING,
    terminal: false,
  },
  [GPU_STATE.READY]: {
    label: GPU_STATE_VOCABULARY.ready,
    icon: GPU_STATE_ICON.READY,
    tone: GPU_STATE_TONE.SUCCESS,
    terminal: true,
  },
  [GPU_STATE.DEGRADED]: {
    label: GPU_STATE_VOCABULARY.degraded,
    icon: GPU_STATE_ICON.DEGRADED,
    tone: GPU_STATE_TONE.WARNING,
    terminal: true,
  },
} satisfies Record<GpuState, GpuStatePresentation>;

/** Missing fields from older API builds share the calm `unknown` presentation. */
export const gpuStatePresentation = (state: GpuState | null): GpuStatePresentation =>
  GPU_STATE_PRESENTATION[state ?? GPU_STATE.UNKNOWN];

export const gpuStateNotice = (state: GpuState | null, cpuDraftCount = 0): string => {
  switch (state ?? GPU_STATE.UNKNOWN) {
    case GPU_STATE.UNKNOWN:
      return GPU_STATE_VOCABULARY.notReportedNotice;
    case GPU_STATE.STOPPED:
      return GPU_STATE_VOCABULARY.stoppedNotice;
    case GPU_STATE.STARTING:
      return GPU_STATE_VOCABULARY.startingNotice;
    case GPU_STATE.WARMING:
      return GPU_STATE_VOCABULARY.warmingNotice;
    case GPU_STATE.READY:
      return GPU_STATE_VOCABULARY.readyNotice;
    case GPU_STATE.DEGRADED:
      return GPU_STATE_VOCABULARY.degradedNotice(cpuDraftCount);
    default:
      return GPU_STATE_VOCABULARY.notReportedNotice;
  }
};
