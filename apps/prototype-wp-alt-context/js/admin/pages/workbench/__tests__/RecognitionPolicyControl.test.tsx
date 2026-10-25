import React from 'react';
import { act, cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { focusManager, type QueryClient } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { registerConfig, resetConfigCache, type ApiConfig } from '../../../api/config';
import { queryKeys } from '../../../api/queryKeys';
import type { SettingsResponse } from '../../../api/settingsApi';
import { buildTestQueryClient, createQueryWrapper } from '../../../test-utils/queryClient';
import { WorkbenchPage } from '../../WorkbenchPage';
import { SettingsPage } from '../../SettingsPage';
import { RecognitionPolicyControl } from '../RecognitionPolicyControl';

// Exercise the actual Workbench mount with its surrounding scan pipeline isolated.
const { startScan } = vi.hoisted(() => ({ startScan: vi.fn() }));
vi.mock('../WorkbenchContext', () => ({ WorkbenchProvider: ({ children }: { children: React.ReactNode }) => children }));
vi.mock('../WorkbenchNavContext', () => ({
  useWorkbenchNav: () => ({
    activeSection: 'scan', recognitionSource: 'service', effectiveTargetUrl: '', activeOverlay: null,
    setActiveOverlay: vi.fn(), isAdvancedOpen: false, setAdvancedOpen: vi.fn(),
  }),
}));
vi.mock('../ClusterPanelContext', () => ({
  useClusterPanel: () => ({ clusterPanel: { mode: 'none' }, dispatchClusterPanel: vi.fn() }),
}));
vi.mock('../JobPipelineContext', () => ({
  useJobPipeline: () => ({ scanRun: { isSynced: false }, status: { isOnline: true }, retryProjectionSync: vi.fn() }),
}));
vi.mock('../WorkbenchMediaContext', () => ({
  useWorkbenchMediaContext: () => ({ mediaQueue: { detailTruncationNotice: null } }),
}));
vi.mock('../ReviewSurfaceContext', () => ({ useReviewSurface: () => ({ cardPrimaryPresent: false }) }));
vi.mock('../../../hooks/usePanesParam', () => ({ usePanesParam: () => ['both', vi.fn()] }));
vi.mock('../ScanTabContent', () => ({
  ScanTabContent: () => <button type="button" className="button button-primary" onClick={startScan}>Scan media</button>,
}));
vi.mock('../MediaSelection', () => ({ MediaSelection: () => null }));
vi.mock('../AdvancedDrawer', () => ({ AdvancedDrawer: () => null }));
vi.mock('../ConflictInbox', () => ({ ConflictInbox: () => null }));
vi.mock('../DeadLetterPanel', () => ({ DeadLetterPanel: () => null }));
vi.mock('../SyncStatusIndicator', () => ({ SyncStatusIndicator: () => null }));
// Settings' policy input and query run unchanged; unrelated panels stay isolated.
vi.mock('../../RetentionPage', () => ({ RetentionSection: () => null }));
vi.mock('../../settings/GpuControlCard', () => ({ GpuControlCard: () => null }));

/*
 * WBRC-1. The HTTP boundary is stubbed, not settingsApi: the real fetchSettings
 * guard, saveSettings and fetchApi error taxonomy all run. Malformed wire bodies
 * are therefore plain JSON, typed nowhere, exactly as the browser receives them.
 */

const SETTINGS_URL = 'http://example.test/wp-json/acx/v1/settings';
// Real neighbours of the settings route. Any request to one fails the test (see afterEach).
const ENDPOINTS = {
  settings: SETTINGS_URL,
  settingsTest: 'http://example.test/wp-json/acx/v1/settings/test',
  workbenchMedia: 'http://example.test/wp-json/acx/v1/workbench/media',
  recognitionAnalyze: 'http://example.test/wp-json/acx/v1/recognition/analyze',
  recognitionDescribe: 'http://example.test/wp-json/acx/v1/recognition/describe',
  recognitionJobs: 'http://example.test/wp-json/acx/v1/recognition/jobs',
  recognitionGpuStatus: 'http://example.test/wp-json/acx/v1/recognition/gpu/status',
  recognitionGpuIntent: 'http://example.test/wp-json/acx/v1/recognition/gpu/intent',
};

const COPY = {
  explain:
    'When on, scans use AI to find faces and suggest who they are. A change applies to scans and descriptions started afterwards; turning it off does not delete people already found or cancel work already running.',
  enable: 'Enable facial recognition',
  disable: 'Disable facial recognition',
  retry: 'Retry reading policy',
  saving: 'Saving…',
  reading: 'Reading…',
  savingStatus: 'Saving the change…',
  readingStatus: 'Reading the setting back from the site…',
  confirmed: (on: boolean) => `Saved and verified. Facial recognition is now ${on ? 'on' : 'off'}.`,
  readFailed: 'Could not read the current setting. Check your connection, then retry.',
  staleNote: 'Could not re-check the setting just now, so this shows the last value read.',
  rejected: (on: boolean) =>
    `The site did not save this change, so facial recognition is still ${on ? 'on' : 'off'}. You can try again.`,
  sessionExpired: 'Your session has expired, so the change was not saved. Reload the page to sign in again.',
  acceptedReadFailed: 'The site accepted the change, but reading it back failed. Retry reading before changing it again.',
  acceptedMismatch: (on: boolean) =>
    `The site accepted the change, but now reports facial recognition is ${on ? 'on' : 'off'}. It may have been changed elsewhere; retry reading to confirm.`,
  uncertainReadFailed: 'Could not confirm whether the change was saved. Retry reading to see the current setting.',
  unconfirmedRead: 'Could not confirm the save result. The current setting has been read from the site.',
  notApplied: (on: boolean) => `The change is not in effect: the site reports facial recognition is ${on ? 'on' : 'off'}.`,
  accessLost: 'Your account can no longer change site settings. Ask a site administrator to change this.',
  denied: 'Only site administrators can change this setting.',
  unknownCapability:
    'Could not confirm that your account can change this setting. Reload the page; if this continues, ask a site administrator.',
  asOfPageLoad: 'Shown as of when this page loaded.',
  asOfLastRead: 'Shown as last read from the site.',
};

/** Mirrors SettingsController::get_settings key for key, including fields SettingsResponse omits. */
const settingsBody = (recognitionEnabled: unknown): Record<string, unknown> => ({
  url: 'https://recognition.example.test',
  url_source: 'option',
  url_rejection_reason: null,
  url_rejection_source: null,
  url_rejection_value: null,
  effective_target_url: 'https://recognition.example.test',
  effective_target_mode: 'service',
  recognition_source: 'service',
  recognition_source_source: 'default',
  api_key_set: true,
  api_key_last4: '****wxyz',
  key_source: 'option',
  api_key_storage_notice: "This key is stored encrypted with a key derived from the site's auth salt.",
  tenant_id: 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee',
  tenant_id_source: 'option',
  tenant_paired: true,
  alt_style: 'alt_only',
  context_categories: ['attachment', 'post', 'taxonomy_terms', 'product'],
  context_categories_error: null,
  recognition_enabled: recognitionEnabled,
  allow_person_names: true,
  allow_person_names_error: null,
  allow_person_names_status: 200,
  allow_person_names_code: null,
  description_service_title: 'Description Service',
  description_budget: {
    max_attempts: 3,
    usage: { attempts: 0, successes: 0, failures: 0, cost_total: 0 },
    recent_errors: [],
  },
});

const withoutPolicyField = (): Record<string, unknown> => {
  const body = settingsBody(true);
  delete body.recognition_enabled;
  return body;
};

/** SettingsController::save_settings answers HTTP 200 for every one of these. */
const SAVE = {
  acknowledged: { saved: ['recognition_enabled'], result: 'ok' },
  fieldFailed: { saved: [], result: 'error', failed: ['recognition_enabled'] },
  partialFailed: { saved: ['url'], result: 'partial', failed: ['recognition_enabled'] },
  unacknowledged: { saved: [], result: 'ok' },
};

type Reply = () => Promise<Response>;

const json = (body: unknown, status = 200): Reply => () =>
  Promise.resolve(new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } }));
