import React from 'react';
import { act, render, screen, fireEvent } from '@testing-library/react';
import { QueryClient } from '@tanstack/react-query';
import { MemoryRouter, RouterProvider, createMemoryRouter } from 'react-router-dom';
import { describe, it, expect, vi, beforeEach } from 'vitest';

import { SettingsPage } from '../SettingsPage';
import {
  CONTEXT_CATEGORIES,
  UrlRejectionReason,
  fetchSettings,
  type SettingsResponse,
  type TestConnectionOutcomeValue,
  type TestConnectionResponse,
} from '../../api/settingsApi';
import { queryKeys } from '../../api/queryKeys';
import {
  useApplyRetentionPreset,
  useAuditEvents,
  useDownloadExportJobData,
  useExportJobStatus,
  useExportTenantData,
  useImportTenantData,
  usePurgeTenantData,
  useRetentionStatus,
  useUpdateRetentionPolicy,
} from '../../hooks/useRetentionStatus';
import { createMockMutation, createMockQuery } from '../../test-utils/mockHooks';

type QueryHookResult = ReturnType<typeof createMockQuery<SettingsResponse>>;
type MutationHookResult = ReturnType<typeof createMockMutation>;

interface CapturedMutationOptions {
  onSuccess?: (data: unknown, variables?: unknown) => void;
  onError?: (err: unknown, variables?: unknown) => void;
}

const {
  mockUseQuery,
  mockUseMutation,
  mockInvalidateQueries,
  mockFetchQuery,
  mockToDashboard,
  mockQueryClientRef,
  gpuStatusQueryResult,
} = vi.hoisted(() => ({
  mockUseQuery: vi.fn<() => QueryHookResult>(),
  mockUseMutation: vi.fn<(options?: CapturedMutationOptions) => MutationHookResult>(),
  mockInvalidateQueries: vi.fn(),
  mockFetchQuery: vi.fn(),
  mockToDashboard: vi.fn(() => '#/owned-dashboard-route'),
  mockQueryClientRef: { current: undefined as unknown },
  // SettingsPage hosts GpuControlCard, whose own useQuery/useMutation would
  // otherwise be answered by the blanket settings mocks below — the card would
  // read gpu_state off a SettingsResponse and shift every captured mutation
  // index. The card keeps its own coverage in settings/__tests__; here it just
  // needs a contract-shaped hook result.
  gpuStatusQueryResult: {
    data: {
      gpu_state: {
        state: 'stopped',
        instance_id: null,
        written_at: 0,
        reason: null,
        since: null,
        intent: 'auto',
        intent_expires_at: null,
        intent_status: 'none',
        honoured_nonce: null,
        lease_expires_at: null,
        instance_running_since: null,
        last_transition_reason: 'idle',
      },
      snapshot_age_seconds: 3,
      snapshot_fresh: true,
      intent: null,
      load: { has_work: false, written_at: 0, fresh: true },
      server_time: '2026-01-01T00:00:00Z',
    },
    isLoading: false,
    isError: false,
    isSuccess: true,
    isPending: false,
    isFetching: false,
    status: 'success',
    error: null,
    refetch: vi.fn(),
  },
}));

