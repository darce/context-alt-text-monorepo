import React from 'react';
import { act, render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

import { SettingsPage } from '../SettingsPage';
import type { SettingsResponse, TestConnectionOutcomeValue, TestConnectionResponse } from '../../api/settingsApi';
import { createMockMutation, createMockQuery } from '../../test-utils/mockHooks';

type QueryHookResult = ReturnType<typeof createMockQuery<SettingsResponse>>;
type MutationHookResult = ReturnType<typeof createMockMutation>;

interface CapturedMutationOptions {
  onSuccess?: (data: unknown) => void;
  onError?: (err: unknown) => void;
}

const { mockUseQuery, mockUseMutation } = vi.hoisted(() => ({
  mockUseQuery: vi.fn<() => QueryHookResult>(),
  mockUseMutation: vi.fn<(options?: CapturedMutationOptions) => MutationHookResult>(),
}));

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
  sprintf: (fmt: string, ...args: unknown[]) => {
    let i = 0;
    return fmt.replace(/%[ds]/g, () => String(args[i++]));
  },
}));

vi.mock('../../api/settingsApi', async () => {
  const actual = await vi.importActual<typeof import('../../api/settingsApi')>('../../api/settingsApi');
  return {
    ...actual,
    fetchSettings: vi.fn(),
    saveSettings: vi.fn(),
    testConnection: vi.fn(),
  };
});

const { mockResetConfigCache } = vi.hoisted(() => ({
  mockResetConfigCache: vi.fn(),
}));

vi.mock('../../api/config', () => ({
  getEndpoint: (key: string) => `/acx/v1/${key}`,
  getConfig: () => ({
    nonce: 'test-nonce',
    endpoints: { settings: '/acx/v1/settings', settingsTest: '/acx/v1/settings/test' },
  }),
  resetConfigCache: mockResetConfigCache,
}));

vi.mock('@tanstack/react-query', async () => {
  const actual = await vi.importActual<typeof import('@tanstack/react-query')>('@tanstack/react-query');
  return {
    ...actual,
    useQueryClient: () => ({ invalidateQueries: vi.fn() }),
    useQuery: mockUseQuery,
    useMutation: mockUseMutation,
  };
});

const defaultSettings: SettingsResponse = {
  url: 'https://api.example.com',
  url_source: 'option',
  local_url: 'http://localhost:8000',
  local_url_source: 'default',
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
};

const saveMutate = vi.fn();
const testMutate = vi.fn();
let capturedTestOptions: CapturedMutationOptions | undefined;

const installMutationMock = (): void => {
  let mutationCallIndex = 0;
  capturedTestOptions = undefined;
  mockUseMutation.mockImplementation((options) => {
    mutationCallIndex++;
    if (mutationCallIndex % 2 === 1) {
      return createMockMutation({ mutate: saveMutate });
    }
    capturedTestOptions = options;
    return createMockMutation({ mutate: testMutate });
  });
};

beforeEach(() => {
  vi.clearAllMocks();
  installMutationMock();
});