const wpError = (code: string, message: string, status: number): Reply => json({ code, message, data: { status } }, status);
const forbidden = wpError('rest_forbidden', 'Sorry, you are not allowed to do that.', 403);
const offline: Reply = () => Promise.reject(new TypeError('Failed to fetch'));
const unreadable: Reply = () => Promise.resolve(new Response('<html>proxy</html>', { status: 200 }));

/** A reply the test releases by hand, to observe the pending UI. */
const held = (): { reply: Reply; release: (body: unknown) => void } => {
  let resolveResponse: (response: Response) => void = () => {
    throw new Error('held reply was never requested');
  };
  const pending = new Promise<Response>((resolve) => {
    resolveResponse = resolve;
  });
  return {
    reply: () => pending,
    release: (body) => {
      resolveResponse(new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } }));
    },
  };
};

interface RecordedRequest {
  method: string;
  url: string;
  body: unknown;
  headers: Headers;
}

let client: QueryClient;
let requests: RecordedRequest[];
let unexpected: string[];
let reads: Reply[];
let writes: Reply[];

const settingsRequests = (method: string) => requests.filter((request) => request.method === method);

const nextReply = (queue: Reply[], label: string): Promise<Response> => {
  const reply = queue.shift();
  if (!reply) {
    unexpected.push(`unscripted ${label}`);
    return json({ code: 'unscripted' }, 500)();
  }
  return reply();
};