vi.mock('../settings/useGpuControl', () => ({
  useGpuControl: () => ({
    ...gpuStatusQueryResult,
    canStart: true,
    canStop: false,
    stopBlockedReason: null,
    canReturnToAuto: false,
    requestIntent: vi.fn(),
    requestIntentAsync: vi.fn(),
    isIntentPending: false,
    intentError: null,
  }),
  getGpuControlPollInterval: () => 15_000,
  GPU_STATUS_POLL_INTERVAL_MS: 15_000,
  GPU_WARMUP_POLL_INTERVAL_MS: 5_000,
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

vi.mock('../../navigation/appLinks', () => ({
  toDashboard: mockToDashboard,
  toDescriptionHistory: () => '#/description-history',
}));

// Recovery affordances must stay enabled while offline (plan §3, RES-15). Forcing the shared
// offline signal to true guards against a future change gating test-connection on the breaker.
vi.mock('../../hooks/useSyncOffline', () => ({
  useSyncOffline: () => true,
}));

vi.mock('../../hooks/useRetentionStatus', () => ({
  useRetentionStatus: vi.fn(),
  useUpdateRetentionPolicy: vi.fn(),
  useExportTenantData: vi.fn(),
  useExportJobStatus: vi.fn(),
  useDownloadExportJobData: vi.fn(),
  usePurgeTenantData: vi.fn(),
  useImportTenantData: vi.fn(),
  useAuditEvents: vi.fn(),
  useApplyRetentionPreset: vi.fn(),
}));

vi.mock('../../context/ToastContext', () => ({
  useToast: () => ({
    success: vi.fn(),
    error: vi.fn(),
  }),
}));

const SettingsPageWithRouter = ({ route = '/settings' }: { route?: string }): React.JSX.Element => (
  <MemoryRouter initialEntries={[route]}>
    <SettingsPage />
  </MemoryRouter>
);

vi.mock('@tanstack/react-query', async () => {
  const actual = await vi.importActual<typeof import('@tanstack/react-query')>('@tanstack/react-query');
  return {
    ...actual,
    useQueryClient: () => mockQueryClientRef.current ?? ({
      invalidateQueries: mockInvalidateQueries,
      fetchQuery: mockFetchQuery,
    }),
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
  recognition_enabled: true,
  allow_person_names: true,
  allow_person_names_error: null,
  context_categories: null,
  context_categories_error: null,
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
let testMutationPending = false;
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
    return createMockMutation({ mutate: testMutate, isPending: testMutationPending });
  });
};

beforeEach(() => {
  vi.clearAllMocks();
  mockQueryClientRef.current = undefined;
  testMutationPending = false;
  mockFetchQuery.mockResolvedValue(defaultSettings);
  installMutationMock();

  vi.mocked(useRetentionStatus).mockReturnValue(
    createMockQuery({
      data: {
        available: true,
        policy: {
          retention_mode: 'dispose_after_ack',
          last_export_at: '2026-03-10T10:00:00Z',
          last_purge_at: null,
          retention_updated_at: '2026-03-09T12:00:00Z',
        },
        recent_audit_events: [],
      },
    }),
  );
  vi.mocked(useUpdateRetentionPolicy).mockReturnValue(createMockMutation());
  vi.mocked(useExportTenantData).mockReturnValue(createMockMutation());
  vi.mocked(useExportJobStatus).mockReturnValue(createMockQuery());
  vi.mocked(useDownloadExportJobData).mockReturnValue(createMockMutation());
  vi.mocked(usePurgeTenantData).mockReturnValue(createMockMutation());
  vi.mocked(useImportTenantData).mockReturnValue(createMockMutation());
  vi.mocked(useAuditEvents).mockReturnValue(
    createMockQuery({ data: { items: [], total: 0, limit: 20, offset: 0 } }),
  );
  vi.mocked(useApplyRetentionPreset).mockReturnValue(createMockMutation());
});

const startTestConnection = (): Record<string, unknown> => {
  const previousCallCount = testMutate.mock.calls.length;
  fireEvent.click(screen.getByRole('button', { name: 'Check health' }));
  const requestVariables = testMutate.mock.calls[previousCallCount]?.[0] as
    | Record<string, unknown>
    | undefined;
  expect(requestVariables).toBeDefined();
  return requestVariables!;
};

describe('SettingsPage', () => {
  it('shows loading state initially', () => {
    mockUseQuery.mockReturnValue(createMockQuery({ status: 'pending' }));
    render(<SettingsPageWithRouter />);
    expect(screen.getByText('Loading settings…')).toBeInTheDocument();
  });

  it('populates the same initially empty error region when loading fails [DUX-L4-RV-01]', () => {
    mockUseQuery.mockReturnValue(createMockQuery({ status: 'pending' }));
    const { rerender } = render(<SettingsPageWithRouter />);

    const errorRegion = screen.getByRole('alert');
    expect(errorRegion).toBeEmptyDOMElement();

    mockUseQuery.mockReturnValue(
      createMockQuery({ isError: true, error: new Error('fail') }),
    );
    rerender(<SettingsPageWithRouter />);

    expect(screen.getByRole('alert')).toBe(errorRegion);
    expect(errorRegion).toHaveTextContent('Failed to load settings.');
  });

  it('shows the cold-load error screen with retry and the owned Dashboard route [DUX-L4-RV-02, DUX-L4-RV-03]', () => {
    const refetch = vi.fn();
    mockUseQuery.mockReturnValue(
      createMockQuery({ isError: true, error: new Error('fail'), refetch }),
    );
    render(<SettingsPageWithRouter />);

    expect(screen.getByRole('alert')).toHaveTextContent('Failed to load settings.');

    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    expect(refetch).toHaveBeenCalledTimes(1);

    expect(screen.getByRole('link', { name: 'Back to Dashboard' })).toHaveAttribute(
      'href',
      '#/owned-dashboard-route',
    );
    expect(mockToDashboard).toHaveBeenCalled();
    expect(screen.queryByLabelText('Service API URL')).not.toBeInTheDocument();
  });

  it('keeps an edited form mounted and shows an inline notice after a refetch error [DUX-L4-RV-02]', () => {
    mockUseQuery.mockReturnValue(createMockQuery({ data: defaultSettings }));
    const { rerender } = render(<SettingsPageWithRouter />);

    fireEvent.change(screen.getByLabelText('Service API URL'), {
      target: { value: 'https://draft.example.com' },
    });

    mockUseQuery.mockReturnValue(
      createMockQuery({
        data: defaultSettings,
        isError: true,
        error: new Error('refetch failed'),
      }),
    );
    rerender(<SettingsPageWithRouter />);

    expect(screen.getByLabelText('Service API URL')).toHaveValue('https://draft.example.com');
    expect(screen.getByTestId('acx-settings-query-error')).toHaveTextContent('Failed to refresh settings.');
    expect(screen.queryByRole('link', { name: 'Back to Dashboard' })).not.toBeInTheDocument();
  });

  it('renders the settings form with loaded data', () => {
    mockUseQuery.mockReturnValue(createMockQuery({ data: defaultSettings }));
    render(<SettingsPageWithRouter />);

    expect(screen.getByLabelText('Service API URL')).toHaveValue('https://api.example.com');
    expect(screen.getByTestId('acx-effective-routing')).toHaveTextContent('https://api.example.com');
    expect(screen.getByRole('button', { name: 'Save Settings' })).toBeEnabled();
    expect(screen.getAllByRole('button', { name: 'Check health' })).toHaveLength(1);
  });

  it('saves settings when the form is submitted with changes', () => {
    mockUseQuery.mockReturnValue(createMockQuery({ data: defaultSettings }));
    render(<SettingsPageWithRouter />);

    fireEvent.change(screen.getByLabelText('Service API URL'), {
      target: { value: 'https://new-api.example.com' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Save Settings' }));

    expect(saveMutate).toHaveBeenCalledWith({ url: 'https://new-api.example.com' });
  });

  it('saves the naming agreement toggle through the page payload (H-02)', () => {
    mockUseQuery.mockReturnValue(createMockQuery({ data: defaultSettings }));
    render(<SettingsPageWithRouter />);

    fireEvent.click(screen.getByRole('checkbox', { name: 'Include named people in descriptions' }));
    fireEvent.click(screen.getByRole('button', { name: 'Save Settings' }));

    expect(saveMutate).toHaveBeenCalledWith({ allow_person_names: false });
  });

  it('saves the remaining context categories in canonical order when one is unchecked', () => {
    mockUseQuery.mockReturnValue(createMockQuery({ data: defaultSettings }));
    render(<SettingsPageWithRouter />);

    fireEvent.click(screen.getByRole('checkbox', { name: 'Attachment details' }));
    fireEvent.click(screen.getByRole('button', { name: 'Save Settings' }));

    expect(saveMutate).toHaveBeenCalledWith({
      context_categories: CONTEXT_CATEGORIES.slice(1),
    });
  });

  it('does not send context_categories when its selection is unchanged', () => {
    mockUseQuery.mockReturnValue(createMockQuery({ data: defaultSettings }));
    render(<SettingsPageWithRouter />);

    fireEvent.change(screen.getByLabelText('Service API URL'), {
      target: { value: 'https://new-api.example.com' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Save Settings' }));

    expect(saveMutate).toHaveBeenCalledWith({ url: 'https://new-api.example.com' });
    expect(saveMutate.mock.calls[0]?.[0]).not.toHaveProperty('context_categories');
  });

  it('renders the people recognition checkbox checked when GET recognition_enabled is true', () => {
    mockUseQuery.mockReturnValue(createMockQuery({ data: defaultSettings }));
    render(<SettingsPageWithRouter />);

    expect(screen.getByRole('heading', { name: 'People & recognition' })).toBeInTheDocument();
    expect(screen.getByLabelText('Identify people in photos')).toBeChecked();
    expect(
      screen.getByText(
        'Uses facial recognition to name people in descriptions. When off, Describe writes alt text without identities. Applies to every run.',
      ),
    ).toBeInTheDocument();
  });

  it('renders the people recognition checkbox unchecked when GET recognition_enabled is false', () => {
    mockUseQuery.mockReturnValue(
      createMockQuery({ data: { ...defaultSettings, recognition_enabled: false } }),
    );
    render(<SettingsPageWithRouter />);

    expect(screen.getByLabelText('Identify people in photos')).not.toBeChecked();
  });

  it('associates the people recognition hint with the checkbox (A11Y-57)', () => {
    mockUseQuery.mockReturnValue(createMockQuery({ data: defaultSettings }));
    render(<SettingsPageWithRouter />);

    expect(screen.getByLabelText('Identify people in photos')).toHaveAccessibleDescription(
      /facial recognition/,
    );
  });

  it('posts recognition_enabled false when the checkbox is unchecked then saved', () => {
    mockUseQuery.mockReturnValue(createMockQuery({ data: defaultSettings }));
    render(<SettingsPageWithRouter />);

    fireEvent.click(screen.getByLabelText('Identify people in photos'));
    fireEvent.click(screen.getByRole('button', { name: 'Save Settings' }));

    expect(saveMutate).toHaveBeenCalledWith({ recognition_enabled: false });
  });

  it('posts recognition_enabled true when GET is false and the checkbox is checked then saved', () => {
    mockUseQuery.mockReturnValue(
      createMockQuery({ data: { ...defaultSettings, recognition_enabled: false } }),
    );
    render(<SettingsPageWithRouter />);

    fireEvent.click(screen.getByLabelText('Identify people in photos'));
    fireEvent.click(screen.getByRole('button', { name: 'Save Settings' }));

    expect(saveMutate).toHaveBeenCalledWith({ recognition_enabled: true });
  });

  it('does not post recognition_enabled when the checkbox is untouched', () => {
    mockUseQuery.mockReturnValue(createMockQuery({ data: defaultSettings }));
    render(<SettingsPageWithRouter />);

    fireEvent.change(screen.getByLabelText('Service API URL'), {
      target: { value: 'https://new-api.example.com' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Save Settings' }));

    expect(saveMutate).toHaveBeenCalledWith({ url: 'https://new-api.example.com' });
    expect(saveMutate.mock.calls[0]?.[0]).not.toHaveProperty('recognition_enabled');
  });

  it('renders the Data & retention section and its purge control after People & recognition', () => {
    mockUseQuery.mockReturnValue(createMockQuery({ data: defaultSettings }));
    render(<SettingsPageWithRouter />);

    const peopleHeading = screen.getByRole('heading', { name: 'People & recognition' });
    const retentionHeading = screen.getByRole('heading', { name: 'Data & retention' });
    expect(peopleHeading.compareDocumentPosition(retentionHeading) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Purge data' })).toBeInTheDocument();
    expect(document.getElementById('acx-settings-section-retention')).not.toBeNull();
  });

  it('renders exactly one h1 whose text is Settings in the composed Settings tree', () => {
    mockUseQuery.mockReturnValue(createMockQuery({ data: defaultSettings }));
    render(<SettingsPageWithRouter />);

    const pageHeadings = screen.getAllByRole('heading', { level: 1 });
    expect(pageHeadings).toHaveLength(1);
    expect(pageHeadings[0]).toHaveTextContent('Settings');
  });

  it('does not submit settings when Enter is pressed on a retention radio', () => {
    mockUseQuery.mockReturnValue(createMockQuery({ data: defaultSettings }));
    render(<SettingsPageWithRouter />);

    const radio = screen.getByRole('radio', { name: /Purge on demand/ });
    const saveSettings = screen.getByRole('button', { name: 'Save Settings' });
    const settingsForm = saveSettings.closest('form');
    expect(settingsForm).not.toBeNull();
    expect(settingsForm?.contains(radio)).toBe(false);

    fireEvent.keyDown(radio, { key: 'Enter', code: 'Enter' });
    const radioForm = radio.closest('form');
    if (radioForm) {
      fireEvent.submit(radioForm);
    }

    expect(saveMutate).not.toHaveBeenCalled();
    expect(screen.queryByText('No changes to save.')).not.toBeInTheDocument();
  });

  it('never includes retention_mode in the settings save payload', () => {
    mockUseQuery.mockReturnValue(createMockQuery({ data: defaultSettings }));
    render(<SettingsPageWithRouter />);

    fireEvent.click(screen.getByRole('radio', { name: /Purge on demand/ }));
    fireEvent.change(screen.getByLabelText('Service API URL'), {
      target: { value: 'https://new-api.example.com' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Save Settings' }));

    expect(saveMutate).toHaveBeenCalledTimes(1);
    const body = saveMutate.mock.calls[0]?.[0] as Record<string, unknown>;
    expect(body).toEqual({ url: 'https://new-api.example.com' });
    expect(body).not.toHaveProperty('retention_mode');
  });

  it('keeps Save policy outside the settings form as the retention-scope primary', () => {
    mockUseQuery.mockReturnValue(createMockQuery({ data: defaultSettings }));
    render(<SettingsPageWithRouter />);

    const settingsForm = screen.getByRole('button', { name: 'Save Settings' }).closest('form');
    const savePolicy = screen.getByRole('button', { name: 'Save policy' });
    expect(settingsForm?.contains(savePolicy)).toBe(false);
    expect(settingsForm?.querySelectorAll('.acx-button--primary')).toHaveLength(0);
    expect(savePolicy).toHaveClass('acx-button--primary');
  });

  it('scrolls the retention section into view and focuses its heading when section=retention is in the location', () => {
    const scrolled: Element[] = [];
    const scrollSpy = vi.spyOn(Element.prototype, 'scrollIntoView').mockImplementation(function scrollIntoView(this: Element) {
      scrolled.push(this);
    });

    mockUseQuery.mockReturnValue(createMockQuery({ data: defaultSettings }));
    const router = createMemoryRouter(
      [{ path: '/settings', element: <SettingsPage /> }],
      { initialEntries: ['/settings?section=retention'] },
    );
    render(<RouterProvider router={router} />);

    const section = document.getElementById('acx-settings-section-retention');
    expect(section).not.toBeNull();
    expect(scrolled).toContain(section);

    const heading = document.getElementById('acx-retention-title');
    expect(heading).not.toBeNull();
    expect(document.activeElement).toBe(heading);

    scrollSpy.mockRestore();
  });

  it('scrolls and focuses the retention heading again when location changes to section=retention after mount', async () => {
    const scrolled: Element[] = [];
    const scrollSpy = vi.spyOn(Element.prototype, 'scrollIntoView').mockImplementation(function scrollIntoView(this: Element) {
      scrolled.push(this);
    });

    mockUseQuery.mockReturnValue(createMockQuery({ data: defaultSettings }));
    const router = createMemoryRouter(
      [{ path: '/settings', element: <SettingsPage /> }],
      { initialEntries: ['/settings'] },
    );
    render(<RouterProvider router={router} />);

    const section = document.getElementById('acx-settings-section-retention');
    expect(section).not.toBeNull();
    expect(scrolled).not.toContain(section);
    expect(document.activeElement).not.toBe(document.getElementById('acx-retention-title'));

    await act(async () => {
      await router.navigate('/settings?section=retention');
    });

    expect(scrolled).toContain(section);
    expect(document.activeElement).toBe(document.getElementById('acx-retention-title'));

    scrollSpy.mockRestore();
  });

  it('keeps deep-link focus on the retention heading when retention status resolves from pending to loaded', () => {
    mockUseQuery.mockReturnValue(createMockQuery({ data: defaultSettings }));
    const loadedRetention: ReturnType<typeof useRetentionStatus> = createMockQuery({
      data: {
        available: true,
        policy: {
          retention_mode: 'dispose_after_ack' as const,
          last_export_at: '2026-03-10T10:00:00Z',
          last_purge_at: null,
          retention_updated_at: '2026-03-09T12:00:00Z',
        },
        recent_audit_events: [],
      },
    });
    vi.mocked(useRetentionStatus).mockReturnValue(
      createMockQuery({ status: 'pending' }),
    );

    const TickContext = React.createContext(0);
    const SettingsWithTick = (): React.JSX.Element => {
      React.useContext(TickContext);
      return <SettingsPage />;
    };
    const router = createMemoryRouter(
      [{ path: '/settings', element: <SettingsWithTick /> }],
      { initialEntries: ['/settings?section=retention'] },
    );
    const { rerender } = render(
      <TickContext.Provider value={0}>
        <RouterProvider router={router} />
      </TickContext.Provider>,
    );

    expect(screen.getByText('Loading retention status…')).toBeInTheDocument();
    const headingWhilePending = document.getElementById('acx-retention-title');
    expect(headingWhilePending).not.toBeNull();
    expect(document.activeElement).toBe(headingWhilePending);

    vi.mocked(useRetentionStatus).mockReturnValue(loadedRetention);
    rerender(
      <TickContext.Provider value={1}>
        <RouterProvider router={router} />
      </TickContext.Provider>,
    );

    expect(screen.queryByText('Loading retention status…')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Save policy' })).toBeInTheDocument();
    const headingAfterLoad = document.getElementById('acx-retention-title');
    expect(headingAfterLoad).not.toBeNull();
    expect(headingAfterLoad).toHaveTextContent('Data & retention');
    expect(headingAfterLoad).toBe(headingWhilePending);
    expect(document.activeElement).toBe(headingWhilePending);
    expect(document.activeElement).toBe(headingAfterLoad);
  });

  it('does not request audit events when Settings mounts', () => {
    mockUseQuery.mockReturnValue(createMockQuery({ data: defaultSettings }));
    render(<SettingsPageWithRouter />);

    expect(useAuditEvents).not.toHaveBeenCalled();
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
    render(<SettingsPageWithRouter />);

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
    render(<SettingsPageWithRouter />);

    fireEvent.click(screen.getByRole('button', { name: 'Save Settings' }));

    expect(screen.getByText('No changes to save.')).toBeInTheDocument();
    expect(saveMutate).not.toHaveBeenCalled();
  });

  it('tests connection and invokes the test mutation for the service target', () => {
    mockUseQuery.mockReturnValue(createMockQuery({ data: defaultSettings }));
    render(<SettingsPageWithRouter />);

    fireEvent.click(screen.getByRole('button', { name: 'Check health' }));

    expect(testMutate).toHaveBeenCalledWith({});
  });

  it('keeps Check health enabled while the sync breaker reports offline (recovery affordance)', () => {
    // useSyncOffline is module-mocked to true for this whole file — the probe must stay usable
    // so the operator can heal the breaker (plan §3 trap-the-operator guard).
    mockUseQuery.mockReturnValue(createMockQuery({ data: defaultSettings }));
    render(<SettingsPageWithRouter />);

    const probeButton = screen.getByRole('button', { name: 'Check health' });
    expect(probeButton).toBeEnabled();
    fireEvent.click(probeButton);
    expect(testMutate).toHaveBeenCalledWith({});
  });

  it('updates the service health chip after a successful probe', () => {
    mockUseQuery.mockReturnValue(createMockQuery({ data: defaultSettings }));
    render(<SettingsPageWithRouter />);

    act(() => {
      capturedTestOptions?.onSuccess?.({
        outcome: 'connected',
        probe_mode: 'service_auth',
      });
    });

    expect(screen.getByTestId('acx-target-card-service')).toHaveTextContent('Reachable');
  });

  it('discloses one current authenticated InsightFace result for a service target', () => {
    mockUseQuery.mockReturnValue(createMockQuery({ data: defaultSettings }));
    render(<SettingsPageWithRouter />);
    const requestVariables = startTestConnection();

    act(() => {
      capturedTestOptions?.onSuccess?.({
        outcome: 'connected',
        status_code: 200,
        probe_mode: 'service_auth',
        probed_url: 'https://api.example.com/health/detailed',
        body: { status: 'ok', model_cache: { status: 'ok', profile: 'insightface' } },
      }, requestVariables);
    });

    expect(screen.getAllByText('Recognition engine: InsightFace')).toHaveLength(1);
  });

  it('discloses current local InsightFace proof on an FIR-named hostname', () => {
    const targetUrl = 'https://fir.example.com/local-service';
    mockUseQuery.mockReturnValue(createMockQuery({
      data: {
        ...defaultSettings,
        effective_target_url: targetUrl,
        effective_target_mode: 'local',
        recognition_source: 'local',
      },
    }));
    render(<SettingsPageWithRouter />);
    const requestVariables = startTestConnection();

    act(() => {
      capturedTestOptions?.onSuccess?.({
        outcome: 'connected',
        status_code: 200,
        probe_mode: 'service_auth',
        probed_url: `${targetUrl}/health/detailed`,
        body: { status: 'ok', model_cache: { status: 'ok', profile: 'insightface' } },
      }, requestVariables);
    });

    expect(screen.getAllByText('Recognition engine: InsightFace')).toHaveLength(1);
  });

  it('discloses InsightFace when overall health is degraded but the model cache is ok', () => {
    mockUseQuery.mockReturnValue(createMockQuery({ data: defaultSettings }));
    render(<SettingsPageWithRouter />);
    const requestVariables = startTestConnection();

    act(() => {
      capturedTestOptions?.onSuccess?.({
        outcome: 'connected',
        status_code: 200,
        probe_mode: 'service_auth',
        probed_url: 'https://api.example.com/health/detailed',
        body: { status: 'degraded', model_cache: { status: 'ok', profile: 'insightface' } },
      }, requestVariables);
    });

    expect(screen.getAllByText('Recognition engine: InsightFace')).toHaveLength(1);
  });

  const nonInsightFaceCases: Array<[string, SettingsResponse, TestConnectionResponse]> = [
    [
      'face_pipeline on the FIR-named service host',
      {
        ...defaultSettings,
        effective_target_url: 'https://fir.example.com/recognition',
      },
      {
        outcome: 'connected',
        status_code: 200,
        probe_mode: 'service_auth',
        probed_url: 'https://fir.example.com/recognition/health/detailed',
        body: { status: 'ok', model_cache: { status: 'ok', profile: 'face_pipeline' } },
      },
    ],
    [
      'auraface on a local target',
      {
        ...defaultSettings,
        effective_target_url: 'http://127.0.0.1:8000',
        effective_target_mode: 'local',
        recognition_source: 'local',
      },
      {
        outcome: 'connected',
        status_code: 200,
        probe_mode: 'service_auth',
        probed_url: 'http://127.0.0.1:8000/health/detailed',
        body: { status: 'ok', model_cache: { status: 'ok', profile: 'auraface' } },
      },
    ],
  ];

  it.each(nonInsightFaceCases)('does not infer InsightFace from %s', (_caseName, settings, result) => {
    mockUseQuery.mockReturnValue(createMockQuery({ data: settings }));
    render(<SettingsPageWithRouter />);
    const requestVariables = startTestConnection();

    act(() => {
      capturedTestOptions?.onSuccess?.(result, requestVariables);
    });

    expect(screen.queryByText('Recognition engine: InsightFace')).not.toBeInTheDocument();
  });

  it.each([
    ['a missing body', { outcome: 'connected', status_code: 200, probe_mode: 'service_auth' }],
    [
      'a raw-string body',
      {
        outcome: 'connected',
        status_code: 200,
        probe_mode: 'service_auth',
        probed_url: 'https://api.example.com/health/detailed',
        body: 'caption adapter reports insightface',
      },
    ],
    [
      'a null body',
      {
        outcome: 'connected',
        status_code: 200,
        probe_mode: 'service_auth',
        probed_url: 'https://api.example.com/health/detailed',
        body: null,
      },
    ],
    [
      'an array body',
      {
        outcome: 'connected',
        status_code: 200,
        probe_mode: 'service_auth',
        probed_url: 'https://api.example.com/health/detailed',
        body: [],
      },
    ],
    [
      'a missing model-cache profile',
      {
        outcome: 'connected',
        status_code: 200,
        probe_mode: 'service_auth',
        probed_url: 'https://api.example.com/health/detailed',
        body: { status: 'ok', model_cache: { status: 'ok' } },
      },
    ],
    [
      'an unknown profile',
      {
        outcome: 'connected',
        status_code: 200,
        probe_mode: 'service_auth',
        probed_url: 'https://api.example.com/health/detailed',
        body: { status: 'ok', model_cache: { status: 'ok', profile: 'other-engine' } },
      },
    ],
    [
      'caption-adapter-only evidence',
      {
        outcome: 'connected',
        status_code: 200,
        probe_mode: 'service_auth',
        probed_url: 'https://api.example.com/health/detailed',
        body: { status: 'ok', description_adapter: { status: 'ok', profile: 'insightface' } },
      },
    ],
    [
      'a ready boolean without model-cache proof',
      {
        outcome: 'connected',
        status_code: 200,
        probe_mode: 'service_auth',
        probed_url: 'https://api.example.com/health/detailed',
        body: { status: 'ok', ready: true },
      },
    ],
    [
      'an unavailable result',
      { outcome: 'not_configured', probe_mode: 'service_auth', probed_url: '' },
    ],
    ['a transport error', { outcome: 'network_error', probe_mode: 'service_auth' }],
    [
      'a lifecycle result',
      {
        outcome: 'starting',
        status_code: 200,
        probe_mode: 'service_auth',
        probed_url: 'https://api.example.com/scene/gpu/intent',
        body: { status: 'ok', model_cache: { status: 'ok', profile: 'insightface' } },
      },
    ],
    [
      'an unhealthy HTTP-200 result',
      {
        outcome: 'server_error',
        status_code: 200,
        probe_mode: 'service_auth',
        probed_url: 'https://api.example.com/health/detailed',
        body: { status: 'unhealthy', model_cache: { status: 'ok', profile: 'insightface' } },
      },
    ],
    [
      'a response for a different endpoint',
      {
        outcome: 'connected',
        status_code: 200,
        probe_mode: 'service_auth',
        probed_url: 'https://api.example.com:8443/health/detailed',
        body: { status: 'ok', model_cache: { status: 'ok', profile: 'insightface' } },
      },
    ],
  ])('keeps %s evidence undisclosed', (_caseName, result) => {
    mockUseQuery.mockReturnValue(createMockQuery({ data: defaultSettings }));
    render(<SettingsPageWithRouter />);
    const requestVariables = startTestConnection();

    act(() => {
      capturedTestOptions?.onSuccess?.(result, requestVariables);
    });

    expect(screen.queryByText('Recognition engine: InsightFace')).not.toBeInTheDocument();
  });

  it('shows the single passive disclosure only for current proof, not while pending, edited, or unavailable', () => {
    mockUseQuery.mockReturnValue(createMockQuery({ data: defaultSettings }));
    render(<SettingsPageWithRouter />);
    const currentRequestVariables = startTestConnection();

    act(() => {
      capturedTestOptions?.onSuccess?.({
        outcome: 'connected',
        status_code: 200,
        probe_mode: 'service_auth',
        probed_url: 'https://api.example.com/health/detailed',
        body: { status: 'ok', model_cache: { status: 'ok', profile: 'insightface' } },
      }, currentRequestVariables);
    });
    const currentLineCount = screen.queryAllByText('Recognition engine: InsightFace').length;

    testMutationPending = true;
    const pendingRequestVariables = startTestConnection();
    const pendingLineCount = screen.queryAllByText('Recognition engine: InsightFace').length;

    fireEvent.change(screen.getByLabelText('Service API URL'), {
      target: { value: 'https://edited-api.example.com' },
    });
    const editedLineCount = screen.queryAllByText('Recognition engine: InsightFace').length;

    testMutationPending = false;
    act(() => {
      capturedTestOptions?.onError?.(new Error('request failed'), pendingRequestVariables);
    });
    const unavailableLineCount = screen.queryAllByText('Recognition engine: InsightFace').length;

    expect({ currentLineCount, pendingLineCount, editedLineCount, unavailableLineCount }).toEqual({
      currentLineCount: 1,
      pendingLineCount: 0,
      editedLineCount: 0,
      unavailableLineCount: 0,
    });
  });

  it('waits for a cached Settings refetch before automatically checking and disclosing the current target', () => {
    const refreshedSettings = { ...defaultSettings };
    let settingsQuery = createMockQuery({
      data: defaultSettings,
      dataUpdatedAt: 100,
      isFetching: true,
    });
    mockUseQuery.mockImplementation(() => settingsQuery);
    const view = render(<SettingsPageWithRouter />);

    expect(testMutate).not.toHaveBeenCalled();
    expect(screen.queryByText('Reachable')).not.toBeInTheDocument();

    settingsQuery = createMockQuery({
      data: refreshedSettings,
      dataUpdatedAt: 101,
      isFetching: false,
    });
    view.rerender(<SettingsPageWithRouter />);

    expect(testMutate).toHaveBeenCalledTimes(1);
    const automaticRequestVariables = testMutate.mock.calls[0]?.[0] as Record<string, unknown>;
    expect(automaticRequestVariables).toEqual({});
    act(() => {
      capturedTestOptions?.onSuccess?.({
        outcome: 'connected',
        status_code: 200,
        probe_mode: 'service_auth',
        probed_url: 'https://api.example.com/health/detailed',
        body: { status: 'ok', model_cache: { status: 'ok', profile: 'insightface' } },
      }, automaticRequestVariables);
    });

    expect(screen.getByTestId('acx-target-card-service')).toHaveTextContent('Reachable');
    expect(screen.getAllByText('Recognition engine: InsightFace')).toHaveLength(1);
  });

  it.each([
    ['while the Settings refetch is pending', false],
    ['after refreshed Settings is published', true],
  ])('retries the automatic check after an old request rejects %s', (_completionOrder, rejectAfterRefresh) => {
    let settingsQuery = createMockQuery({
      data: defaultSettings,
      dataUpdatedAt: 200,
      isFetching: false,
    });
    mockUseQuery.mockImplementation(() => settingsQuery);
    const view = render(<SettingsPageWithRouter />);
    expect(testMutate).toHaveBeenCalledTimes(1);
    const oldRequestVariables = testMutate.mock.calls[0]?.[0] as Record<string, unknown>;

    settingsQuery = createMockQuery({
      data: defaultSettings,
      dataUpdatedAt: 200,
      isFetching: true,
    });
    view.rerender(<SettingsPageWithRouter />);

    if (!rejectAfterRefresh) {
      act(() => {
        capturedTestOptions?.onError?.(new Error('old request rejected'), oldRequestVariables);
      });
      expect(screen.queryByTestId('acx-test-connection-banner')).not.toBeInTheDocument();
    }

    const refreshedSettings = { ...defaultSettings };
    settingsQuery = createMockQuery({
      data: refreshedSettings,
      dataUpdatedAt: 201,
      isFetching: false,
    });
    view.rerender(<SettingsPageWithRouter />);

    expect(testMutate).toHaveBeenCalledTimes(2);
    const currentRequestVariables = testMutate.mock.calls[1]?.[0] as Record<string, unknown>;
    expect(currentRequestVariables).toEqual({});
    expect(currentRequestVariables).not.toBe(oldRequestVariables);

    if (rejectAfterRefresh) {
      act(() => {
        capturedTestOptions?.onError?.(new Error('old request rejected'), oldRequestVariables);
      });
      expect(screen.queryByTestId('acx-test-connection-banner')).not.toBeInTheDocument();
    }

    act(() => {
      capturedTestOptions?.onSuccess?.({
        outcome: 'connected',
        status_code: 200,
        probe_mode: 'service_auth',
        probed_url: 'https://api.example.com/health/detailed',
        body: { status: 'ok', model_cache: { status: 'ok', profile: 'insightface' } },
      }, currentRequestVariables);
    });

    expect(screen.getByTestId('acx-target-card-service')).toHaveTextContent('Reachable');
    expect(screen.getAllByText('Recognition engine: InsightFace')).toHaveLength(1);
  });

  it.each(['error', 'success'] as const)(
    'keeps the queued health check through a cache-first Settings refetch when R0 returns %s',
    async (completion) => {
      const savedSettings: SettingsResponse = {
        ...defaultSettings,
        url: 'https://saved-api.example.com',
        effective_target_url: 'https://saved-api.example.com',
      };
      const currentSettings: SettingsResponse = {
        ...savedSettings,
        url: 'https://current-api.example.com',
        effective_target_url: 'https://current-api.example.com',
        tenant_paired: true,
      };
      const queryClient = new QueryClient({
        defaultOptions: { queries: { gcTime: Infinity, retry: false } },
      });
      mockQueryClientRef.current = queryClient;
      let resolveInitialSettings: (settings: SettingsResponse) => void = () => {};
      const initialSettingsRequest = new Promise<SettingsResponse>((resolve) => {
        resolveInitialSettings = resolve;
      });
      vi.mocked(fetchSettings).mockImplementation(() => initialSettingsRequest);
      const initialFetch = queryClient.fetchQuery({
        queryKey: queryKeys.settings.all,
        queryFn: fetchSettings,
      });
      const initialPendingState = queryClient.getQueryState<SettingsResponse>(queryKeys.settings.all);
      expect(initialPendingState).toMatchObject({
        status: 'pending',
        fetchStatus: 'fetching',
        data: undefined,
      });
      let publishedSettingsQuery: QueryHookResult = createMockQuery<SettingsResponse>({
        status: 'pending',
        isFetching: true,
        fetchStatus: 'fetching',
        dataUpdatedAt: initialPendingState!.dataUpdatedAt,
      });
      expect(publishedSettingsQuery.data).toBe(initialPendingState?.data);
      expect(publishedSettingsQuery.dataUpdatedAt).toBe(initialPendingState?.dataUpdatedAt);
      mockUseQuery.mockImplementation(() => publishedSettingsQuery);

      const view = render(<SettingsPageWithRouter />);
      const publishSettingsCache = (): void => {
        const queryState = queryClient.getQueryState<SettingsResponse>(queryKeys.settings.all);
        const cachedSettings = queryClient.getQueryData<SettingsResponse>(queryKeys.settings.all);
        expect(queryState).toBeDefined();
        expect(cachedSettings).toBeDefined();
        expect(queryState?.data).toBe(cachedSettings);
        publishedSettingsQuery = createMockQuery<SettingsResponse>({
          data: cachedSettings!,
          dataUpdatedAt: queryState!.dataUpdatedAt,
          isFetching: queryState?.fetchStatus === 'fetching',
          fetchStatus: queryState!.fetchStatus,
        });
        view.rerender(<SettingsPageWithRouter />);
        expect(publishedSettingsQuery.data).toBe(cachedSettings);
        expect(publishedSettingsQuery.dataUpdatedAt).toBe(queryState!.dataUpdatedAt);
      };

      // Load and publish the real initial query result. A settled initial mount
      // legitimately starts its automatic health check, so complete that
      // request before measuring the post-save R0/R1 sequence below.
      await act(async () => {
        resolveInitialSettings(defaultSettings);
        await initialFetch;
      });
      publishSettingsCache();
      const initialCachedSettings = queryClient.getQueryData<SettingsResponse>(queryKeys.settings.all);
      const initialQueryState = queryClient.getQueryState<SettingsResponse>(queryKeys.settings.all);
      expect(initialCachedSettings).toBeDefined();
      expect(initialQueryState).toBeDefined();
      expect(initialQueryState?.data).toBe(initialCachedSettings);
      expect(publishedSettingsQuery.data).toBe(initialCachedSettings);
      expect(publishedSettingsQuery.dataUpdatedAt).toBe(initialQueryState!.dataUpdatedAt);
      expect(testMutate).toHaveBeenCalledTimes(1);
      const initialRequestVariables = testMutate.mock.calls[0]?.[0] as Record<string, unknown>;
      expect(initialRequestVariables).toBeDefined();
      act(() => {
        capturedTestOptions!.onError!(new Error('initial check failed'), initialRequestVariables);
      });
      expect(testMutate).toHaveBeenCalledTimes(1);
      // The page legitimately starts Rinitial after the initial query settles.
      // Complete it, then isolate the existing post-save R0/R1 count assertions.
      testMutate.mockClear();
      vi.mocked(fetchSettings).mockResolvedValue(savedSettings);

      fireEvent.change(screen.getByLabelText('Service API URL'), {
        target: { value: savedSettings.url },
      });
      fireEvent.blur(screen.getByLabelText('Service API URL'));
      expect(saveMutate).toHaveBeenCalledWith({ url: savedSettings.url });

      await act(async () => {
        await Promise.resolve(
          capturedSaveOptions!.onSuccess!({ saved: ['url'], result: 'ok' }),
        );
      });

      const savedSettingsInCache = queryClient.getQueryData<SettingsResponse>(queryKeys.settings.all);
      const savedQueryState = queryClient.getQueryState<SettingsResponse>(queryKeys.settings.all);
      expect(savedSettingsInCache).toBeDefined();
      expect(savedSettingsInCache).toEqual(savedSettings);
      expect(savedQueryState?.data).toBe(savedSettingsInCache);
      // The live cache has the saved snapshot while the mock hook still exposes
      // the initial identity and stamp until the cache publication is rendered.
      expect(publishedSettingsQuery.data).toBe(initialCachedSettings);
      expect(publishedSettingsQuery.dataUpdatedAt).toBe(initialQueryState!.dataUpdatedAt);
      expect(testMutate).not.toHaveBeenCalled();

      // Publish the actual cache value and stamp created by the save refetch;
      // this is the settled state from which the automatic R0 is bound.
      publishSettingsCache();
      expect(publishedSettingsQuery.data).toBe(savedSettingsInCache);
      expect(testMutate).toHaveBeenCalledTimes(1);
      const oldRequestVariables = testMutate.mock.calls[0]?.[0] as Record<string, unknown>;
      expect(oldRequestVariables).toBeDefined();

      let resolveBackgroundSettings: (settings: SettingsResponse) => void = () => {};
      const backgroundSettings = new Promise<SettingsResponse>((resolve) => {
        resolveBackgroundSettings = resolve;
      });
      vi.mocked(fetchSettings).mockImplementation(() => backgroundSettings);
      let backgroundRefetch!: Promise<void>;
      act(() => {
        backgroundRefetch = queryClient.refetchQueries({
          queryKey: queryKeys.settings.all,
          type: 'all',
        });
      });

      // Query state changes synchronously; the mock hook still exposes the
      // prior settled publication until publishSettingsCache is called.
      expect(queryClient.getQueryState(queryKeys.settings.all)?.fetchStatus).toBe('fetching');
      expect(publishedSettingsQuery.isFetching).toBe(false);
      expect(publishedSettingsQuery.data).toBe(savedSettings);

      if (completion === 'error') {
        act(() => {
          capturedTestOptions!.onError!(new Error('R0 failed'), oldRequestVariables);
        });
      } else {
        act(() => {
          capturedTestOptions!.onSuccess!({
            outcome: 'connected',
            status_code: 200,
            probe_mode: 'service_auth',
            probed_url: `${savedSettings.effective_target_url}/health/detailed`,
            body: { status: 'ok', model_cache: { status: 'ok', profile: 'insightface' } },
          }, oldRequestVariables);
        });
      }

      expect(queryClient.getQueryState(queryKeys.settings.all)?.fetchStatus).toBe('fetching');
      expect(screen.getByTestId('acx-target-card-service')).toHaveTextContent('Not checked');
      expect(screen.queryByTestId('acx-test-connection-banner')).not.toBeInTheDocument();
      expect(screen.queryByText('Recognition engine: InsightFace')).not.toBeInTheDocument();

      // The hook now publishes the pending state. It must keep the queued
      // automatic check waiting until refreshed data and stamp are aligned.
      publishSettingsCache();
      expect(publishedSettingsQuery.isFetching).toBe(true);
      expect(testMutate).toHaveBeenCalledTimes(1);
      expect(screen.getByTestId('acx-target-card-service')).toHaveTextContent('Not checked');

      await act(async () => {
        resolveBackgroundSettings(currentSettings);
        await backgroundRefetch;
      });
      publishSettingsCache();

      const currentSettingsInCache = queryClient.getQueryData<SettingsResponse>(queryKeys.settings.all);
      expect(currentSettingsInCache).toEqual(currentSettings);
      expect(publishedSettingsQuery.data).toBe(currentSettingsInCache);
      expect(publishedSettingsQuery.isFetching).toBe(false);
      expect(testMutate).toHaveBeenCalledTimes(2);
      const currentRequestVariables = testMutate.mock.calls[1]?.[0] as Record<string, unknown>;
      expect(currentRequestVariables).toEqual({});
      expect(currentRequestVariables).not.toBe(oldRequestVariables);

      act(() => {
        capturedTestOptions!.onSuccess!({
          outcome: 'connected',
          status_code: 200,
          probe_mode: 'service_auth',
          probed_url: `${currentSettings.effective_target_url}/health/detailed`,
          body: { status: 'ok', model_cache: { status: 'ok', profile: 'insightface' } },
        }, currentRequestVariables);
      });

      expect(screen.getByTestId('acx-target-card-service')).toHaveTextContent('Reachable');
      expect(screen.getAllByText('Recognition engine: InsightFace')).toHaveLength(1);
    },
  );

  it.each([
    [
      'URL edit',
      'Service API URL',
      'https://replacement-api.example.com',
      { url: 'https://replacement-api.example.com' },
    ],
    [
      'key replacement with the same displayed last four characters',
      'API Key',
      'replacement-secret-abcd',
      { api_key: 'replacement-secret-abcd' },
    ],
  ])('does not restore connected health after a late probe races a %s autosave', (
    _caseName,
    fieldLabel,
    fieldValue,
    expectedSave,
  ) => {
    mockUseQuery.mockReturnValue(createMockQuery({ data: defaultSettings }));
    render(<SettingsPageWithRouter />);
    expect(screen.getByLabelText('API Key')).toHaveAttribute('placeholder', 'Current: ****abcd');

    const freshRequestVariables = startTestConnection();
    act(() => {
      capturedTestOptions?.onSuccess?.({
        outcome: 'connected',
        status_code: 200,
        probe_mode: 'service_auth',
        probed_url: 'https://api.example.com/health/detailed',
        body: { status: 'ok', model_cache: { status: 'ok', profile: 'insightface' } },
      }, freshRequestVariables);
    });
    expect(screen.getByTestId('acx-target-card-service')).toHaveTextContent('Reachable');

    const staleRequestVariables = startTestConnection();
    expect(screen.queryByText('Reachable')).not.toBeInTheDocument();
    expect(screen.queryByText('Recognition engine: InsightFace')).not.toBeInTheDocument();

    const editedField = screen.getByLabelText(fieldLabel);
    fireEvent.change(editedField, { target: { value: fieldValue } });
    fireEvent.blur(editedField);
    expect(saveMutate).toHaveBeenCalledWith(expectedSave);
    expect(screen.queryByText('Recognition engine: InsightFace')).not.toBeInTheDocument();

    act(() => {
      capturedTestOptions?.onSuccess?.({
        outcome: 'connected',
        status_code: 200,
        probe_mode: 'service_auth',
        probed_url: 'https://api.example.com/health/detailed',
        body: { status: 'ok', model_cache: { status: 'ok', profile: 'insightface' } },
      }, staleRequestVariables);
    });

    expect(screen.queryByText('Reachable')).not.toBeInTheDocument();
    expect(screen.queryByText('Recognition engine: InsightFace')).not.toBeInTheDocument();
  });

  it('renders the tenant id and unpaired status when the tenant is not paired', () => {
    mockUseQuery.mockReturnValue(createMockQuery({ data: defaultSettings }));
    render(<SettingsPageWithRouter />);

    expect(screen.getByTestId('acx-tenant-id')).toHaveTextContent('aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee');
    expect(screen.getByTestId('acx-tenant-pairing-status')).toHaveTextContent('Not paired yet');
  });

  it('renders the paired status when the tenant is paired', () => {
    mockUseQuery.mockReturnValue(createMockQuery({ data: { ...defaultSettings, tenant_paired: true } }));
    render(<SettingsPageWithRouter />);

    expect(screen.getByTestId('acx-tenant-pairing-status')).toHaveTextContent(
      'Paired with the recognition service',
    );
  });

  it('refetches sync health after a successful save so the offline banner clears', async () => {
    mockUseQuery.mockReturnValue(createMockQuery({ data: defaultSettings }));
    render(<SettingsPageWithRouter />);

    expect(capturedSaveOptions?.onSuccess).toBeDefined();
    // onSuccess is async at runtime but typed void; wrap so we await the real work.
    // R23-BR-14: pass an ok envelope so the success path runs (not partial/error).
    await act(async () => {
      await Promise.resolve(
        capturedSaveOptions!.onSuccess!({ saved: ['url'], result: 'ok' }),
      );
    });

    expect(mockInvalidateQueries).toHaveBeenCalledWith({ queryKey: ['sync', 'health'] });
  });

  it('shows Settings saved only when result is ok (R23-BR-14)', async () => {
    mockUseQuery.mockReturnValue(createMockQuery({ data: defaultSettings }));
    render(<SettingsPageWithRouter />);

    await act(async () => {
      await Promise.resolve(
        capturedSaveOptions!.onSuccess!({ saved: ['url', 'api_key'], result: 'ok' }),
      );
    });

    const banner = screen.getByTestId('acx-settings-save-message');
    expect(banner.textContent).toBe('Settings saved.');
    expect(banner.getAttribute('role')).toBe('status');
  });

  it('does not show Settings saved on partial storage failure (R23-BR-14)', async () => {
    mockUseQuery.mockReturnValue(createMockQuery({ data: defaultSettings }));
    render(<SettingsPageWithRouter />);

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
    render(<SettingsPageWithRouter />);

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
    render(<SettingsPageWithRouter />);

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

  it('surfaces the server deployment-key URL message when save is rejected (SECFIX-1)', () => {
    const deploymentKeyUrlMessage =
      'A deployment-managed recognition API key is configured; set the recognition URL with ACX_RECOGNITION_URL or the acx_recognition_base_url filter instead of saving it here.';
    mockUseQuery.mockReturnValue(createMockQuery({ data: defaultSettings }));
    render(<SettingsPageWithRouter />);

    expect(capturedSaveOptions?.onError).toBeDefined();
    act(() => {
      capturedSaveOptions!.onError!(
        new Error(
          `Request to /acx/v1/settings failed (400): {"code":"deployment_key_requires_deployment_url","message":"${deploymentKeyUrlMessage}","data":{"status":400}}`,
        ),
      );
    });

    const banner = screen.getByTestId('acx-settings-save-message');
    expect(banner.textContent).toBe(deploymentKeyUrlMessage);
    expect(banner.getAttribute('role')).toBe('alert');
  });

  it('falls back to the generic save failure when the rejection is unstructured', () => {
    mockUseQuery.mockReturnValue(createMockQuery({ data: defaultSettings }));
    render(<SettingsPageWithRouter />);

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
    render(<SettingsPageWithRouter />);

    act(() => {
      capturedTestOptions?.onSuccess?.({ outcome: 'connected', probe_mode: 'service_auth' });
    });

    expect(mockInvalidateQueries).toHaveBeenCalledWith({ queryKey: ['sync', 'health'] });
  });

  it('does not refetch sync health when a probe fails', () => {
    // A failed probe must not clear the offline banner: sync.health stays as-is.
    mockUseQuery.mockReturnValue(createMockQuery({ data: defaultSettings }));
    render(<SettingsPageWithRouter />);

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
    render(<SettingsPageWithRouter />);

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
    render(<SettingsPageWithRouter />);

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
    render(<SettingsPageWithRouter />);

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
    render(<SettingsPageWithRouter />);

    const routing = screen.getByTestId('acx-effective-routing');
    const rejection = screen.getByTestId('acx-url-rejection');
    expect(rejection).toHaveTextContent(
      'Rejected http://10.0.0.5:8000 (Saved in database): HTTP is only allowed for loopback development hosts (localhost, 127.0.0.1, ::1)',
    );
    expect(routing).not.toHaveTextContent('not configured');
    // Status is text, not decoration alone (A11Y-21).
    expect(routing).toHaveAttribute('role', 'status');
  });

  it('explains when an option URL is rejected because a deployment key requires a deployment URL (SECFIX-1)', () => {
    mockUseQuery.mockReturnValue(
      createMockQuery({
        data: {
          ...defaultSettings,
          url: '',
          url_source: 'default',
          url_rejection_reason: UrlRejectionReason.DEPLOYMENT_KEY_REQUIRES_DEPLOYMENT_URL,
          url_rejection_source: 'option',
          url_rejection_value: 'https://attacker.example',
          effective_target_url: '',
          effective_target_mode: 'service',
          recognition_source: 'service',
        },
      }),
    );
    render(<SettingsPageWithRouter />);

    const rejection = screen.getByTestId('acx-url-rejection');
    expect(rejection).toHaveTextContent(
      'a deployment-managed API key is configured, so the recognition URL must come from ACX_RECOGNITION_URL or the acx_recognition_base_url filter',
    );
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
    render(<SettingsPageWithRouter />);

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
    render(<SettingsPageWithRouter />);

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
    render(<SettingsPageWithRouter />);

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
    render(<SettingsPageWithRouter />);

    expect(screen.queryByRole('button', { name: 'Configure service URL' })).not.toBeInTheDocument();
    expect(
      screen.queryByText(/No service URL configured yet/),
    ).not.toBeInTheDocument();
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
    render(<SettingsPageWithRouter />);

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
    render(<SettingsPageWithRouter />);

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

  it('keeps Check health enabled when routing edits are unsaved', () => {
    mockUseQuery.mockReturnValue(createMockQuery({ data: defaultSettings }));
    render(<SettingsPageWithRouter />);

    fireEvent.change(screen.getByLabelText('Service API URL'), {
      target: { value: 'https://new-api.example.com' },
    });

    expect(screen.getByRole('button', { name: 'Check health' })).toBeEnabled();
    expect(screen.queryByText(/Save settings before scanning or testing/)).not.toBeInTheDocument();
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
      render(<SettingsPageWithRouter />);
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
