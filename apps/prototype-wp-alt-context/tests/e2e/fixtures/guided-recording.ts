/**
 * Guided walkthrough recording helpers (GUIDESEED-1).
 *
 * Pure functions behind `tests/e2e/evidence/guided-walkthrough.spec.ts`: they turn
 * the timed steps of a headless Playwright run into a WebVTT caption track and a
 * manifest, and classify the REST traffic the page produced so the recorded-only
 * policy (no live generation, no WordPress writes) is asserted, not assumed.
 * Narration describes what changes on screen, never what the model "recognised"
 * (A11Y-09, A11Y-54): the run replays saved suggestions.
 */

export interface GuidedRecordingCue {
  /** Stable id, also the step name in the manifest. */
  id: string;
  started_at_ms: number;
  ended_at_ms: number;
  /** Caption text; describes the visual change, not an inference. */
  text: string;
}

export type AcxRequestClass = 'read' | 'privileged' | 'other';

export interface AcxRequestRecord {
  method: string;
  url: string;
  classification: AcxRequestClass;
}

export interface GuidedRecordingManifest {
  task_ref: string;
  captured_at: string;
  base_url: string;
  deploy_commit_sha: string | null;
  harness: { headless: boolean; viewport: { width: number; height: number }; slow_mo_ms: number };
  video_path: string | null;
  captions_path: string;
  cues: GuidedRecordingCue[];
  /** Every acx/v1 request the page issued; must contain zero `privileged` rows. */
  acx_requests: AcxRequestRecord[];
  privileged_request_count: number;
  applied_text_after_apply: string | null;
  applied_text_after_undo: string | null;
  verdict: 'pass' | 'fail';
}

export const GUIDED_RECORDING_MANIFEST_FILENAME = 'guided-walkthrough-manifest.json';
export const GUIDED_RECORDING_CAPTIONS_FILENAME = 'guided-walkthrough.vtt';

/** Opening caption required by the case-study brief; word-for-word. */
export const GUIDED_RECORDING_OPENING_CAPTION =
  'Recorded prototype walkthrough. Uses saved face suggestions and sample drafts; changes affect only the demo copy.';

const pad = (value: number, width: number): string => String(value).padStart(width, '0');

/** `HH:MM:SS.mmm` as WebVTT requires; negative or fractional input is clamped/floored. */
export const formatVttTimestamp = (ms: number): string => {
  const total = Math.max(0, Math.floor(ms));
  const hours = Math.floor(total / 3_600_000);
  const minutes = Math.floor((total % 3_600_000) / 60_000);
  const seconds = Math.floor((total % 60_000) / 1000);
  const millis = total % 1000;
  return `${pad(hours, 2)}:${pad(minutes, 2)}:${pad(seconds, 2)}.${pad(millis, 3)}`;
};

const MIN_CUE_MS = 1_000;

/**
 * Render cues as a WebVTT track. Cues are emitted in start order; a cue shorter than
 * one second is stretched so players do not drop it. Blank cues are skipped.
 */
export const renderWebVtt = (cues: readonly GuidedRecordingCue[]): string => {
  const ordered = [...cues]
    .filter((cue) => cue.text.trim().length > 0)
    .sort((a, b) => a.started_at_ms - b.started_at_ms);
  const blocks = ordered.map((cue, index) => {
    const start = cue.started_at_ms;
    const end = Math.max(cue.ended_at_ms, start + MIN_CUE_MS);
    const text = cue.text.replace(/\r?\n/g, ' ').replace(/-->/g, '→').trim();
    return `${index + 1}\n${formatVttTimestamp(start)} --> ${formatVttTimestamp(end)}\n${text}`;
  });
  return `WEBVTT\n\n${blocks.join('\n\n')}\n`;
};

/** Plain-text transcript for the case-study page (one paragraph per cue). */
export const renderTranscript = (cues: readonly GuidedRecordingCue[]): string =>
  [...cues]
    .filter((cue) => cue.text.trim().length > 0)
    .sort((a, b) => a.started_at_ms - b.started_at_ms)
    .map((cue) => {
      const text = cue.text.replace(/\r?\n/g, ' ').trim();
      return `[${formatVttTimestamp(cue.started_at_ms).slice(3, 8)}] ${text}`;
    })
    .join('\n')
    .concat('\n');

const ACX_REST_PATTERN = /(?:\/wp-json\/acx\/v1\/|[?&]rest_route=(?:%2F|\/)acx(?:%2F|\/)v1(?:%2F|\/))/i;
const PRIVILEGED_PATH_PATTERN = /\/(?:describe|persons|commit|scan|apply|jobs|tasks)(?:[/?#]|$)/i;

/** True when the request targets the plugin's REST namespace at all. */
export const isAcxRestRequest = (url: string): boolean => ACX_REST_PATTERN.test(url);

/**
 * Recorded-only policy: the guided page may read (GET) plugin state, but any write
 * verb or any path that starts server-side work (describe, roster writes, scans, jobs)
 * is privileged and fails the recording.
 */
export const classifyAcxRequest = (method: string, url: string): AcxRequestClass => {
  if (!isAcxRestRequest(url)) {
    return 'other';
  }
  const verb = method.toUpperCase();
  if (verb !== 'GET' && verb !== 'HEAD' && verb !== 'OPTIONS') {
    return 'privileged';
  }
  let pathname = url;
  try {
    const parsed = new URL(url);
    const routeParam = parsed.searchParams.get('rest_route');
    pathname = routeParam ?? parsed.pathname;
  } catch {
    // Relative or malformed URL: classify on the raw string.
  }
  return PRIVILEGED_PATH_PATTERN.test(decodeURIComponent(pathname)) ? 'privileged' : 'read';
};

export const countPrivileged = (records: readonly AcxRequestRecord[]): number =>
  records.filter((record) => record.classification === 'privileged').length;