/** Page-load bootstrap. `unknown` because malformed values are part of the contract under test. */
const boot = (recognitionPolicy: unknown): void => {
  const raw: unknown = { nonce: 'abcdef1234', ajaxUrl: '/wp-admin/admin-ajax.php', endpoints: ENDPOINTS, recognitionPolicy };
  registerConfig(raw as ApiConfig);
};

const mount = () => render(<RecognitionPolicyControl />, { wrapper: createQueryWrapper(client) });
const control = () => screen.getByRole('group', { name: 'Facial recognition' });
const policyState = () => within(control()).getByText(/^(On|Off|Unknown|Checking…)$/);
const cachedSettings = () => client.getQueryData<SettingsResponse>(queryKeys.settings.all);
const actionButtons = () => within(control()).queryAllByRole('button');

/** Browsers blur a focused control when it becomes `disabled`; jsdom does not, so do it here. */
const blurLikeABrowser = (button: HTMLElement) => {
  act(() => {
    button.blur();
  });
};

const returnToWindow = () => {
  act(() => {
    focusManager.setFocused(false);
    focusManager.setFocused(true);
  });
};

beforeEach(() => {
  resetConfigCache();
  client = buildTestQueryClient();
  requests = [];
  unexpected = [];
  reads = [];
  writes = [];
  startScan.mockReset();
  vi.spyOn(window, 'confirm').mockImplementation(() => {
    throw new Error('the policy control must not ask for a repeated opt-in');
  });
  vi.stubGlobal(
    'fetch',
    vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url;
      const method = (init?.method ?? 'GET').toUpperCase();
      const body: unknown = typeof init?.body === 'string' ? JSON.parse(init.body) : undefined;
      requests.push({ method, url, body, headers: new Headers(init?.headers) });
      if (url === SETTINGS_URL && method === 'GET') {
        return nextReply(reads, 'GET /settings');
      }
      if (url === SETTINGS_URL && method === 'POST') {
        return nextReply(writes, 'POST /settings');
      }
      unexpected.push(`${method} ${url}`);
      return json({ code: 'unexpected_fixture_route' }, 500)();
    }),
  );
});

afterEach(async () => {
  cleanup();
  await client.cancelQueries();
  client.clear();
  focusManager.setFocused(undefined);
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  resetConfigCache();
  delete window.AltContextAdmin;
  expect(unexpected, 'only scripted GET/POST /settings requests may be sent').toEqual([]);
  expect({ reads: reads.length, writes: writes.length }, 'every scripted reply is consumed').toEqual({ reads: 0, writes: 0 });
});

