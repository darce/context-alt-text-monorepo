import React from 'react';
import { act, fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { SettingsPage } from '../SettingsPage';
import type { SettingsResponse } from '../../api/settingsApi';
import { createMockMutation, createMockQuery } from '../../test-utils/mockHooks';

type SettingsQueryResult = ReturnType<typeof createMockQuery<SettingsResponse>>;
type MockMutationResult = ReturnType<typeof createMockMutation>;

interface MutationOptions {
  onSuccess?: (data: unknown) => void | Promise<void>;
  onError?: (error: unknown) => void;
}

const {
  mockUseQuery,
  mockUseMutation,
  mockInvalidateQueries,
  mockFetchQuery,
  mockResetConfigCache,
} = vi.hoisted(() => ({
  mockUseQuery: vi.fn<() => SettingsQueryResult>(),
  mockUseMutation: vi.fn<(options?: MutationOptions) => MockMutationResult>(),
  mockInvalidateQueries: vi.fn(),
  mockFetchQuery: vi.fn(),
  mockResetConfigCache: vi.fn(),
}));

vi.mock('@wordpress/i18n', () => ({ __: (text: string) => text }));

vi.mock('@tanstack/react-query', async () => {
  const actual = await vi.importActual<typeof import('@tanstack/react-query')>('@tanstack/react-query');
  return {
    ...actual,
    useQuery: mockUseQuery,
    useMutation: mockUseMutation,
    useQueryClient: () => ({ invalidateQueries: mockInvalidateQueries, fetchQuery: mockFetchQuery }),
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
  let mutationCallIndex = 0;
  capturedSaveOptions = undefined;
  mockUseMutation.mockImplementation((options) => {
    mutationCallIndex += 1;
    if (mutationCallIndex === 1) {
      capturedSaveOptions = options;
      return createMockMutation({ mutate: saveMutate });
    }
    return createMockMutation({ mutate: testMutate });
  });
});

describe('SettingsPage routing autosave', () => {
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
});
