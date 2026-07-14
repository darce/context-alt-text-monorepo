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

const { mockUseQuery, mockUseMutation, mockInvalidateQueries, mockFetchQuery } = vi.hoisted(() => ({
  mockUseQuery: vi.fn<() => QueryHookResult>(),
  mockUseMutation: vi.fn<(options?: CapturedMutationOptions) => MutationHookResult>(),
  mockInvalidateQueries: vi.fn(),
  mockFetchQuery: vi.fn(),
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
    useQueryClient: () => ({ invalidateQueries: mockInvalidateQueries, fetchQuery: mockFetchQuery }),
    useQuery: mockUseQuery,
    useMutation: mockUseMutation,
  };
});

const defaultSettings: SettingsResponse = {
  url: 'https://api.example.com',
  url_source: 'option',
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
  description_budget: {
    max_attempts: -1,
    usage: {
      attempts: 0,
      successes: 0,
      failures: 0,
      cost_total: 0,
    },
    recent_errors: [],
  },
};

const saveMutate = vi.fn();
const testMutate = vi.fn();
let capturedSaveOptions: CapturedMutationOptions | undefined;
let capturedTestOptions: CapturedMutationOptions | undefined;

const installMutationMock = (): void => {
  let mutationCallIndex = 0;
  capturedSaveOptions = undefined;
  capturedTestOptions = undefined;
  mockUseMutation.mockImplementation((options) => {
    mutationCallIndex++;
    if (mutationCallIndex % 2 === 1) {
      capturedSaveOptions = options;
      return createMockMutation({ mutate: saveMutate });
    }
    capturedTestOptions = options;
    return createMockMutation({ mutate: testMutate });
  });
};