describe('administrator live state', () => {
  it('mounts the real control beside Workbench scan actions and toggles without starting a scan', async () => {
    boot({ enabled: false, canManage: true });
    reads.push(json(settingsBody(false)), json(settingsBody(true)));
    writes.push(json(SAVE.acknowledged));
    const user = userEvent.setup();
    render(<WorkbenchPage />, { wrapper: createQueryWrapper(client) });

    const scan = screen.getByRole('button', { name: 'Scan media' });
    const panel = screen.getByRole('heading', { name: 'Recognition evidence' }).parentElement;
    expect(panel).toContainElement(control());
    expect(panel).toContainElement(scan);
    const action = await within(control()).findByRole('button', { name: COPY.enable });
    expect(action).toHaveClass('button-secondary');
    expect(scan).toHaveClass('button-primary');
    await user.click(action);

    await within(control()).findByText(COPY.confirmed(true));
    expect(startScan).not.toHaveBeenCalled();
    expect(scan).toBeEnabled();
    expect(settingsRequests('POST').map(({ body }) => body)).toEqual([{ recognition_enabled: true }]);
  });

  it.each([
    { from: false, key: '{Enter}' },
    { from: true, key: '[Space]' },
  ])('changes $from -> !$from by keyboard, posting only the policy field and confirming from a fresh read', async ({ from, key }) => {
    // The page-load hint deliberately disagrees: an administrator sees the live value.
    boot({ enabled: !from, canManage: true });
    reads.push(json(settingsBody(from)), json(settingsBody(!from)));
    writes.push(json(SAVE.acknowledged));
    const user = userEvent.setup();
    mount();

    const action = await screen.findByRole('button', { name: from ? COPY.disable : COPY.enable });
    expect(policyState()).toHaveTextContent(from ? 'On' : 'Off');
    expect(within(control()).getByText('Site-wide')).toBeInTheDocument();
    expect(within(control()).getByText(COPY.explain)).toBeInTheDocument();

    await user.tab();
    expect(action).toHaveFocus();
    await user.keyboard(key);

    expect(await within(control()).findByText(COPY.confirmed(!from))).toBeInTheDocument();
    expect(policyState()).toHaveTextContent(!from ? 'On' : 'Off');
    // Same DOM node, opposite action, focus kept: a keyboard user can act again in place.
    expect(action).toHaveAccessibleName(from ? COPY.enable : COPY.disable);
    expect(action).toBeEnabled();
    expect(action).toHaveFocus();

    expect(requests.map(({ method }) => method)).toEqual(['GET', 'POST', 'GET']);
    const [post] = settingsRequests('POST');
    expect(post?.body).toStrictEqual({ recognition_enabled: !from });
    expect(post?.headers.get('X-WP-Nonce')).toBe('abcdef1234');
    expect(post?.headers.get('Content-Type')).toBe('application/json');
    expect(cachedSettings()?.recognition_enabled).toBe(!from);
    // No URL, key, or other setting leaks into the Workbench surface.
    expect(control()).not.toHaveTextContent(/recognition\.example\.test|wxyz|aaaaaaaa/);
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument();
  });

  it('keeps the confirmed value in the shared Settings cache across a remount and re-reads on entry', async () => {
    boot({ enabled: false, canManage: true });
    const reentry = held();
    reads.push(json(settingsBody(false)), json(settingsBody(true)), reentry.reply);
    writes.push(json(SAVE.acknowledged));
    const user = userEvent.setup();
    const first = mount();

    await user.click(await screen.findByRole('button', { name: COPY.enable }));
    await within(control()).findByText(COPY.confirmed(true));
    first.unmount();

    mount();
    // The verified read is shown at once from the shared cache while a fresh read runs.
    expect(policyState()).toHaveTextContent('On');
    expect(screen.getByRole('button', { name: COPY.disable })).toBeInTheDocument();
    await waitFor(() => expect(settingsRequests('GET')).toHaveLength(3));
    reentry.release(settingsBody(true));
    await waitFor(() => expect(client.isFetching()).toBe(0));
    expect(settingsRequests('POST')).toHaveLength(1);
  });

  it.each([false, true])('SettingsPage immediately sees the verified %s -> !$from change from the shared cache', async (from) => {
    boot({ enabled: from, canManage: true });
    // A site without a service URL does not schedule Settings' separate connection probe.
    const snapshot = (enabled: boolean) => ({ ...settingsBody(enabled), url: '', effective_target_url: '' });
    const settingsEntry = held();
    reads.push(json(snapshot(from)), json(snapshot(!from)), settingsEntry.reply);
    writes.push(json(SAVE.acknowledged));
    const user = userEvent.setup();
    const workbench = mount();
    await user.click(await screen.findByRole('button', { name: from ? COPY.disable : COPY.enable }));
    await within(control()).findByText(COPY.confirmed(!from));
    workbench.unmount();

    render(<MemoryRouter initialEntries={['/settings']}><SettingsPage /></MemoryRouter>, {
      wrapper: createQueryWrapper(client),
    });
    const checkbox = screen.getByRole('checkbox', { name: 'Identify people in photos' });
    expect(checkbox).toHaveProperty('checked', !from);
    await waitFor(() => expect(settingsRequests('GET')).toHaveLength(3));
    settingsEntry.release(snapshot(!from));
    await waitFor(() => expect(client.isFetching()).toBe(0));
    expect(checkbox).toHaveProperty('checked', !from);
    expect(settingsRequests('POST')).toHaveLength(1);
  });

  it('re-reads when the operator returns to the window, so a change made elsewhere is not stale', async () => {
    boot({ enabled: false, canManage: true });
    reads.push(json(settingsBody(false)), json(settingsBody(true)));
    mount();

    await screen.findByRole('button', { name: COPY.enable });
    returnToWindow();

    expect(await screen.findByRole('button', { name: COPY.disable })).toBeInTheDocument();
    expect(policyState()).toHaveTextContent('On');
  });

  it('keeps the last value read, and says so, when a later re-check fails', async () => {
    boot({ enabled: false, canManage: true });
    reads.push(json(settingsBody(true)), offline);
    mount();

    await screen.findByRole('button', { name: COPY.disable });
    returnToWindow();

    expect(await within(control()).findByText(COPY.staleNote)).toBeInTheDocument();
    expect(policyState()).toHaveTextContent('On');
    expect(screen.getByRole('button', { name: COPY.disable })).toBeEnabled();
  });

  it('shows Checking… with no action until the first read lands', async () => {
    boot({ enabled: true, canManage: true });
    const first = held();
    reads.push(first.reply);
    mount();

    expect(policyState()).toHaveTextContent('Checking…');
    expect(actionButtons()).toEqual([]);

    first.release(settingsBody(false));
    expect(await screen.findByRole('button', { name: COPY.enable })).toBeEnabled();
  });
});

