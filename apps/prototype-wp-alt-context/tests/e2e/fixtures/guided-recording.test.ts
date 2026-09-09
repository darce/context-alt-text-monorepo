import { describe, expect, it } from 'vitest';

import {
  classifyAcxRequest,
  countPrivileged,
  formatVttTimestamp,
  GUIDED_RECORDING_CAPTIONS_FILENAME,
  GUIDED_RECORDING_MANIFEST_FILENAME,
  GUIDED_RECORDING_OPENING_CAPTION,
  isAcxRestRequest,
  renderTranscript,
  renderWebVtt,
  type GuidedRecordingCue,
} from './guided-recording';

const cues = (): GuidedRecordingCue[] => [
  { id: 'apply', started_at_ms: 42_000, ended_at_ms: 46_500, text: 'The demo image now carries the edited alt text.' },
  { id: 'opening', started_at_ms: 0, ended_at_ms: 5_000, text: GUIDED_RECORDING_OPENING_CAPTION },
  { id: 'blank', started_at_ms: 10_000, ended_at_ms: 11_000, text: '   ' },
  { id: 'short', started_at_ms: 20_000, ended_at_ms: 20_200, text: 'Line one\nline two --> arrow' },
];

describe('formatVttTimestamp', () => {
  it('renders HH:MM:SS.mmm', () => {
    expect(formatVttTimestamp(0)).toBe('00:00:00.000');
    expect(formatVttTimestamp(61_234)).toBe('00:01:01.234');
    expect(formatVttTimestamp(3_600_000 + 5)).toBe('01:00:00.005');
  });

  it('clamps negatives and floors fractions', () => {
    expect(formatVttTimestamp(-50)).toBe('00:00:00.000');
    expect(formatVttTimestamp(999.9)).toBe('00:00:00.999');
  });
});

describe('renderWebVtt', () => {
  it('starts with the WEBVTT header and orders cues by start time', () => {
    const vtt = renderWebVtt(cues());
    expect(vtt.startsWith('WEBVTT\n\n')).toBe(true);
    const firstCue = vtt.split('\n\n')[1];
    expect(firstCue).toContain('00:00:00.000 --> 00:00:05.000');
    expect(firstCue).toContain(GUIDED_RECORDING_OPENING_CAPTION);
    expect(vtt.indexOf('00:00:20.000')).toBeLessThan(vtt.indexOf('00:00:42.000'));
  });

  it('skips blank cues and numbers the rest consecutively', () => {
    const vtt = renderWebVtt(cues());
    expect(vtt).not.toMatch(/00:00:10\.000/);
    expect(vtt).toMatch(/\n1\n00:00:00\.000/);
    expect(vtt).toMatch(/\n2\n00:00:20\.000/);
    expect(vtt).toMatch(/\n3\n00:00:42\.000/);
  });

  it('stretches sub-second cues to one second and sanitises cue text', () => {
    const vtt = renderWebVtt(cues());
    expect(vtt).toContain('00:00:20.000 --> 00:00:21.000\nLine one line two → arrow');
  });

  it('renders an empty track for no cues', () => {
    expect(renderWebVtt([])).toBe('WEBVTT\n\n\n');
  });
});

describe('renderTranscript', () => {
  it('emits one MM:SS-stamped line per non-blank cue in time order', () => {
    const lines = renderTranscript(cues()).trimEnd().split('\n');
    expect(lines).toHaveLength(3);
    expect(lines[0]).toBe(`[00:00] ${GUIDED_RECORDING_OPENING_CAPTION}`);
    expect(lines[2]).toBe('[00:42] The demo image now carries the edited alt text.');
  });
});

describe('classifyAcxRequest', () => {
  const base = 'http://localhost:10010/wp-json/acx/v1';

  it('treats non-plugin traffic as other', () => {
    expect(classifyAcxRequest('POST', 'http://localhost:10010/wp-admin/admin-ajax.php')).toBe('other');
    expect(classifyAcxRequest('GET', 'http://localhost:10010/wp-json/wp/v2/media/12')).toBe('other');
    expect(isAcxRestRequest('http://localhost:10010/wp-json/wp/v2/media')).toBe(false);
  });

  it('allows plain GET reads of plugin state', () => {
    expect(classifyAcxRequest('GET', `${base}/roster/entries`)).toBe('read');
    expect(classifyAcxRequest('get', `${base}/settings`)).toBe('read');
    expect(classifyAcxRequest('GET', 'http://localhost:10010/?rest_route=%2Facx%2Fv1%2Fsettings')).toBe('read');
  });

  it('flags every write verb', () => {
    expect(classifyAcxRequest('POST', `${base}/roster/persons`)).toBe('privileged');
    expect(classifyAcxRequest('PUT', `${base}/settings`)).toBe('privileged');
    expect(classifyAcxRequest('DELETE', `${base}/roster/entries/3`)).toBe('privileged');
  });

  it('flags describe and job-starting paths even on GET', () => {
    expect(classifyAcxRequest('GET', `${base}/public/demo/describe?media_id=4`)).toBe('privileged');
    expect(classifyAcxRequest('GET', `${base}/describe/12`)).toBe('privileged');
    expect(classifyAcxRequest('GET', `${base}/jobs/9`)).toBe('privileged');
    expect(classifyAcxRequest('GET', 'http://localhost:10010/?rest_route=/acx/v1/describe&media_id=4')).toBe('privileged');
  });

  it('does not confuse similar words in unrelated segments', () => {
    expect(classifyAcxRequest('GET', `${base}/roster/entries?include=described`)).toBe('read');
  });

  it('flags query _method write overrides on GET as privileged', () => {
    expect(classifyAcxRequest('GET', `${base}/settings?_method=POST`)).toBe('privileged');
    expect(classifyAcxRequest('GET', `${base}/roster/entries?_method=put`)).toBe('privileged');
    expect(
      classifyAcxRequest('GET', 'http://localhost:10010/?rest_route=/acx/v1/settings&_method=POST'),
    ).toBe('privileged');
  });

  it('flags X-HTTP-Method-Override write overrides as privileged', () => {
    expect(classifyAcxRequest('GET', `${base}/settings`, { 'X-HTTP-Method-Override': 'POST' })).toBe(
      'privileged',
    );
    expect(classifyAcxRequest('GET', `${base}/settings`, { 'x-http-method-override': 'PATCH' })).toBe(
      'privileged',
    );
  });

  it('does not treat a GET override as a write', () => {
    expect(classifyAcxRequest('GET', `${base}/settings?_method=GET`)).toBe('read');
    expect(classifyAcxRequest('GET', `${base}/settings`, { 'X-HTTP-Method-Override': 'HEAD' })).toBe(
      'read',
    );
  });
});

describe('countPrivileged', () => {
  it('counts only privileged rows', () => {
    expect(
      countPrivileged([
        { method: 'GET', url: 'a', classification: 'read' },
        { method: 'POST', url: 'b', classification: 'privileged' },
        { method: 'GET', url: 'c', classification: 'other' },
        { method: 'GET', url: 'd', classification: 'privileged' },
      ]),
    ).toBe(2);
  });
});

describe('artifact filenames', () => {
  it('are stable for the make target', () => {
    expect(GUIDED_RECORDING_MANIFEST_FILENAME).toBe('guided-walkthrough-manifest.json');
    expect(GUIDED_RECORDING_CAPTIONS_FILENAME).toBe('guided-walkthrough.vtt');
  });
});