beforeEach(() => {
  vi.clearAllMocks();
  mockFetchQuery.mockResolvedValue(defaultSettings);
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
    expect(screen.getByTestId('acx-effective-routing')).toHaveTextContent('https://api.example.com');
    expect(screen.getByRole('button', { name: 'Save Settings' })).toBeEnabled();
    expect(screen.getAllByRole('button', { name: 'Check health' })).toHaveLength(1);
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

  it('renders description budget usage and saves the attempt limit', () => {
    mockUseQuery.mockReturnValue(
      createMockQuery({
        data: {
          ...defaultSettings,
          description_budget: {
            max_attempts: 25,
            usage: {
              attempts: 3,
              successes: 2,
              failures: 1,
              cost_total: 0.12,
            },
            recent_errors: [
              {
                media_id: 102,
                error_code: 'rate_limited',
                error_message: 'Rate limited',
                retryable: true,
                occurred_at: '2026-07-05T12:00:00Z',
              },
            ],
          },
        },
      }),
    );
    render(<SettingsPage />);

    expect(screen.getByText('Description budget')).toBeInTheDocument();
    expect(screen.getByLabelText('Maximum description attempts')).toHaveValue(25);
    expect(screen.getByText('Attempts')).toBeInTheDocument();
    expect(screen.getByText('3')).toBeInTheDocument();
    expect(screen.getByText('Failures')).toBeInTheDocument();
    expect(screen.getByText('rate_limited')).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText('Maximum description attempts'), {
      target: { value: '50' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Save Settings' }));

    expect(saveMutate).toHaveBeenCalledWith({ description_budget: { max_attempts: 50 } });
  });

  it('shows "no changes" when submitting without modifications', () => {
    mockUseQuery.mockReturnValue(createMockQuery({ data: defaultSettings }));
    render(<SettingsPage />);

    fireEvent.click(screen.getByRole('button', { name: 'Save Settings' }));

    expect(screen.getByText('No changes to save.')).toBeInTheDocument();
    expect(saveMutate).not.toHaveBeenCalled();
  });

  it('tests connection and invokes the test mutation for the service target', () => {
    mockUseQuery.mockReturnValue(createMockQuery({ data: defaultSettings }));
    render(<SettingsPage />);

    fireEvent.click(screen.getByRole('button', { name: 'Check health' }));

    expect(testMutate).toHaveBeenCalledWith({});
  });

  it('updates the service health chip after a successful probe', () => {
    mockUseQuery.mockReturnValue(createMockQuery({ data: defaultSettings }));
    render(<SettingsPage />);

    act(() => {
      capturedTestOptions?.onSuccess?.({
        outcome: 'connected',
        probe_mode: 'service_auth',
      });
    });

    expect(screen.getByTestId('acx-target-card-service')).toHaveTextContent('Reachable');
  });

  it('renders the tenant id and unpaired status when the tenant is not paired', () => {
    mockUseQuery.mockReturnValue(createMockQuery({ data: defaultSettings }));
    render(<SettingsPage />);

    expect(screen.getByTestId('acx-tenant-id')).toHaveTextContent('aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee');
    expect(screen.getByTestId('acx-tenant-pairing-status')).toHaveTextContent('Not paired yet');
  });

  it('renders the paired status when the tenant is paired', () => {
    mockUseQuery.mockReturnValue(createMockQuery({ data: { ...defaultSettings, tenant_paired: true } }));
    render(<SettingsPage />);

    expect(screen.getByTestId('acx-tenant-pairing-status')).toHaveTextContent(
      'Paired with the recognition service',
    );
  });

  it('refetches sync health after a successful save so the offline banner clears', async () => {
    mockUseQuery.mockReturnValue(createMockQuery({ data: defaultSettings }));
    render(<SettingsPage />);

    expect(capturedSaveOptions?.onSuccess).toBeDefined();
    // onSuccess is async at runtime but typed void; wrap so we await the real work.
    await act(async () => {
      await Promise.resolve(capturedSaveOptions!.onSuccess!(undefined));
    });

    expect(mockInvalidateQueries).toHaveBeenCalledWith({ queryKey: ['sync', 'health'] });
  });

  it('refetches sync health after a successful probe so the offline banner clears', () => {
    mockUseQuery.mockReturnValue(createMockQuery({ data: defaultSettings }));
    render(<SettingsPage />);

    act(() => {
      capturedTestOptions?.onSuccess?.({ outcome: 'connected', probe_mode: 'service_auth' });
    });

    expect(mockInvalidateQueries).toHaveBeenCalledWith({ queryKey: ['sync', 'health'] });
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
  });

  it('keeps Save enabled for description-budget edits even when routing fields are read-only', () => {
    // RECOG-1 B-02: the description budget is always editable, so read-only
    // routing fields (constant/filter-managed url + key) must not disable Save.
    mockUseQuery.mockReturnValue(
      createMockQuery({
        data: {
          ...defaultSettings,
          url_source: 'constant' as const,
          key_source: 'constant' as const,
        },
      }),
    );
    render(<SettingsPage />);

    expect(screen.getByRole('button', { name: 'Save Settings' })).toBeEnabled();
  });

  it('lets a fresh install enter the service URL when unconfigured', () => {
    // RECOG-1 B-01: with the service default and an empty URL, the Service API
    // URL input MUST be present and editable — the CTA alone would be a dead end.
    mockUseQuery.mockReturnValue(
      createMockQuery({
        data: {
          ...defaultSettings,
          url: '',
          effective_target_url: '',
          effective_target_mode: 'service',
          recognition_source: 'service',
        },
      }),
    );
    render(<SettingsPage />);

    expect(screen.getByRole('button', { name: 'Configure service URL' })).toBeInTheDocument();
    const urlInput = screen.getByLabelText('Service API URL');
    expect(urlInput).toBeInTheDocument();
    expect(urlInput).not.toHaveAttribute('readOnly');
    fireEvent.change(urlInput, { target: { value: 'https://api.altcontext.com' } });
    expect(urlInput).toHaveValue('https://api.altcontext.com');
  });

  it('disables Check health when routing edits are unsaved', () => {
    mockUseQuery.mockReturnValue(createMockQuery({ data: defaultSettings }));
    render(<SettingsPage />);

    fireEvent.change(screen.getByLabelText('Service API URL'), {
      target: { value: 'https://new-api.example.com' },
    });

    expect(screen.getByRole('button', { name: 'Check health' })).toBeDisabled();
    expect(screen.getByText(/Save settings before scanning or testing/)).toBeInTheDocument();
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

    it('renders a pairing warning when health succeeds but pairing fails', () => {
      renderWithLoadedSettings();
      driveOutcome({
        outcome: 'connected',
        status_code: 200,
        pairing_error: 'database unavailable',
      });
      const banner = bannerFor('connected');
      expect(banner).toHaveTextContent('tenant pairing failed');
      expect(banner).toHaveTextContent('database unavailable');
      expect(banner.className).toContain('notice-warning');
      expect(banner.getAttribute('role')).toBe('alert');
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

    it('renders a confirm-pairing action on the tenant_mismatch banner', () => {
      renderWithLoadedSettings();
      driveOutcome({ outcome: 'tenant_mismatch', status_code: 403, detail: 'tenant mismatch' });
      const banner = bannerFor('tenant_mismatch');
      expect(banner).toHaveTextContent('Tenant mismatch.');
      expect(screen.getByTestId('acx-confirm-tenant-pairing')).toBeInTheDocument();
    });

    it('sends confirm_tenant_pairing when the mismatch adopt button is clicked', () => {
      renderWithLoadedSettings();
      driveOutcome({ outcome: 'tenant_mismatch', status_code: 403, detail: 'tenant mismatch' });

      fireEvent.click(screen.getByTestId('acx-confirm-tenant-pairing'));

      expect(testMutate).toHaveBeenCalledWith({ confirm_tenant_pairing: true });
    });

    it('renders the tenant_pairing_conflict banner with tenant ids and confirm control', () => {
      renderWithLoadedSettings();
      driveOutcome({
        outcome: 'tenant_pairing_conflict',
        persisted_tenant_id: 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee',
        key_tenant_id: 'ffffffff-ffff-4fff-8fff-ffffffffffff',
      });
      const banner = bannerFor('tenant_pairing_conflict');
      expect(banner).toHaveTextContent('Tenant identity conflict.');
      expect(banner).toHaveTextContent('aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee');
      expect(banner).toHaveTextContent('ffffffff-ffff-4fff-8fff-ffffffffffff');
      expect(screen.getByTestId('acx-confirm-tenant-pairing')).toBeInTheDocument();
    });

    it('sends confirm_tenant_pairing when adopt button is clicked', () => {
      renderWithLoadedSettings();
      driveOutcome({
        outcome: 'tenant_pairing_conflict',
        persisted_tenant_id: 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee',
        key_tenant_id: 'ffffffff-ffff-4fff-8fff-ffffffffffff',
      });

      fireEvent.click(screen.getByTestId('acx-confirm-tenant-pairing'));

      expect(testMutate).toHaveBeenCalledWith({ confirm_tenant_pairing: true });
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
  });
});