describe('busy feedback', () => {
  it('disables the action and parks focus in the control until the read-back confirms', async () => {
    boot({ enabled: false, canManage: true });
    const write = held();
    const readBack = held();
    reads.push(json(settingsBody(false)), readBack.reply);
    writes.push(write.reply);
    const user = userEvent.setup();
    mount();

    const action = await screen.findByRole('button', { name: COPY.enable });
    await user.click(action);

    expect(action).toHaveAccessibleName(COPY.saving);
    expect(action).toBeDisabled();
    expect(within(control()).getByRole('status')).toHaveTextContent(COPY.savingStatus);
    expect(policyState()).toHaveTextContent('Off');
    blurLikeABrowser(action);
    await waitFor(() => expect(control()).toHaveFocus());
    await user.click(action);

    write.release(SAVE.acknowledged);
    await waitFor(() => expect(action).toHaveAccessibleName(COPY.reading));
    expect(action).toBeDisabled();
    expect(within(control()).getByRole('status')).toHaveTextContent(COPY.readingStatus);
    // The pre-write value is known stale once the write is acknowledged: nothing shows it.
    expect(policyState()).toHaveTextContent('Checking…');
    expect(cachedSettings()).toBeUndefined();

    readBack.release(settingsBody(true));
    await within(control()).findByText(COPY.confirmed(true));
    expect(action).toHaveAccessibleName(COPY.disable);
    expect(action).toHaveFocus();
    expect(settingsRequests('POST')).toHaveLength(1);
  });

  it('does not reclaim focus the operator moved outside the control during a write', async () => {
    boot({ enabled: false, canManage: true });
    const write = held();
    const readBack = held();
    reads.push(json(settingsBody(false)), readBack.reply);
    writes.push(write.reply);
    const user = userEvent.setup();
    render(<><button type="button">Outside</button><RecognitionPolicyControl /></>, { wrapper: createQueryWrapper(client) });

    await user.click(await screen.findByRole('button', { name: COPY.enable }));
    const outside = screen.getByRole('button', { name: 'Outside' });
    await user.click(outside);
    write.release(SAVE.acknowledged);
    await screen.findByRole('button', { name: COPY.reading });
    expect(outside).toHaveFocus();
    readBack.release(settingsBody(true));
    await within(control()).findByText(COPY.confirmed(true));
    expect(outside).toHaveFocus();
  });
});

