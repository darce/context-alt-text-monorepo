export const GUIDED_BROWSER_TIMING_SCHEMA: 'altcontext-guided-browser-timing/v1';
export const DEFAULT_RENDER_TIMEOUT_MS: number;

export type TimingClock = () => number;
export type TimerHandle = number;
export type AnimationFrameHandle = number;
export type TimerScheduler = (callback: () => void, delayMs: number) => TimerHandle;
export type TimerCanceler = (handle: TimerHandle) => void;
export type AnimationFrameScheduler = (callback: () => void) => AnimationFrameHandle;
export type AnimationFrameCanceler = (handle: AnimationFrameHandle) => void;
export type TimingOperation = () => unknown;

export type RenderedTextResult =
  | {
      ok: true;
      text: string;
      renderedAtMs: number;
    }
  | {
      ok: false;
      text: null;
      renderedAtMs: null;
      timedOut?: boolean;
      error?: string;
    };

export interface WaitForRenderedTextOptions {
  readRenderedText: () => string | null | undefined;
  isTextReady?: (text: string) => boolean;
  maxWaitMs?: number;
  deadlineMs?: number;
  now?: TimingClock;
  requestAnimationFrame?: AnimationFrameScheduler;
  cancelAnimationFrame?: AnimationFrameCanceler;
  setTimer?: TimerScheduler;
  clearTimer?: TimerCanceler;
}

interface MeasureOptions {
  readRenderedText: () => string | null | undefined;
  isTextReady?: (text: string) => boolean;
  maxWaitMs?: number;
  now?: TimingClock;
  requestAnimationFrame?: AnimationFrameScheduler;
  cancelAnimationFrame?: AnimationFrameCanceler;
  setTimer?: TimerScheduler;
  clearTimer?: TimerCanceler;
}

export type GuidedBrowserTimingMode = 'true_inference' | 'recorded_replay';
export type GuidedBrowserTimingStatus =
  | 'not_started'
  | 'request_timeout'
  | 'request_failed'
  | 'render_timeout'
  | 'render_failed'
  | 'replay_timeout'
  | 'replay_failed'
  | 'rendered';

export interface GuidedBrowserTimingRecord {
  schema: typeof GUIDED_BROWSER_TIMING_SCHEMA;
  mode: GuidedBrowserTimingMode;
  label: string;
  clock: 'performance.now';
  max_wait_ms: number;
  request_sent_at_ms: number | null;
  response_received_at_ms: number | null;
  replay_started_at_ms: number | null;
  text_rendered_at_ms: number | null;
  elapsed_request_to_render_ms: number | null;
  elapsed_response_to_render_ms: number | null;
  elapsed_replay_to_render_ms: number | null;
  rendered_text: string | null;
  rendered_text_length: number;
  status: GuidedBrowserTimingStatus;
  error: string | null;
}

export interface MeasureTrueInferenceOptions extends MeasureOptions {
  sendRequest: TimingOperation;
  label?: string;
}

export interface MeasureRecordedReplayOptions extends MeasureOptions {
  triggerReplay: TimingOperation;
  label?: string;
}

export const waitForRenderedText: (options: WaitForRenderedTextOptions) => Promise<RenderedTextResult>;
export const measureTrueInference: (
  options: MeasureTrueInferenceOptions,
) => Promise<GuidedBrowserTimingRecord>;
export const measureRecordedReplay: (
  options: MeasureRecordedReplayOptions,
) => Promise<GuidedBrowserTimingRecord>;
export const readRenderedTextFromSelector: (selector: string) => () => string;
export const serializeGuidedBrowserTiming: (record: GuidedBrowserTimingRecord) => string;
