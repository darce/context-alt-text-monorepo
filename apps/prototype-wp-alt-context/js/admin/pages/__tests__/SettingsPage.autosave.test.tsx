import React from 'react';
import { act, fireEvent, render, renderHook, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { SettingsPage } from '../SettingsPage';
import { useSettingsPageState } from '../settings/useSettingsPageState';
import { saveSettings, testConnection, type SettingsResponse, type SaveSettingsResponse } from '../../api/settingsApi';
import { createMockMutation, createMockQuery } from '../../test-utils/mockHooks';

type SettingsQueryResult = ReturnType<typeof createMockQuery<SettingsResponse>>;
type MockMutationResult = ReturnType<typeof createMockMutation>;

interface MutationOptions {
  mutationFn?: unknown;
  onSuccess?: (data: unknown, variables?: unknown) => void | Promise<void>;
  onError?: (error: unknown) => void;
}

const {
  mockUseQuery,
  mockUseMutation,
  mockInvalidateQueries,
  mockFetchQuery,
  mockGetQueryData,
  mockResetConfigCache,
} = vi.hoisted(() => ({
  mockUseQuery: vi.fn<() => SettingsQueryResult>(),
  mockUseMutation: vi.fn<(options?: MutationOptions) => MockMutationResult>(),
  mockInvalidateQueries: vi.fn(),
  mockFetchQuery: vi.fn(),
  mockGetQueryData: vi.fn(),
  mockResetConfigCache: vi.fn(),
}));

vi.mock('@wordpress/i18n', () => ({ __: (text: string) => text }));

vi.mock('@tanstack/react-query', async () => {
  const actual = await vi.importActual<typeof import('@tanstack/react-query')>('@tanstack/react-query');
  return {
    ...actual,
    useQuery: mockUseQuery,
    useMutation: mockUseMutation,
    useQueryClient: () => ({
      invalidateQueries: mockInvalidateQueries,
      fetchQuery: mockFetchQuery,
      getQueryData: mockGetQueryData,
    }),
  };
});

vi.mock('../../api/settingsApi', async () => {
  const actual = await vi.importActual<typeof import('../../api/settingsApi')>('../../api/settingsApi');
  return { ...actual, fetchSettings: vi.fn(), saveSettings: vi.fn(), testConnection: vi.fn() };
});

vi.mock('../../api/config', () => ({ resetConfigCache: mockResetConfigCache }));
vi.mock('../RetentionPage', () => ({ RetentionSection: () => null }));
vi.mock('../settings/GpuControlCard', () => ({ GpuControlCard: () => null }));
vi.mock('../settings/SettingsRoutingBanner', () => ({ SettingsRoutingBanner: () => null }));

const configuredSettings: SettingsResponse = {
  url: 'https://api.example.com',
  url_source: 'option',
  url_rejection_reason: null,
  url_rejection_source: null,
  url_rejection_value: null,
  effective_target_url: 'https://api.example.com',
  effective_target_mode: 'service',
  recognition_source: 'service',
  recognition_source_source: 'option',
  api_key_set: true,
  api_key_last4: '****abcd',
  key_source: 'option',
  tenant_id: 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee',
  tenant_id_source: 'option',
  tenant_paired: false,
  alt_style: 'alt_only',
  recognition_enabled: true,
  allow_person_names: true,
  allow_person_names_error: null,
  description_budget: {
    max_attempts: -1,
    usage: { attempts: 0, successes: 0, failures: 0, cost_total: 0 },
    recent_errors: [],
  },
};

const saveMutate = vi.fn();
const testMutate = vi.fn();
let capturedSaveOptions: MutationOptions | undefined;
let capturedTestOptions: MutationOptions | undefined;
let saveMutationPending = false;

const SettingsPageWithRouter = (): React.JSX.Element => (
  <MemoryRouter initialEntries={['/settings']}>
    <SettingsPage />
  </MemoryRouter>
);

const renderSettings = (data: SettingsResponse = configuredSettings) => {
  mockUseQuery.mockReturnValue(createMockQuery({ data }));
  return render(<SettingsPageWithRouter />);
};

beforeEach(() => {
  vi.clearAllMocks();
  mockFetchQuery.mockResolvedValue(configuredSettings);
  mockGetQueryData.mockReturnValue(configuredSettings);
  capturedSaveOptions = undefined;
  capturedTestOptions = undefined;
  saveMutationPending = false;
  saveMutate.mockImplementation(() => {
    saveMutationPending = true;
  });
  mockUseMutation.mockImplementation((options) => {
    if (options?.mutationFn === saveSettings) {
      capturedSaveOptions = options;
      return createMockMutation({ mutate: saveMutate, isPending: saveMutationPending });
    }
    if (options?.mutationFn === testConnection) {
      capturedTestOptions = options;
      return createMockMutation({ mutate: testMutate });
    }
    throw new Error('Unexpected mutation in SettingsPage autosave test.');
  });
});

describe('SettingsPage draft revision acknowledgements', () => {
  it('retains a newer URL revert until its own acknowledgement, then follows persisted updates', () => {
    const { result, rerender } = renderHook(({ settings }) => useSettingsPageState(settings), {
      initialProps: { settings: configuredSettings },
    });
    const urlA = 'https://pending.example.com';
    act(() => { result.current.dispatch({ type: 'setUrl', value: urlA }); });
    const revisionA = result.current.state.urlRevision;
    act(() => { result.current.dispatch({ type: 'setUrl', value: configuredSettings.url }); });
    const revisionRevert = result.current.state.urlRevision;
    act(() => { result.current.dispatch({ type: 'acknowledgeUrl', revision: revisionA }); });
    rerender({ settings: { ...configuredSettings, url: urlA, effective_target_url: urlA } });
    expect(result.current.state.url).toBe(configuredSettings.url);
    expect(result.current.state.acknowledgedUrlRevision).toBe(revisionA);
    act(() => { result.current.dispatch({ type: 'acknowledgeUrl', revision: revisionRevert }); });
    rerender({ settings: { ...configuredSettings } });
    const externalUrl = 'https://external.example.com';
    rerender({ settings: { ...configuredSettings, url: externalUrl, effective_target_url: externalUrl } });
    expect(result.current.state.url).toBe(externalUrl);
  });

  it('clears a same-value key only for its own edit revision', () => {
    const { result } = renderHook(() => useSettingsPageState(configuredSettings));
    act(() => { result.current.dispatch({ type: 'setApiKey', value: 'draft-A' }); });
    const revisionA = result.current.state.apiKeyRevision;
    act(() => { result.current.dispatch({ type: 'setApiKey', value: 'draft-B' }); });
    act(() => { result.current.dispatch({ type: 'setApiKey', value: 'draft-A' }); });
    const revisionNewA = result.current.state.apiKeyRevision;
    act(() => { result.current.dispatch({ type: 'acknowledgeApiKey', value: 'draft-A', revision: revisionA }); });
    expect(result.current.state.apiKey).toBe('draft-A');
    act(() => { result.current.dispatch({ type: 'acknowledgeApiKey', value: 'draft-A', revision: revisionNewA }); });
    expect(result.current.state.apiKey).toBe('');
  });
});

describe('SettingsPage routing autosave', () => {
  it.each([
    ['resolve', 'blur'], ['reject', 'blur'],
    ['resolve', 'submit'], ['reject', 'submit'],
  ])('retains and retries B while A is pending: %s / %s', async (outcome, intent) => {
    let resolveRequest!: (response: SaveSettingsResponse) => void;
    let rejectRequest!: (error: Error) => void;
    const request = new Promise<SaveSettingsResponse>((resolve, reject) => {
      resolveRequest = resolve;
      rejectRequest = reject;
    });
    let completion: Promise<unknown> | undefined;
    saveMutate.mockImplementationOnce(() => {
      saveMutationPending = true;
      const options = capturedSaveOptions;
      completion = request.then(
        (response) => options?.onSuccess?.(response),
        (error: Error) => options?.onError?.(error),
      );
    });
    renderSettings();
    const key = screen.getByLabelText('API Key');
    fireEvent.change(key, { target: { value: 'draft-A' } });
    fireEvent.blur(key);
    fireEvent.change(key, { target: { value: 'draft-B' } });
    if (intent === 'blur') {
      fireEvent.blur(key);
    } else {
      fireEvent.submit(screen.getByRole('button', { name: 'Saving…' }).closest('form')!);
    }
    expect(saveMutate).toHaveBeenCalledTimes(1);
    saveMutationPending = false;
    await act(async () => {
      if (outcome === 'resolve') {
        resolveRequest({ saved: ['api_key'], result: 'ok' });
      } else {
        rejectRequest(new Error('save failed'));
      }
      await completion;
    });
    expect(key).toHaveValue('draft-B');
    expect(saveMutate).toHaveBeenNthCalledWith(2, { api_key: 'draft-B' });
  });

  it('preserves a failed secret across partial-save settings readback', async () => {
    const view = renderSettings();
    const key = screen.getByLabelText('API Key');
    fireEvent.change(key, { target: { value: 'unsaved-secret' } });
    fireEvent.blur(key);
    saveMutationPending = false;
    await act(async () => {
      await capturedSaveOptions?.onSuccess?.({ saved: [], failed: ['api_key'], result: 'error' });
    });
    mockUseQuery.mockReturnValue(createMockQuery({ data: { ...configuredSettings } }));
    view.rerender(<SettingsPageWithRouter />);
    expect(key).toHaveValue('unsaved-secret');
  });

  it.each(['resolve', 'reject'])('retains URL B and its blur intent across A: %s', async (outcome) => {
    const urlA = 'https://first.example.com';
    const urlB = 'https://second.example.com';
    const readback = { ...configuredSettings, url: urlA, effective_target_url: urlA };
    mockFetchQuery.mockResolvedValue(readback);
    const view = renderSettings();
    const url = screen.getByLabelText('Service API URL');
    fireEvent.change(url, { target: { value: urlA } });
    fireEvent.blur(url);
    fireEvent.change(url, { target: { value: urlB } });
    fireEvent.blur(url);
    saveMutationPending = false;
    await act(async () => {
      if (outcome === 'resolve') {
        await capturedSaveOptions?.onSuccess?.({ saved: ['url'], result: 'ok' });
      } else {
        capturedSaveOptions?.onError?.(new Error('save failed'));
      }
    });
    mockUseQuery.mockReturnValue(createMockQuery({ data: readback }));
    view.rerender(<SettingsPageWithRouter />);
    expect(url).toHaveValue(urlB);
    expect(saveMutate).toHaveBeenNthCalledWith(2, { url: urlB });
  });

  it.each(['blur', 'submit'])('clears only the exact acknowledged key from %s', async (intent) => {
    renderSettings();
    const key = screen.getByLabelText('API Key');
    fireEvent.change(key, { target: { value: 'draft-A' } });
    if (intent === 'blur') {
      fireEvent.blur(key);
    } else {
      fireEvent.submit(screen.getByRole('button', { name: 'Save Settings' }).closest('form')!);
    }
    await act(async () => {
      await capturedSaveOptions?.onSuccess?.({ saved: ['api_key'], result: 'ok' });
    });
    expect(key).toHaveValue('');
    expect(saveMutate).toHaveBeenCalledTimes(1);
  });

  it('retains an uncommitted newer key when the older draft succeeds', async () => {
    renderSettings();
    const key = screen.getByLabelText('API Key');
    fireEvent.change(key, { target: { value: 'draft-A' } });
    fireEvent.blur(key);
    fireEvent.change(key, { target: { value: 'draft-B' } });
    await act(async () => {
      await capturedSaveOptions?.onSuccess?.({ saved: ['api_key'], result: 'ok' });
    });
    expect(key).toHaveValue('draft-B');
    expect(saveMutate).toHaveBeenCalledTimes(1);
  });

  it('retains a secret on transport failure and allows retry', async () => {
    renderSettings();
    const key = screen.getByLabelText('API Key');
    fireEvent.change(key, { target: { value: 'draft-A' } });
    fireEvent.blur(key);
    saveMutationPending = false;
    await act(async () => { capturedSaveOptions?.onError?.(new Error('save failed')); });
    expect(key).toHaveValue('draft-A');
    fireEvent.blur(key);
    expect(saveMutate).toHaveBeenNthCalledWith(2, { api_key: 'draft-A' });
  });

  it('does not probe or lose the failed key when only an unrelated field persists', async () => {
    const view = renderSettings();
    testMutate.mockClear();
    const key = screen.getByLabelText('API Key');
    fireEvent.change(key, { target: { value: 'draft-A' } });
    fireEvent.change(screen.getByLabelText('Maximum description attempts'), { target: { value: '4' } });
    fireEvent.submit(screen.getByRole('button', { name: 'Save Settings' }).closest('form')!);
    await act(async () => {
      await capturedSaveOptions?.onSuccess?.({ saved: ['description_budget'], failed: ['api_key'], result: 'partial' });
    });
    mockUseQuery.mockReturnValue(createMockQuery({ data: { ...configuredSettings } }));
    view.rerender(<SettingsPageWithRouter />);
    expect(key).toHaveValue('draft-A');
    expect(testMutate).not.toHaveBeenCalled();
  });

  it('waits for deferred persisted readback before probing', async () => {
    let release!: (data: SettingsResponse) => void;
    mockFetchQuery.mockReturnValue(new Promise<SettingsResponse>((resolve) => { release = resolve; }));
    renderSettings();
    testMutate.mockClear();
    const url = screen.getByLabelText('Service API URL');
    fireEvent.change(url, { target: { value: 'https://new.example.com' } });
    fireEvent.blur(url);
    let completion: void | Promise<void> = undefined;
    await act(async () => {
      completion = capturedSaveOptions?.onSuccess?.({ saved: ['url'], result: 'ok' });
      await Promise.resolve();
    });
    expect(testMutate).not.toHaveBeenCalled();
    await act(async () => {
      release({ ...configuredSettings, url: 'https://new.example.com', effective_target_url: 'https://new.example.com' });
      await completion;
    });
    expect(testMutate).toHaveBeenCalledTimes(1);
  });

  it('queues a settings submit during a routing save and saves it after the refetch', async () => {
    const savedUrl = 'https://new-api.example.com';
    const refreshedSettings = { ...configuredSettings, url: savedUrl };
    mockFetchQuery.mockResolvedValue(refreshedSettings);
    mockGetQueryData.mockReturnValue(refreshedSettings);
    renderSettings();

    fireEvent.change(screen.getByLabelText('Maximum description attempts'), {
      target: { value: '4' },
    });
    const url = screen.getByLabelText('Service API URL');
    fireEvent.change(url, { target: { value: savedUrl } });
    fireEvent.blur(url);

    expect(saveMutate).toHaveBeenNthCalledWith(1, { url: savedUrl });
    const saveButton = screen.getByRole('button', { name: 'Saving…' });
    fireEvent.submit(saveButton.closest('form') as HTMLFormElement);

    saveMutationPending = false;
    await act(async () => {
      await capturedSaveOptions?.onSuccess?.({ saved: ['url'], result: 'ok' });
    });

    expect(saveMutate).toHaveBeenNthCalledWith(2, { description_budget: { max_attempts: 4 } });
  });

  it('re-probes after a queued URL change and ignores the earlier probe result', async () => {
    const urlA = 'https://first-api.example.com';
    const urlB = 'https://second-api.example.com';
    const settingsA = { ...configuredSettings, url: urlA, effective_target_url: urlA };
    const settingsB = { ...configuredSettings, url: urlB, effective_target_url: urlB };
    mockFetchQuery.mockResolvedValueOnce(settingsA).mockResolvedValueOnce(settingsB);
    const resolveProbe = new Map<object, (data: unknown) => void>();
    testMutate.mockImplementation((variables) => {
      const options = capturedTestOptions;
      resolveProbe.set(variables as object, (data) => options?.onSuccess?.(data, variables));
    });
    renderSettings();
    const url = screen.getByLabelText('Service API URL');
    fireEvent.change(url, { target: { value: urlA } });
    fireEvent.blur(url);
    expect(saveMutate).toHaveBeenNthCalledWith(1, { url: urlA });

    fireEvent.change(url, { target: { value: urlB } });
    fireEvent.change(screen.getByLabelText('Maximum description attempts'), {
      target: { value: '4' },
    });
    fireEvent.submit(screen.getByRole('button', { name: 'Saving…' }).closest('form') as HTMLFormElement);

    saveMutationPending = false;
    await act(async () => {
      await capturedSaveOptions?.onSuccess?.({ saved: ['url'], result: 'ok' });
    });
    const probeFromA = testMutate.mock.calls[1]?.[0] as object;

    expect(saveMutate).toHaveBeenNthCalledWith(2, {
      url: urlB,
      description_budget: { max_attempts: 4 },
    });
    saveMutationPending = false;
    await act(async () => {
      await capturedSaveOptions?.onSuccess?.({ saved: ['url', 'description_budget'], result: 'ok' });
    });

    expect(testMutate).toHaveBeenCalledTimes(3);
    expect(screen.getByTestId('acx-settings-save-message')).toHaveTextContent('Settings saved.');
    const currentProbe = testMutate.mock.calls[2]?.[0] as object;
    await act(async () => {
      resolveProbe.get(currentProbe)?.({ outcome: 'network_error' });
    });
    await act(async () => {
      resolveProbe.get(probeFromA)?.({ outcome: 'connected' });
    });

    expect(screen.getByTestId('acx-test-connection-banner')).toHaveAttribute(
      'data-outcome',
      'network_error',
    );
  });

  it('does not resend an API key saved by the in-flight autosave', async () => {
    renderSettings();

    fireEvent.change(screen.getByLabelText('API Key'), { target: { value: 'new-secret' } });
    fireEvent.blur(screen.getByLabelText('API Key'));
    expect(saveMutate).toHaveBeenNthCalledWith(1, { api_key: 'new-secret' });

    fireEvent.change(screen.getByLabelText('Maximum description attempts'), {
      target: { value: '4' },
    });
    fireEvent.submit(screen.getByRole('button', { name: 'Saving…' }).closest('form') as HTMLFormElement);

    saveMutationPending = false;
    await act(async () => {
      await capturedSaveOptions?.onSuccess?.({ saved: ['api_key'], result: 'ok' });
    });

    expect(saveMutate).toHaveBeenNthCalledWith(2, { description_budget: { max_attempts: 4 } });
  });

  it('runs a queued settings submit after a routing save rejects', async () => {
    renderSettings();

    fireEvent.change(screen.getByLabelText('Maximum description attempts'), {
      target: { value: '4' },
    });
    const url = screen.getByLabelText('Service API URL');
    fireEvent.change(url, { target: { value: 'https://new-api.example.com' } });
    fireEvent.blur(url);
    const saveButton = screen.getByRole('button', { name: 'Saving…' });
    fireEvent.submit(saveButton.closest('form') as HTMLFormElement);

    saveMutationPending = false;
    await act(async () => {
      capturedSaveOptions?.onError?.(new Error('request failed'));
    });

    expect(saveMutate).toHaveBeenNthCalledWith(2, {
      url: 'https://new-api.example.com',
      description_budget: { max_attempts: 4 },
    });
  });

  it('submits one save when there is no save already pending', () => {
    renderSettings();
    fireEvent.change(screen.getByLabelText('Maximum description attempts'), {
      target: { value: '4' },
    });

    fireEvent.click(screen.getByRole('button', { name: 'Save Settings' }));

    expect(saveMutate).toHaveBeenCalledTimes(1);
    expect(saveMutate).toHaveBeenCalledWith({ description_budget: { max_attempts: 4 } });
  });

  it('saves only a changed URL on blur, then checks health after an OK save', async () => {
    renderSettings();
    testMutate.mockClear(); // Ignore the one automatic mount probe.

    const url = screen.getByLabelText('Service API URL');
    fireEvent.change(url, { target: { value: 'https://new-api.example.com' } });
    fireEvent.blur(url);

    expect(saveMutate).toHaveBeenCalledWith({ url: 'https://new-api.example.com' });
    expect(testMutate).not.toHaveBeenCalled();
    expect(screen.getByTestId('acx-settings-routing-save-message')).toHaveTextContent('Saving…');

    await act(async () => {
      await capturedSaveOptions?.onSuccess?.({ saved: ['url'], result: 'ok' });
    });

    expect(testMutate).toHaveBeenCalledTimes(1);
  });

  it('saves the API key only after blur, then checks health after an OK save', async () => {
    renderSettings();
    testMutate.mockClear();

    const apiKey = screen.getByLabelText('API Key');
    fireEvent.change(apiKey, { target: { value: 'new-secret' } });
    expect(saveMutate).not.toHaveBeenCalled();

    fireEvent.blur(apiKey);
    expect(saveMutate).toHaveBeenCalledWith({ api_key: 'new-secret' });

    await act(async () => {
      await capturedSaveOptions?.onSuccess?.({ saved: ['api_key'], result: 'ok' });
    });

    expect(testMutate).toHaveBeenCalledTimes(1);
  });

  it('does not save a key while the operator is still typing', () => {
    renderSettings();

    fireEvent.change(screen.getByLabelText('API Key'), { target: { value: 'partial-secret' } });

    expect(saveMutate).not.toHaveBeenCalled();
  });

  it('shows a partial save error and does not check health', async () => {
    renderSettings();
    testMutate.mockClear();

    const url = screen.getByLabelText('Service API URL');
    fireEvent.change(url, { target: { value: 'https://new-api.example.com' } });
    fireEvent.blur(url);

    await act(async () => {
      await capturedSaveOptions?.onSuccess?.({ saved: ['url'], failed: ['api_key'], result: 'partial' });
    });

    const message = screen.getByTestId('acx-settings-routing-save-message');
    expect(message).toHaveTextContent('Could not save settings.');
    expect(message).toHaveTextContent('api_key');
    expect(message).toHaveAttribute('role', 'alert');
    expect(testMutate).not.toHaveBeenCalled();
  });

  it('saves unsaved URL edits before checking health from the button', async () => {
    renderSettings();
    testMutate.mockClear();

    fireEvent.change(screen.getByLabelText('Service API URL'), {
      target: { value: 'https://new-api.example.com' },
    });
    const checkButton = screen.getByRole('button', { name: 'Check health' });
    expect(checkButton).toBeEnabled();
    fireEvent.click(checkButton);

    expect(saveMutate).toHaveBeenCalledWith({ url: 'https://new-api.example.com' });
    expect(testMutate).not.toHaveBeenCalled();

    await act(async () => {
      await capturedSaveOptions?.onSuccess?.({ saved: ['url'], result: 'ok' });
    });

    expect(testMutate).toHaveBeenCalledTimes(1);
  });

  it('automatically checks a configured target once per page mount', () => {
    const view = renderSettings();

    expect(testMutate).toHaveBeenCalledTimes(1);
    view.rerender(<SettingsPageWithRouter />);
    expect(testMutate).toHaveBeenCalledTimes(1);
  });

  it('waits for the Settings hook to publish a routing save before checking the refreshed target', async () => {
    const savedUrl = 'https://new-api.example.com';
    const refreshedSettings = {
      ...configuredSettings,
      url: savedUrl,
      effective_target_url: savedUrl,
    };
    let settingsQuery = createMockQuery({ data: configuredSettings, dataUpdatedAt: 300 });
    mockUseQuery.mockImplementation(() => settingsQuery);
    mockFetchQuery.mockResolvedValue(refreshedSettings);
    const view = render(<SettingsPageWithRouter />);
    expect(testMutate).toHaveBeenCalledTimes(1);
    const oldRequestVariables = testMutate.mock.calls[0]?.[0] as object;

    const url = screen.getByLabelText('Service API URL');
    fireEvent.change(url, { target: { value: savedUrl } });
    fireEvent.blur(url);
    expect(saveMutate).toHaveBeenCalledWith({ url: savedUrl });

    let releaseSettingsInvalidation: (() => void) | undefined;
    mockInvalidateQueries.mockImplementationOnce(() => new Promise<void>((resolve) => {
      releaseSettingsInvalidation = resolve;
    }));
    let saveCompletion: void | Promise<void> = undefined;
    act(() => {
      saveCompletion = capturedSaveOptions?.onSuccess?.({ saved: ['url'], result: 'ok' });
    });
    expect(releaseSettingsInvalidation).toBeDefined();

    // The successful save starts a real Settings refetch while the hook still
    // exposes its cached snapshot.
    settingsQuery = createMockQuery({
      data: configuredSettings,
      dataUpdatedAt: 300,
      isFetching: true,
    });
    view.rerender(<SettingsPageWithRouter />);
    await act(async () => {
      releaseSettingsInvalidation?.();
      await saveCompletion;
      saveMutationPending = false;
    });

    expect(mockFetchQuery).toHaveBeenCalled();
    expect(screen.getByTestId('acx-settings-routing-save-message')).toHaveTextContent(
      'Saved — checking health…',
    );
    // fetchQuery has returned the new settings, but the hook remains on the
    // cached snapshot while its refetch is pending.
    expect(testMutate).toHaveBeenCalledTimes(1);

    settingsQuery = createMockQuery({
      data: refreshedSettings,
      dataUpdatedAt: 301,
      isFetching: false,
    });
    view.rerender(<SettingsPageWithRouter />);

    expect(testMutate).toHaveBeenCalledTimes(2);
    const replacementRequestVariables = testMutate.mock.calls[1]?.[0] as object;
    expect(replacementRequestVariables).toEqual({});
    expect(replacementRequestVariables).not.toBe(oldRequestVariables);
    await act(async () => {
      await capturedTestOptions?.onSuccess?.({
        outcome: 'connected',
        status_code: 200,
        probe_mode: 'service_auth',
        probed_url: `${savedUrl}/health/detailed`,
        body: { status: 'ok', model_cache: { status: 'ok', profile: 'insightface' } },
      }, replacementRequestVariables);
    });

    expect(screen.getByTestId('acx-target-card-service')).toHaveTextContent('Reachable');
    expect(screen.getAllByText('Recognition engine: InsightFace')).toHaveLength(1);
    expect(screen.queryByTestId('acx-settings-routing-save-message')).not.toBeInTheDocument();
  });

  it('keeps the newer probe result when the older probe resolves last', async () => {
    const resolveProbeByVariables = new Map<object, (data: unknown) => void>();
    testMutate.mockImplementation((variables) => {
      const mutationOptions = capturedTestOptions;
      resolveProbeByVariables.set(variables as object, (data) => {
        mutationOptions?.onSuccess?.(data, variables);
      });
    });

    renderSettings();
    const olderProbeVariables = testMutate.mock.calls[0]?.[0] as object;

    fireEvent.change(screen.getByLabelText('API Key'), { target: { value: 'new-secret' } });
    fireEvent.blur(screen.getByLabelText('API Key'));

    await act(async () => {
      await capturedSaveOptions?.onSuccess?.({ saved: ['api_key'], result: 'ok' });
    });

    const newerProbeVariables = testMutate.mock.calls.find(
      ([variables]) => variables !== olderProbeVariables,
    )?.[0] as object;
    expect(resolveProbeByVariables.has(olderProbeVariables)).toBe(true);
    expect(resolveProbeByVariables.has(newerProbeVariables)).toBe(true);

    await act(async () => {
      resolveProbeByVariables.get(newerProbeVariables)?.({ outcome: 'network_error' });
    });
    await act(async () => {
      resolveProbeByVariables.get(olderProbeVariables)?.({ outcome: 'connected' });
    });

    expect(screen.getByTestId('acx-test-connection-banner')).toHaveAttribute(
      'data-outcome',
      'network_error',
    );
  });
});
