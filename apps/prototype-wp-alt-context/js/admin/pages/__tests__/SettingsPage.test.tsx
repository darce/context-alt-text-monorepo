import React from 'react';
import { act, render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

import { SettingsPage } from '../SettingsPage';
import {
  UrlRejectionReason,
  type SettingsResponse,
  type TestConnectionOutcomeValue,
  type TestConnectionResponse,
} from '../../api/settingsApi';
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
    ajaxUrl: '/wp-admin/admin-ajax.php',
    endpoints: { settings: '/acx/v1/settings', settingsTest: '/acx/v1/settings/test' },
  }),
  resetConfigCache: mockResetConfigCache,
}));

// Recovery affordances must stay enabled while offline (plan §3, RES-15). Forcing the shared
// offline signal to true guards against a future change gating test-connection on the breaker.
vi.mock('../../hooks/useSyncOffline', () => ({
  useSyncOffline: () => true,
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

  it('offers retry and a labelled Dashboard escape when Recognition API settings fail to load', () => {
    const refetch = vi.fn();
    mockUseQuery.mockReturnValue(createMockQuery({ isError: true, error: new Error('fail'), refetch }));
    render(<SettingsPage />);

    expect(screen.getByRole('alert')).toHaveTextContent(
      'Recognition API settings could not be loaded. Retry loading them or return to Dashboard.',
    );
    fireEvent.click(screen.getByRole('button', { name: 'Retry loading settings' }));
    expect(refetch).toHaveBeenCalledTimes(1);
    expect(screen.getByRole('link', { name: 'Return to Dashboard' })).toHaveAttribute('href', '#/dashboard');
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

  it('keeps Check health enabled while the sync breaker reports offline (recovery affordance)', () => {
    // useSyncOffline is module-mocked to true for this whole file — the probe must stay usable
    // so the operator can heal the breaker (plan §3 trap-the-operator guard).
    mockUseQuery.mockReturnValue(createMockQuery({ data: defaultSettings }));
    render(<SettingsPage />);

    const probeButton = screen.getByRole('button', { name: 'Check health' });
    expect(probeButton).toBeEnabled();
    fireEvent.click(probeButton);
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

    expect(screen.getByTestId('acx-tenant-pairing-status')).toHaveTextContent('Paired with the recognition service');
  });

  it('refetches sync health after a successful save so the offline banner clears', async () => {
    mockUseQuery.mockReturnValue(createMockQuery({ data: defaultSettings }));
    render(<SettingsPage />);

    expect(capturedSaveOptions?.onSuccess).toBeDefined();
    // onSuccess is async at runtime but typed void; wrap so we await the real work.
    // R23-BR-14: pass an ok envelope so the success path runs (not partial/error).
    await act(async () => {
      await Promise.resolve(capturedSaveOptions!.onSuccess!({ saved: ['url'], result: 'ok' }));
    });

    expect(mockInvalidateQueries).toHaveBeenCalledWith({ queryKey: ['sync', 'health'] });
  });

  it('shows Settings saved only when result is ok (R23-BR-14)', async () => {
    mockUseQuery.mockReturnValue(createMockQuery({ data: defaultSettings }));
    render(<SettingsPage />);

    await act(async () => {
      await Promise.resolve(capturedSaveOptions!.onSuccess!({ saved: ['url', 'api_key'], result: 'ok' }));
    });

    const banner = screen.getByTestId('acx-settings-save-message');
    expect(banner.textContent).toBe('Settings saved.');
    expect(banner.getAttribute('role')).toBe('status');
  });

  it('does not show Settings saved on partial storage failure (R23-BR-14)', async () => {
    mockUseQuery.mockReturnValue(createMockQuery({ data: defaultSettings }));
    render(<SettingsPage />);

    await act(async () => {
      await Promise.resolve(
        capturedSaveOptions!.onSuccess!({
          saved: ['url'],
          failed: ['api_key'],
          result: 'partial',
        }),
      );
    });

    const banner = screen.getByTestId('acx-settings-save-message');
    expect(banner.textContent).toContain('Could not save settings.');
    expect(banner.textContent).toContain('api_key');
    expect(banner.getAttribute('role')).toBe('alert');
    // Must not paint the success copy on a non-ok result.
    expect(banner.textContent).not.toContain('Settings saved.');
  });

  it('does not show Settings saved on total storage failure (R23-BR-14)', async () => {
    mockUseQuery.mockReturnValue(createMockQuery({ data: defaultSettings }));
    render(<SettingsPage />);

    await act(async () => {
      await Promise.resolve(
        capturedSaveOptions!.onSuccess!({
          saved: [],
          failed: ['url', 'api_key'],
          result: 'error',
        }),
      );
    });

    const banner = screen.getByTestId('acx-settings-save-message');
    expect(banner.textContent).toContain('Could not save settings.');
    expect(banner.getAttribute('role')).toBe('alert');
    expect(banner.textContent).not.toContain('Settings saved.');
  });

  it('surfaces the server invalid_url message when save is rejected (BR-136)', () => {
    // After the loopback-only HTTP rule, non-loopback http:// URLs return 400
    // invalid_url with an actionable message — the operator must see that text,
    // not a generic "Failed to save settings." ([RLSE-05]).
    const loopbackRuleMessage =
      'The recognition API URL must be HTTPS (HTTP is allowed only for loopback development hosts).';
    mockUseQuery.mockReturnValue(createMockQuery({ data: defaultSettings }));
    render(<SettingsPage />);

    expect(capturedSaveOptions?.onError).toBeDefined();
    act(() => {
      capturedSaveOptions!.onError!(
        new Error(
          `Request to /acx/v1/settings failed (400): {"code":"invalid_url","message":"${loopbackRuleMessage}","data":{"status":400}}`,
        ),
      );
    });

    const banner = screen.getByTestId('acx-settings-save-message');
    // BR-150: exact text — a regression that wraps the resolved message in raw
    // transport text must go red. toHaveTextContent is a substring match.
    expect(banner.textContent).toBe(loopbackRuleMessage);
    expect(banner.getAttribute('role')).toBe('alert');
  });

  it('falls back to the generic save failure when the rejection is unstructured', () => {
    mockUseQuery.mockReturnValue(createMockQuery({ data: defaultSettings }));
    render(<SettingsPage />);

    expect(capturedSaveOptions?.onError).toBeDefined();
    act(() => {
      capturedSaveOptions!.onError!(new Error('network down'));
    });

    const banner = screen.getByTestId('acx-settings-save-message');
    // BR-150: exact text for the fallback path too.
    expect(banner.textContent).toBe('Failed to save settings.');
    expect(banner.getAttribute('role')).toBe('alert');
  });

  it('refetches sync health after a successful probe so the offline banner clears', () => {
    mockUseQuery.mockReturnValue(createMockQuery({ data: defaultSettings }));
    render(<SettingsPage />);

    act(() => {
      capturedTestOptions?.onSuccess?.({ outcome: 'connected', probe_mode: 'service_auth' });
    });

    expect(mockInvalidateQueries).toHaveBeenCalledWith({ queryKey: ['sync', 'health'] });
  });

  it('does not refetch sync health when a probe fails', () => {
    // A failed probe must not clear the offline banner: sync.health stays as-is.
    mockUseQuery.mockReturnValue(createMockQuery({ data: defaultSettings }));
    render(<SettingsPage />);

    act(() => {
      capturedTestOptions?.onError?.(new Error('boom'));
    });

    expect(mockInvalidateQueries).not.toHaveBeenCalledWith({ queryKey: ['sync', 'health'] });
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
    // Genuinely unconfigured still says "not configured".
    expect(screen.getByTestId('acx-effective-routing')).toHaveTextContent('not configured');
  });

  it('renders rejection reason instead of not configured when a URL was rejected (BR-138)', () => {
    mockUseQuery.mockReturnValue(
      createMockQuery({
        data: {
          ...defaultSettings,
          url: '',
          url_source: 'default',
          url_rejection_reason: UrlRejectionReason.NON_LOOPBACK_HTTP,
          url_rejection_source: 'option',
          url_rejection_value: 'http://10.0.0.5:8000',
          effective_target_url: '',
          effective_target_mode: 'service',
          recognition_source: 'service',
        },
      }),
    );
    render(<SettingsPage />);

    const routing = screen.getByTestId('acx-effective-routing');
    const rejection = screen.getByTestId('acx-url-rejection');
    expect(rejection).toHaveTextContent(
      'Rejected http://10.0.0.5:8000 (Saved in database): HTTP is only allowed for loopback development hosts (localhost, 127.0.0.1, ::1)',
    );
    expect(routing).not.toHaveTextContent('not configured');
    // Status is text, not decoration alone (A11Y-21).
    expect(routing).toHaveAttribute('role', 'status');
  });

  // R16-BR-09: rejection sentence must appear exactly once (live region only).
  it('announces the rejection sentence exactly once in the accessibility tree (R16-BR-09)', () => {
    mockUseQuery.mockReturnValue(
      createMockQuery({
        data: {
          ...defaultSettings,
          url: '',
          url_source: 'default',
          url_rejection_reason: UrlRejectionReason.NON_LOOPBACK_HTTP,
          url_rejection_source: 'option',
          url_rejection_value: 'http://10.0.0.5:8000',
          effective_target_url: '',
          effective_target_mode: 'service',
          recognition_source: 'service',
        },
      }),
    );
    render(<SettingsPage />);

    const rejectionSentence =
      'Rejected http://10.0.0.5:8000 (Saved in database): HTTP is only allowed for loopback development hosts (localhost, 127.0.0.1, ::1)';
    // Count matched nodes — getByText throws on multiples for the wrong reason and
    // would pass for the wrong reason if the suite only asserted presence.
    expect(screen.getAllByText(rejectionSentence)).toHaveLength(1);
    // Card notice is a non-duplicating next-step cue, not a second copy of the sentence.
    expect(screen.getByTestId('acx-url-rejection-notice')).toHaveTextContent(
      'The configured service URL was rejected. Enter a valid HTTPS URL below to restore recognition routing.',
    );
    expect(screen.getByTestId('acx-url-rejection-notice')).not.toHaveTextContent(rejectionSentence);
    // Colour+text status half still lives in the live-region span ([sr-004]).
    expect(screen.getByTestId('acx-url-rejection')).toHaveTextContent(rejectionSentence);
  });

  // A11Y-21: live region must stay mounted in CONFIGURED as well (rejected / hatch /
  // unconfigured are already pinned above).
  it('mounts the effective-target live region when configured (A11Y-21)', () => {
    mockUseQuery.mockReturnValue(createMockQuery({ data: defaultSettings }));
    render(<SettingsPage />);

    const routing = screen.getByTestId('acx-effective-routing');
    expect(routing).toHaveAttribute('role', 'status');
    expect(routing).toHaveAttribute('aria-live', 'polite');
    expect(routing).toHaveTextContent('https://api.example.com');
    expect(screen.queryByTestId('acx-url-rejection')).not.toBeInTheDocument();
    expect(screen.queryByTestId('acx-url-rejection-notice')).not.toBeInTheDocument();
  });

  it('renders constant-tier rejection with exact source wording (BR-138)', () => {
    mockUseQuery.mockReturnValue(
      createMockQuery({
        data: {
          ...defaultSettings,
          url: '',
          url_source: 'default',
          url_rejection_reason: UrlRejectionReason.NON_LOOPBACK_HTTP,
          url_rejection_source: 'constant',
          url_rejection_value: 'http://host.docker.internal:8000',
          effective_target_url: '',
        },
      }),
    );
    render(<SettingsPage />);

    expect(screen.getByTestId('acx-url-rejection')).toHaveTextContent(
      'Rejected http://host.docker.internal:8000 (Set via wp-config.php constant): HTTP is only allowed for loopback development hosts (localhost, 127.0.0.1, ::1)',
    );
    expect(screen.getByTestId('acx-effective-routing')).not.toHaveTextContent('not configured');
  });

  // R19-BR-04 / R19-BR-05: rejected URL must not masquerade as "not configured".
  it('hides the empty-state CTA and reports rejected tier when a URL was rejected (R19-BR-04)', () => {
    mockUseQuery.mockReturnValue(
      createMockQuery({
        data: {
          ...defaultSettings,
          url: '',
          url_source: 'default',
          url_rejection_reason: UrlRejectionReason.NON_LOOPBACK_HTTP,
          url_rejection_source: 'option',
          url_rejection_value: 'http://10.0.0.5:8000',
          effective_target_url: '',
          effective_target_mode: 'service',
          recognition_source: 'service',
        },
      }),
    );
    render(<SettingsPage />);

    expect(screen.queryByRole('button', { name: 'Configure service URL' })).not.toBeInTheDocument();
    expect(screen.queryByText(/No service URL configured yet/)).not.toBeInTheDocument();
    expect(screen.getByTestId('acx-url-rejection')).toHaveTextContent('http://10.0.0.5:8000');
    expect(screen.getByTestId('acx-url-rejection')).toHaveTextContent(
      'HTTP is only allowed for loopback development hosts',
    );
    // Source chip reports the rejected tier, not "Not configured".
    expect(screen.getByTestId('acx-url-source')).toHaveTextContent('Saved in database');
    expect(screen.getByTestId('acx-url-source')).not.toHaveTextContent('Not configured');
    // Live region always mounted (A11Y-21).
    const routing = screen.getByTestId('acx-effective-routing');
    expect(routing).toHaveAttribute('role', 'status');
    expect(routing).toHaveAttribute('aria-live', 'polite');
    // Nothing to probe — Check health stays disabled.
    expect(screen.getByRole('button', { name: 'Check health' })).toBeDisabled();
  });

  it('shows effective target and enables Check health when hatch + rejection coexist (R19-BR-05)', () => {
    mockUseQuery.mockReturnValue(
      createMockQuery({
        data: {
          ...defaultSettings,
          url: '',
          url_source: 'default',
          url_rejection_reason: UrlRejectionReason.NON_LOOPBACK_HTTP,
          url_rejection_source: 'option',
          url_rejection_value: 'http://10.0.0.5:8000',
          effective_target_url: 'http://localhost:8000',
          effective_target_mode: 'local',
          recognition_source: 'local',
          recognition_source_source: 'constant',
        },
      }),
    );
    render(<SettingsPage />);

    const routing = screen.getByTestId('acx-effective-routing');
    expect(routing).toHaveTextContent('http://localhost:8000');
    expect(screen.getByTestId('acx-url-rejection')).toHaveTextContent(
      'Rejected http://10.0.0.5:8000 (Saved in database)',
    );
    // Both present — rejection is additional info, not a replacement.
    expect(routing.querySelector('code')).toHaveTextContent('http://localhost:8000');
    expect(screen.getByRole('button', { name: 'Check health' })).toBeEnabled();
    expect(screen.queryByRole('button', { name: 'Configure service URL' })).not.toBeInTheDocument();
    // Live region always mounted (A11Y-21).
    expect(routing).toHaveAttribute('role', 'status');
    expect(routing).toHaveAttribute('aria-live', 'polite');
  });

  it('shows empty CTA and disables Check health when genuinely unconfigured (R19-BR-04 regression)', () => {
    mockUseQuery.mockReturnValue(
      createMockQuery({
        data: {
          ...defaultSettings,
          url: '',
          url_source: 'default',
          url_rejection_reason: null,
          url_rejection_source: null,
          url_rejection_value: null,
          effective_target_url: '',
          effective_target_mode: 'service',
          recognition_source: 'service',
        },
      }),
    );
    render(<SettingsPage />);

    expect(screen.getByRole('button', { name: 'Configure service URL' })).toBeInTheDocument();
    expect(screen.getByText(/No service URL configured yet/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Check health' })).toBeDisabled();
    expect(screen.queryByTestId('acx-url-rejection')).not.toBeInTheDocument();
    // Live region always mounted even when target is empty (A11Y-21).
    const routing = screen.getByTestId('acx-effective-routing');
    expect(routing).toHaveAttribute('role', 'status');
    expect(routing).toHaveAttribute('aria-live', 'polite');
    expect(routing).toHaveTextContent('not configured');
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