describe('SettingsPage', () => {
  it('shows loading state initially', () => {
    mockUseQuery.mockReturnValue(createMockQuery({ status: 'pending' }));
    render(<SettingsPage />);
    expect(screen.getByText('Loading settings…')).toBeInTheDocument();
  });

  it('shows error state when settings fail to load', () => {
    mockUseQuery.mockReturnValue(createMockQuery({ isError: true, error: new Error('fail') }));
    render(<SettingsPage />);
    expect(screen.getByText('Failed to load settings.')).toBeInTheDocument();
  });

  it('renders the settings form with loaded data', () => {
    mockUseQuery.mockReturnValue(createMockQuery({ data: defaultSettings }));
    render(<SettingsPage />);

    expect(screen.getByLabelText('Service API URL')).toHaveValue('https://api.example.com');
    expect(screen.getByLabelText('Local service URL')).toHaveValue('http://localhost:8000');
    expect(screen.getByLabelText('Service')).toBeChecked();
    expect(screen.getByTestId('acx-effective-routing')).toHaveTextContent('https://api.example.com');
    expect(screen.getByRole('button', { name: 'Save Settings' })).toBeEnabled();
    expect(screen.getByRole('button', { name: 'Test active target' })).toBeEnabled();
  });

  it('saves the recognition source when the operator switches to local mode', () => {
    mockUseQuery.mockReturnValue(createMockQuery({ data: defaultSettings }));
    render(<SettingsPage />);

    fireEvent.click(screen.getByLabelText('Local'));
    fireEvent.click(screen.getByRole('button', { name: 'Save Settings' }));

    expect(saveMutate).toHaveBeenCalledWith({ recognition_source: 'local' });
  });

  it('saves settings when the form is submitted with changes', () => {
    mockUseQuery.mockReturnValue(createMockQuery({ data: defaultSettings }));
    render(<SettingsPage />);

    fireEvent.change(screen.getByLabelText('Service API URL'), {
      target: { value: 'https://new-api.example.com' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Save Settings' }));

    expect(saveMutate).toHaveBeenCalledWith({ url: 'https://new-api.example.com' });
  });

  it('shows "no changes" when submitting without modifications', () => {
    mockUseQuery.mockReturnValue(createMockQuery({ data: defaultSettings }));
    render(<SettingsPage />);

    fireEvent.click(screen.getByRole('button', { name: 'Save Settings' }));

    expect(screen.getByText('No changes to save.')).toBeInTheDocument();
    expect(saveMutate).not.toHaveBeenCalled();
  });

  it('tests connection and invokes the test mutation', () => {
    mockUseQuery.mockReturnValue(createMockQuery({ data: defaultSettings }));
    render(<SettingsPage />);

    fireEvent.click(screen.getByRole('button', { name: 'Test active target' }));

    expect(testMutate).toHaveBeenCalled();
  });

  it('renders read-only fields when source is constant', () => {
    mockUseQuery.mockReturnValue(
      createMockQuery({
        data: {
          ...defaultSettings,
          recognition_source_source: 'constant' as const,
          url_source: 'constant' as const,
          key_source: 'constant' as const,
        },
      }),
    );
    render(<SettingsPage />);

    expect(screen.getByLabelText('Service API URL')).toHaveAttribute('readOnly');
    expect(screen.getByLabelText('API Key')).toHaveAttribute('readOnly');
    expect(screen.getByRole('button', { name: 'Save Settings' })).toBeEnabled();
  });

  it('disables Save when every routing field is read-only', () => {
    mockUseQuery.mockReturnValue(
      createMockQuery({
        data: {
          ...defaultSettings,
          recognition_source_source: 'constant' as const,
          url_source: 'constant' as const,
          local_url_source: 'constant' as const,
          key_source: 'constant' as const,
        },
      }),
    );
    render(<SettingsPage />);

    expect(screen.getByRole('button', { name: 'Save Settings' })).toBeDisabled();
  });

  it('disables the Test active target button when service mode has no URL', () => {
    mockUseQuery.mockReturnValue(
      createMockQuery({
        data: {
          ...defaultSettings,
          url: '',
          effective_target_url: '',
          effective_target_mode: 'service',
        },
      }),
    );
    render(<SettingsPage />);

    expect(screen.getByRole('button', { name: 'Test active target' })).toBeDisabled();
  });

  it('enables the Test active target button when recognition source is local', () => {
    mockUseQuery.mockReturnValue(
      createMockQuery({
        data: {
          ...defaultSettings,
          recognition_source: 'local' as const,
          effective_target_url: 'http://localhost:8000',
          effective_target_mode: 'local' as const,
        },
      }),
    );
    render(<SettingsPage />);

    expect(screen.getByRole('button', { name: 'Test active target' })).toBeEnabled();
  });

  it('disables the Test active target button when routing edits are unsaved', () => {
    mockUseQuery.mockReturnValue(createMockQuery({ data: defaultSettings }));
    render(<SettingsPage />);

    fireEvent.click(screen.getByLabelText('Local'));

    expect(screen.getByRole('button', { name: 'Test active target' })).toBeDisabled();
    expect(screen.getByTestId('acx-effective-routing')).toHaveTextContent('Save settings before scanning or testing');
  });

  describe('probe outcome banners', () => {
    const driveOutcome = (response: TestConnectionResponse): void => {
      expect(capturedTestOptions?.onSuccess).toBeDefined();
      act(() => {
        capturedTestOptions!.onSuccess!(response);
      });
    };

    const renderWithLoadedSettings = (): void => {
      mockUseQuery.mockReturnValue(createMockQuery({ data: defaultSettings }));
      render(<SettingsPage />);
    };

    const bannerFor = (outcome: TestConnectionOutcomeValue): HTMLElement => {
      const banner = screen.getByTestId('acx-test-connection-banner');
      expect(banner.getAttribute('data-outcome')).toBe(outcome);
      return banner;
    };

    it('renders the connected banner', () => {
      renderWithLoadedSettings();
      driveOutcome({ outcome: 'connected', status_code: 200 });
      const banner = bannerFor('connected');
      expect(banner).toHaveTextContent('Connection successful.');
      expect(banner).toHaveTextContent('pool is healthy');
      expect(banner.className).toContain('notice-success');
      expect(banner.getAttribute('role')).toBe('status');
    });

    it('renders the not_configured banner', () => {
      renderWithLoadedSettings();
      driveOutcome({ outcome: 'not_configured' });
      const banner = bannerFor('not_configured');
      expect(banner).toHaveTextContent('No recognition URL configured.');
      expect(banner).toHaveTextContent('Set the API URL above before testing.');
      expect(banner.className).toContain('notice-warning');
    });

    it('renders the invalid_key banner', () => {
      renderWithLoadedSettings();
      driveOutcome({ outcome: 'invalid_key', status_code: 401 });
      const banner = bannerFor('invalid_key');
      expect(banner).toHaveTextContent('API key rejected.');
      expect(banner).toHaveTextContent('re-issue the key');
      expect(banner.className).toContain('notice-error');
      expect(banner.getAttribute('role')).toBe('alert');
    });

    it('renders the expired banner', () => {
      renderWithLoadedSettings();
      driveOutcome({ outcome: 'expired', status_code: 401, detail: 'api key expired' });
      const banner = bannerFor('expired');
      expect(banner).toHaveTextContent('API key expired.');
      expect(banner).toHaveTextContent('rotate the key');
    });

    it('renders the revoked banner', () => {
      renderWithLoadedSettings();
      driveOutcome({ outcome: 'revoked', status_code: 401, detail: 'api key revoked' });
      const banner = bannerFor('revoked');
      expect(banner).toHaveTextContent('API key revoked.');
      expect(banner).toHaveTextContent('Request a fresh key');
    });

    it('renders the tenant_mismatch banner', () => {
      renderWithLoadedSettings();
      driveOutcome({ outcome: 'tenant_mismatch', status_code: 403, detail: 'tenant mismatch' });
      const banner = bannerFor('tenant_mismatch');
      expect(banner).toHaveTextContent('Tenant mismatch.');
      expect(banner).toHaveTextContent('different site');
    });

    it('renders the rate_limited banner and interpolates retry_after_seconds', () => {
      renderWithLoadedSettings();
      driveOutcome({ outcome: 'rate_limited', status_code: 429, retry_after_seconds: 45 });
      const banner = bannerFor('rate_limited');
      expect(banner).toHaveTextContent('rate limiting this site');
      expect(banner).toHaveTextContent('Retry after 45 seconds.');
      expect(banner.className).toContain('notice-warning');
    });

    it('falls back to generic wording when retry_after_seconds is absent', () => {
      renderWithLoadedSettings();
      driveOutcome({ outcome: 'rate_limited', status_code: 429 });
      const banner = bannerFor('rate_limited');
      expect(banner).toHaveTextContent('Retry after a few seconds.');
    });

    it('renders the server_error banner', () => {
      renderWithLoadedSettings();
      driveOutcome({ outcome: 'server_error', status_code: 503 });
      const banner = bannerFor('server_error');
      expect(banner).toHaveTextContent('server error');
      expect(banner).toHaveTextContent('Try again in a moment');
    });

    it('renders the network_error banner', () => {
      renderWithLoadedSettings();
      driveOutcome({ outcome: 'network_error', detail: 'connection refused' });
      const banner = bannerFor('network_error');
      expect(banner).toHaveTextContent('Could not reach the recognition service.');
      expect(banner).toHaveTextContent('Verify the API URL');
    });

    it('renders the tls_error banner', () => {
      renderWithLoadedSettings();
      driveOutcome({ outcome: 'tls_error', detail: 'SSL certificate problem' });
      const banner = bannerFor('tls_error');
      expect(banner).toHaveTextContent('TLS handshake failed.');
      expect(banner).toHaveTextContent('trust chain');
    });

    it('renders a safe fallback banner when the outcome is not one of the known values', () => {
      renderWithLoadedSettings();
      act(() => {
        capturedTestOptions!.onSuccess!({
          outcome: 'something_new_from_the_future' as TestConnectionOutcomeValue,
          status_code: 418,
        });
      });
      const banner = screen.getByTestId('acx-test-connection-banner');
      expect(banner).toHaveTextContent('Unexpected response');
      expect(banner.className).toContain('notice-error');
      expect(banner.getAttribute('role')).toBe('alert');
    });

    it('falls back to network_error when the mutation itself rejects', () => {
      renderWithLoadedSettings();
      expect(capturedTestOptions?.onError).toBeDefined();
      act(() => {
        capturedTestOptions!.onError!(new Error('request aborted'));
      });
      const banner = bannerFor('network_error');
      expect(banner).toHaveTextContent('Could not reach the recognition service.');
    });

    it('uses local network_error copy when the mutation rejects in local mode', () => {
      mockUseQuery.mockReturnValue(
        createMockQuery({
          data: {
            ...defaultSettings,
            effective_target_mode: 'local',
            effective_target_url: 'http://localhost:8000',
            recognition_source: 'local',
          },
        }),
      );
      render(<SettingsPage />);
      act(() => {
        capturedTestOptions!.onError!(new Error('connection refused'));
      });
      const banner = bannerFor('network_error');
      expect(banner).toHaveTextContent('Could not reach the local recognition service.');
      expect(banner).toHaveTextContent('make serve');
    });
  });

  it('keeps Save enabled when only local_url is editable', () => {
    mockUseQuery.mockReturnValue(
      createMockQuery({
        data: {
          ...defaultSettings,
          recognition_source_source: 'constant',
          url_source: 'constant',
          key_source: 'constant',
          local_url_source: 'option',
        },
      }),
    );
    render(<SettingsPage />);

    expect(screen.getByRole('button', { name: 'Save Settings' })).toBeEnabled();
  });
});