describe('read failures', () => {
  it.each([
    ['a body without recognition_enabled', json(withoutPolicyField())],
    ['recognition_enabled as the string "false"', json(settingsBody('false'))],
    ['recognition_enabled as null', json(settingsBody(null))],
    ['recognition_enabled as 0', json(settingsBody(0))],
    ['HTTP 400', wpError('bad_request', 'Invalid request.', 400)],
    ['HTTP 500', wpError('internal_server_error', 'There has been a critical error on this website.', 500)],
    ['a network failure', offline],
  ])('treats %s as Unknown and recovers inline with a read only', async (_label, failure) => {
    boot({ enabled: false, canManage: true });
    reads.push(failure, json(settingsBody(false)));
    const user = userEvent.setup();
    mount();

    const retry = await screen.findByRole('button', { name: COPY.retry });
    expect(policyState()).toHaveTextContent('Unknown');
    expect(within(control()).getByRole('alert')).toHaveTextContent(COPY.readFailed);
    expect(actionButtons()).toEqual([retry]);

    await user.click(retry);

    expect(await screen.findByRole('button', { name: COPY.enable })).toBeEnabled();
    expect(policyState()).toHaveTextContent('Off');
    expect(within(control()).queryByRole('alert')).not.toBeInTheDocument();
    expect(settingsRequests('POST')).toEqual([]);
  });

  it('withdraws every action and stops reading after a 403 on read', async () => {
    boot({ enabled: true, canManage: true });
    reads.push(forbidden);
    mount();

    expect(await within(control()).findByRole('alert')).toHaveTextContent(COPY.accessLost);
    expect(policyState()).toHaveTextContent('On');
    expect(within(control()).getByText(COPY.asOfPageLoad)).toBeInTheDocument();
    expect(actionButtons()).toEqual([]);

    returnToWindow();
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 20));
    });
    expect(settingsRequests('GET')).toHaveLength(1);
  });
});

