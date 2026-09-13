/**
 * GPU lifecycle -> operator presentation strategy (sr-007).
 *
 * This is the single owner of GPU-state labels and severity/icon choices. The
 * presentation table is exhaustive over the frontend GpuState union; unknown
 * wire values are narrowed to UNKNOWN at the describeApi boundary.
 */
import { __ } from '@wordpress/i18n';

import { GPU_STATE, type GpuState } from '../../api/describeApi';

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
  warmingToast: __('GPU warming — CPU drafts first', 'alt-context'),
  readyToast: __('GPU ready — review results for compute tiers', 'alt-context'),
  degradedToast: __('GPU unavailable — CPU drafts kept', 'alt-context'),
  backToRun: __('Back to run', 'alt-context'),
  backToRunAltText: __('Return to the active describe run', 'alt-context'),
  reviewResults: __('Review results', 'alt-context'),
  reviewResultsAltText: __('Review the active describe run results', 'alt-context'),
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