describe('write outcomes', () => {
  it.each([
    ['HTTP 200 result=error', json(SAVE.fieldFailed), COPY.rejected(false)],
    ['HTTP 200 result=partial', json(SAVE.partialFailed), COPY.rejected(false)],
    ['HTTP 400', wpError('invalid_recognition_enabled', 'recognition_enabled must be a boolean.', 400), COPY.rejected(false)],
    ['HTTP 401 (signed out)', wpError('rest_not_logged_in', 'You are not currently logged in.', 401), COPY.sessionExpired],
  ])('%s is not success: the last confirmed value stays and the action is offered again', async (_label, rejection, message) => {
    boot({ enabled: false, canManage: true });
    reads.push(json(settingsBody(false)));
    writes.push(rejection, json(SAVE.acknowledged));
    reads.push(json(settingsBody(true)));
    const user = userEvent.setup();
    mount();

    await user.click(await screen.findByRole('button', { name: COPY.enable }));

    expect(await within(control()).findByRole('alert')).toHaveTextContent(message);
    expect(policyState()).toHaveTextContent('Off');
    expect(within(control()).queryByText(COPY.confirmed(true))).not.toBeInTheDocument();
    expect(cachedSettings()?.recognition_enabled).toBe(false);
    expect(settingsRequests('GET')).toHaveLength(1);

    // A refused write changed nothing, so an explicit second attempt is a new request.
    await user.click(screen.getByRole('button', { name: COPY.enable }));
    await within(control()).findByText(COPY.confirmed(true));
    expect(settingsRequests('POST')).toHaveLength(2);
  });

  it.each([
    ['HTTP 500, then the site reports the requested value', wpError('internal_server_error', 'Critical error.', 500), true, COPY.unconfirmedRead],
    ['HTTP 500, then the site reports the old value', wpError('internal_server_error', 'Critical error.', 500), false, COPY.notApplied(false)],
    ['HTTP 200 without acknowledging the field', json(SAVE.unacknowledged), false, COPY.notApplied(false)],
    ['HTTP 200 without acknowledgement, then a matching GET', json(SAVE.unacknowledged), true, COPY.unconfirmedRead],
    ['HTTP 200 partial with a saved policy field', json({ saved: ['recognition_enabled'], result: 'partial', failed: ['url'] }), true, COPY.unconfirmedRead],
    ['HTTP 200 error with a contradictory saved policy field', json({ saved: ['recognition_enabled'], result: 'error', failed: ['recognition_enabled'] }), true, COPY.unconfirmedRead],
    ['HTTP 200 with a malformed failed field', json({ ...SAVE.acknowledged, failed: null }), true, COPY.unconfirmedRead],
    ['HTTP 200 with a malformed saved list', json({ saved: ['recognition_enabled', 1], result: 'ok' }), true, COPY.unconfirmedRead],
    ['HTTP 200 ok contradicting a failed field', json({ ...SAVE.acknowledged, failed: ['url'] }), true, COPY.unconfirmedRead],
    ['an unreadable HTTP 200 body', unreadable, false, COPY.notApplied(false)],
  ])('%s: an uncertain write is settled by a fresh read', async (_label, uncertain, after, message) => {
    boot({ enabled: false, canManage: true });
    reads.push(json(settingsBody(false)), json(settingsBody(after)));
    writes.push(uncertain);
    const user = userEvent.setup();
    mount();

    await user.click(await screen.findByRole('button', { name: COPY.enable }));

    expect(await within(control()).findByRole('alert')).toHaveTextContent(message);
    expect(screen.getByRole('button', { name: after ? COPY.disable : COPY.enable })).toBeEnabled();
    expect(within(control()).queryByText(COPY.confirmed(true))).not.toBeInTheDocument();
    expect(policyState()).toHaveTextContent(after ? 'On' : 'Off');
    expect(cachedSettings()?.recognition_enabled).toBe(after);
    expect(settingsRequests('POST')).toHaveLength(1);
  });

  it('offers only a read when neither the write nor the read could be confirmed', async () => {
    boot({ enabled: false, canManage: true });
    reads.push(json(settingsBody(false)), offline, json(settingsBody(true)));
    writes.push(offline);
    const user = userEvent.setup();
    mount();

    await user.click(await screen.findByRole('button', { name: COPY.enable }));

    const retry = await screen.findByRole('button', { name: COPY.retry });
    expect(within(control()).getByRole('alert')).toHaveTextContent(COPY.uncertainReadFailed);
    expect(policyState()).toHaveTextContent('Unknown');
    expect(actionButtons()).toEqual([retry]);

    await user.click(retry);
    expect(await within(control()).findByRole('alert')).toHaveTextContent(COPY.unconfirmedRead);
    expect(policyState()).toHaveTextContent('On');
    expect(screen.getByRole('button', { name: COPY.disable })).toBeEnabled();
    expect(within(control()).queryByText(COPY.confirmed(true))).not.toBeInTheDocument();
    expect(settingsRequests('POST')).toHaveLength(1);
  });

  it.each([
    { label: 'fails', readBack: offline, state: 'Unknown', message: COPY.acceptedReadFailed, cached: undefined },
    { label: 'is malformed', readBack: json(settingsBody('true')), state: 'Unknown', message: COPY.acceptedReadFailed, cached: undefined },
    { label: 'mismatches', readBack: json(settingsBody(false)), state: 'Off', message: COPY.acceptedMismatch(false), cached: false },
  ])('never re-posts an acknowledged write whose read-back $label; it offers only a read retry', async ({ readBack, state, message, cached }) => {
    boot({ enabled: false, canManage: true });
    reads.push(json(settingsBody(false)), readBack, json(settingsBody(true)));
    writes.push(json(SAVE.acknowledged));
    const user = userEvent.setup();
    mount();

    await user.click(await screen.findByRole('button', { name: COPY.enable }));

    const retry = await screen.findByRole('button', { name: COPY.retry });
    expect(within(control()).getByRole('alert')).toHaveTextContent(message);
    expect(policyState()).toHaveTextContent(state);
    expect(actionButtons()).toEqual([retry]);
    expect(within(control()).queryByText(COPY.confirmed(true))).not.toBeInTheDocument();
    // Other readers of the shared key never keep presenting the pre-write value as current.
    expect(cachedSettings()?.recognition_enabled).toBe(cached);

    await user.click(retry);

    expect(await within(control()).findByText(COPY.confirmed(true))).toBeInTheDocument();
    expect(policyState()).toHaveTextContent('On');
    expect(settingsRequests('POST')).toHaveLength(1);
    expect(settingsRequests('GET')).toHaveLength(3);
  });

  it('accepts a second, explicit read as current when it still disagrees, and only then offers the action', async () => {
    boot({ enabled: false, canManage: true });
    reads.push(json(settingsBody(false)), json(settingsBody(false)), json(settingsBody(false)));
    writes.push(json(SAVE.acknowledged));
    const user = userEvent.setup();
    mount();

    await user.click(await screen.findByRole('button', { name: COPY.enable }));
    await user.click(await screen.findByRole('button', { name: COPY.retry }));

    expect(await within(control()).findByRole('alert')).toHaveTextContent(COPY.notApplied(false));
    expect(screen.getByRole('button', { name: COPY.enable })).toBeEnabled();
    expect(settingsRequests('POST')).toHaveLength(1);
  });

  it('requires a new GET after acknowledgement even when a pre-write focus read later matches', async () => {
    boot({ enabled: false, canManage: true });
    const beforeWrite = held();
    const readBack = held();
    reads.push(json(settingsBody(false)), beforeWrite.reply, readBack.reply);
    writes.push(json(SAVE.acknowledged));
    const user = userEvent.setup();
    mount();

    await screen.findByRole('button', { name: COPY.enable });
    returnToWindow();
    await waitFor(() => expect(settingsRequests('GET')).toHaveLength(2));
    await user.click(screen.getByRole('button', { name: COPY.enable }));
    await waitFor(() => expect(settingsRequests('GET')).toHaveLength(3));
    beforeWrite.release(settingsBody(true));
    await act(async () => { await Promise.resolve(); });
    expect(within(control()).queryByText(COPY.confirmed(true))).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: COPY.reading })).toBeDisabled();

    readBack.release(settingsBody(true));
    expect(await within(control()).findByText(COPY.confirmed(true))).toBeInTheDocument();
    expect(settingsRequests('POST')).toHaveLength(1);
  });

  it('stops reading and writing if capability is lost on post-write readback', async () => {
    boot({ enabled: false, canManage: true });
    reads.push(json(settingsBody(false)), forbidden);
    writes.push(json(SAVE.acknowledged));
    const user = userEvent.setup();
    mount();

    await user.click(await screen.findByRole('button', { name: COPY.enable }));
    expect(await within(control()).findByRole('alert')).toHaveTextContent(COPY.accessLost);
    expect(actionButtons()).toEqual([]);
    expect(within(control()).queryByText(COPY.confirmed(true))).not.toBeInTheDocument();
    returnToWindow();
    await act(async () => { await new Promise((resolve) => setTimeout(resolve, 20)); });
    expect(requests.map(({ method }) => method)).toEqual(['GET', 'POST', 'GET']);
  });

  it('withdraws every action, keeps focus in the control and stops reading after a 403 on write', async () => {
    boot({ enabled: false, canManage: true });
    reads.push(json(settingsBody(true)));
    writes.push(forbidden);
    const user = userEvent.setup();
    mount();

    const action = await screen.findByRole('button', { name: COPY.disable });
    await user.click(action);
    blurLikeABrowser(action);

    expect(await within(control()).findByRole('alert')).toHaveTextContent(COPY.accessLost);
    expect(policyState()).toHaveTextContent('On');
    expect(within(control()).getByText(COPY.asOfLastRead)).toBeInTheDocument();
    expect(actionButtons()).toEqual([]);
    expect(control()).toHaveFocus();

    returnToWindow();
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 20));
    });
    expect(settingsRequests('GET')).toHaveLength(1);
    expect(settingsRequests('POST')).toHaveLength(1);
  });
});

describe('without a confirmed manage capability', () => {
  it.each([
    { label: 'denied, On', policy: { enabled: true, canManage: false }, state: 'On', note: COPY.denied },
    { label: 'denied, Off', policy: { enabled: false, canManage: false }, state: 'Off', note: COPY.denied },
    { label: 'denied, malformed state', policy: { enabled: 'false', canManage: false }, state: 'Unknown', note: COPY.denied },
    { label: 'string capability', policy: { enabled: true, canManage: 'true' }, state: 'On', note: COPY.unknownCapability },
    { label: 'numeric capability', policy: { enabled: false, canManage: 1 }, state: 'Off', note: COPY.unknownCapability },
    { label: 'older bootstrap', policy: undefined, state: 'Unknown', note: COPY.unknownCapability },
  ])('$label: shows the page-load snapshot with no Settings request or action', ({ policy, state, note }) => {
    boot(policy);
    mount();

    expect(policyState()).toHaveTextContent(state);
    expect(within(control()).getByText(note)).toBeInTheDocument();
    expect(within(control()).getByText(COPY.asOfPageLoad)).toBeInTheDocument();
    expect(screen.getByText(/administrator/i)).toBeInTheDocument();
    expect(actionButtons()).toEqual([]);
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(requests).toEqual([]);
  });

  it('fails closed when no bootstrap was localized at all', () => {
    mount();

    expect(policyState()).toHaveTextContent('Unknown');
    expect(within(control()).getByText(COPY.unknownCapability)).toBeInTheDocument();
    expect(actionButtons()).toEqual([]);
    expect(requests).toEqual([]);
  });
});
