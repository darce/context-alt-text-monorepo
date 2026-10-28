import React from 'react';
import { act, render, screen, fireEvent, within } from '@testing-library/react';
import { QueryClient } from '@tanstack/react-query';
import { MemoryRouter, RouterProvider, createMemoryRouter } from 'react-router-dom';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

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
      expect(publishedSettingsQuery.data).toBe(savedSettingsInCache);

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

    it('rechecks health after publishing the tenant adopted by confirmation', async () => {
      const tenantASettings = { ...defaultSettings };
      const tenantBSettings: SettingsResponse = {
        ...defaultSettings,
        tenant_id: 'ffffffff-ffff-4fff-8fff-ffffffffffff',
        tenant_paired: true,
      };
      const tenantBHealthResponse: TestConnectionResponse = {
        outcome: 'connected',
        status_code: 200,
        probe_mode: 'service_auth',
        probed_url: 'https://api.example.com/health/detailed',
        tenant_id: tenantBSettings.tenant_id,
        body: { status: 'ok', model_cache: { status: 'ok', profile: 'insightface' } },
      };
      const queryClient = new QueryClient({
        defaultOptions: { queries: { gcTime: Infinity, retry: false } },
      });
      mockQueryClientRef.current = queryClient;
      queryClient.setQueryData(queryKeys.settings.all, tenantASettings);
      const tenantAQueryState = queryClient.getQueryState<SettingsResponse>(queryKeys.settings.all)!;
      let publishedSettingsQuery = createMockQuery<SettingsResponse>({
        data: tenantAQueryState.data,
        dataUpdatedAt: tenantAQueryState.dataUpdatedAt,
      });
      mockUseQuery.mockImplementation(() => publishedSettingsQuery);
      vi.mocked(fetchSettings).mockResolvedValue(tenantBSettings);

      const view = render(<SettingsPageWithRouter />);
      expect(testMutate).toHaveBeenCalledTimes(1);
      const initialRequestVariables = testMutate.mock.calls[0]?.[0] as Record<string, unknown>;
      act(() => {
        capturedTestOptions!.onSuccess!({ outcome: 'tenant_mismatch' }, initialRequestVariables);
      });
      expect(screen.getByTestId('acx-confirm-tenant-pairing')).toBeInTheDocument();

      fireEvent.click(screen.getByTestId('acx-confirm-tenant-pairing'));
      expect(testMutate).toHaveBeenCalledTimes(2);
      const confirmRequestVariables = testMutate.mock.calls[1]?.[0] as Record<string, unknown>;
      expect(confirmRequestVariables).toEqual({ confirm_tenant_pairing: true });

      await act(async () => {
        await Promise.resolve(capturedTestOptions!.onSuccess!(tenantBHealthResponse, confirmRequestVariables));
      });

      const cachedTenantB = queryClient.getQueryData<SettingsResponse>(queryKeys.settings.all)!;
      const tenantBQueryState = queryClient.getQueryState<SettingsResponse>(queryKeys.settings.all)!;
      expect(fetchSettings).toHaveBeenCalledTimes(1);
      expect(cachedTenantB.tenant_id).toBe(tenantBSettings.tenant_id);
      expect(tenantBQueryState).toMatchObject({ status: 'success', fetchStatus: 'idle' });
      expect(tenantBQueryState.data).toBe(cachedTenantB);
      expect(publishedSettingsQuery.data).toBe(tenantASettings);
      const requestsBeforePublishingTenantB = testMutate.mock.calls.length;
      expect(requestsBeforePublishingTenantB).toBe(2);
      publishedSettingsQuery = createMockQuery<SettingsResponse>({
        data: cachedTenantB,
        dataUpdatedAt: tenantBQueryState.dataUpdatedAt,
        fetchStatus: tenantBQueryState.fetchStatus,
      });
      view.rerender(<SettingsPageWithRouter />);
      expect(publishedSettingsQuery.data).toBe(cachedTenantB);
      expect(publishedSettingsQuery.dataUpdatedAt).toBe(tenantBQueryState.dataUpdatedAt);
      expect(testMutate).toHaveBeenCalledTimes(requestsBeforePublishingTenantB + 1);
      expect(screen.queryByTestId('acx-test-connection-banner')).not.toBeInTheDocument();
      expect(screen.getByTestId('acx-target-card-service')).toHaveTextContent('Not checked');
      expect(screen.queryByText('Recognition engine: InsightFace')).not.toBeInTheDocument();

      const tenantBRequestVariables = testMutate.mock.calls[requestsBeforePublishingTenantB]?.[0] as Record<string, unknown>;
      expect(tenantBRequestVariables).toEqual({});
      expect(tenantBRequestVariables).not.toBe(confirmRequestVariables);
      act(() => {
        capturedTestOptions!.onSuccess!(tenantBHealthResponse, tenantBRequestVariables);
      });

      expect(screen.getByTestId('acx-test-connection-banner')).toHaveTextContent('Connection successful.');
      expect(screen.getAllByText('Recognition engine: InsightFace')).toHaveLength(1);
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

// Independent Q-C-r1 probes use the installed React Query hooks and client.
describe('QCR real React Query credential boundaries', () => {
  const clients: QueryClient[] = [];
  afterEach(() => { act(() => { for (const client of clients.splice(0)) client.clear(); }); });

  const deferred = <T,>() => {
    let resolve!: (value: T) => void;
    let reject!: (error: Error) => void;
    const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
    return { promise, resolve, reject };
  };
  const flush = async () => { await act(async () => { for (let i = 0; i < 20; i++) await Promise.resolve(); }); };
  const harness = async (initial = defaultSettings, staleTime = Infinity) => {
    const real = await vi.importActual<typeof import('@tanstack/react-query')>('@tanstack/react-query');
    const api = await import('../../api/settingsApi');
    const client = new QueryClient({ defaultOptions: {
      queries: { gcTime: Infinity, retry: false, staleTime, refetchOnWindowFocus: false },
      mutations: { gcTime: Infinity, retry: false },
    } });
    clients.push(client);
    client.setQueryData(queryKeys.settings.all, initial);
    mockQueryClientRef.current = client;
    mockUseQuery.mockImplementation(real.useQuery as never);
    mockUseMutation.mockImplementation(real.useMutation as never);
    let persisted = initial;
    vi.mocked(api.fetchSettings).mockImplementation(() => Promise.resolve(persisted));
    vi.mocked(api.testConnection).mockResolvedValue({ outcome: 'network_error' });
    const requests: ({ payload: import('../../api/settingsApi').SaveSettingsPayload } & ReturnType<typeof deferred<import('../../api/settingsApi').SaveSettingsResponse>>)[] = [];
    vi.mocked(api.saveSettings).mockImplementation((payload) => {
      const request = { payload, ...deferred<import('../../api/settingsApi').SaveSettingsResponse>() };
      requests.push(request);
      return request.promise;
    });
    const view = render(<real.QueryClientProvider client={client}><SettingsPageWithRouter /></real.QueryClientProvider>);
    await flush();
    vi.mocked(api.testConnection).mockClear();
    return { api, client, requests, view, persist: (settings: SettingsResponse) => { persisted = settings; } };
  };
  const type = (element: HTMLElement, value: string) => fireEvent.change(element, { target: { value } });
  const finish = async (request: ReturnType<typeof deferred<import('../../api/settingsApi').SaveSettingsResponse>>, result: import('../../api/settingsApi').SaveSettingsResponse) => {
    await act(() => Promise.resolve(request.resolve(result)));
    await flush();
  };

  it.each(['independent', 'queued'] as const)('R4-F1 retains whole-form Retry alongside a later routing readback warning: %s', async (mode) => {
    const h = await harness();
    const url = screen.getByLabelText('Service API URL');
    const budget = screen.getByLabelText('Maximum description attempts');
    const urlA = 'https://review-a.example.com';
    const urlB = 'https://review-b.example.com';
    type(url, urlA); type(budget, '4');
    fireEvent.click(screen.getByRole('button', { name: 'Save Settings' })); await flush();
    expect(h.requests[0].payload).toEqual({ url: urlA, description_budget: { max_attempts: 4 } });
    if (mode === 'queued') { type(url, urlB); fireEvent.blur(url); await flush(); }
    h.persist({ ...defaultSettings, url: urlA, effective_target_url: urlA });
    await finish(h.requests[0], { saved: ['url'], failed: ['description_budget'], result: 'partial' });
    if (mode === 'independent') {
      expect(screen.getByRole('button', { name: 'Retry save' })).toBeEnabled();
      type(url, urlB); fireEvent.blur(url); await flush();
    }
    expect(h.requests[1].payload).toEqual({ url: urlB });
    vi.mocked(h.api.fetchSettings).mockRejectedValue(new Error('review readback unavailable'));
    await finish(h.requests[1], { saved: ['url'], result: 'ok' });
    const card = screen.getByTestId('acx-target-card-service');
    expect(budget).toHaveValue(4);
    expect(within(card).getByText('Could not save settings. (description_budget)')).toBeInTheDocument();
    expect(card).toHaveTextContent('Saved, but the page could not reload settings: settings unavailable.');
    expect(within(card).getByRole('button', { name: 'Reload settings' })).toBeEnabled();
    if (mode === 'queued') {
      vi.mocked(h.api.fetchSettings).mockResolvedValue({ ...defaultSettings, url: urlB, effective_target_url: urlB });
      fireEvent.click(within(card).getByRole('button', { name: 'Reload settings' })); await flush();
      expect(h.requests).toHaveLength(2);
      expect(budget).toHaveValue(4);
      expect(within(card).getByText('Could not save settings. (description_budget)')).toBeInTheDocument();
      expect(within(card).queryByRole('button', { name: 'Reload settings' })).not.toBeInTheDocument();
    }
    fireEvent.click(within(card).getByRole('button', { name: 'Retry save' })); await flush();
    expect(h.requests[2].payload).toEqual({ description_budget: { max_attempts: 4 } });
    vi.mocked(h.api.fetchSettings).mockResolvedValue({
      ...defaultSettings, url: urlB, effective_target_url: urlB,
      description_budget: { ...defaultSettings.description_budget, max_attempts: 4 },
    });
    await finish(h.requests[2], { saved: ['description_budget'], result: 'ok' });
    expect(screen.queryByText(/Could not save settings/)).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Reload settings' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Retry save' })).not.toBeInTheDocument();
  });

  it('R4-F2 Check health during a budget-only Save survives an empty routing drain exactly once', async () => {
    const h = await harness();
    type(screen.getByLabelText('Maximum description attempts'), '4');
    fireEvent.click(screen.getByRole('button', { name: 'Save Settings' })); await flush();
    const check = screen.getByRole('button', { name: 'Check health' });
    expect(check).toBeEnabled();
    fireEvent.click(check); fireEvent.click(check); await flush();
    expect(h.api.testConnection).not.toHaveBeenCalled();
    const readback = deferred<SettingsResponse>();
    vi.mocked(h.api.fetchSettings).mockReturnValue(readback.promise);
    await finish(h.requests[0], { saved: ['description_budget'], result: 'ok' });
    expect(h.api.fetchSettings).toHaveBeenCalled();
    expect(h.api.testConnection).not.toHaveBeenCalled();
    await act(async () => { readback.resolve({
      ...defaultSettings,
      description_budget: { ...defaultSettings.description_budget, max_attempts: 4 },
    }); });
    await flush();
    expect(h.requests).toHaveLength(1);
    expect(h.api.testConnection).toHaveBeenCalledTimes(1);
    expect(vi.mocked(h.api.testConnection).mock.calls[0][0]).toEqual({});
    await flush();
    expect(h.api.testConnection).toHaveBeenCalledTimes(1);
    expect(screen.getByLabelText('Maximum description attempts')).toHaveValue(4);
  });

  it('R4-control a partial subset acknowledgement preserves newer non-routing edits through routing', async () => {
    const h = await harness();
    const url = screen.getByLabelText('Service API URL');
    const budget = screen.getByLabelText('Maximum description attempts');
    const recognition = screen.getByLabelText('Identify people in photos');
    const names = screen.getByLabelText('Include named people in descriptions');
    const context = document.getElementById(`acx-settings-context-category-${CONTEXT_CATEGORIES[0]}`)!;
    const urlA = 'https://review-a.example.com';
    const urlB = 'https://review-b.example.com';
    type(url, urlA); type(budget, '4'); fireEvent.click(recognition); fireEvent.click(context);
    fireEvent.click(screen.getByRole('button', { name: 'Save Settings' })); await flush();
    fireEvent.click(recognition); fireEvent.click(names); type(budget, '7');
    h.persist({ ...defaultSettings, url: urlA, effective_target_url: urlA, recognition_enabled: false });
    await finish(h.requests[0], { saved: ['url', 'recognition_enabled'], failed: ['description_budget', 'context_categories'], result: 'partial' });
    expect(recognition).toBeChecked(); expect(names).not.toBeChecked();
    expect(budget).toHaveValue(7); expect(context).not.toBeChecked();
    type(url, urlB); fireEvent.blur(url); await flush();
    h.persist({ ...defaultSettings, url: urlB, effective_target_url: urlB, recognition_enabled: false });
    await finish(h.requests[1], { saved: ['url'], result: 'ok' });
    expect(recognition).toBeChecked(); expect(names).not.toBeChecked();
    expect(budget).toHaveValue(7); expect(context).not.toBeChecked();
    fireEvent.click(screen.getByRole('button', { name: 'Retry save' })); await flush();
    expect(h.requests[2].payload).toEqual({
      description_budget: { max_attempts: 7 }, recognition_enabled: true,
      allow_person_names: false, context_categories: CONTEXT_CATEGORIES.slice(1),
    });
    h.persist({
      ...defaultSettings, url: urlB, effective_target_url: urlB,
      description_budget: { ...defaultSettings.description_budget, max_attempts: 7 },
      recognition_enabled: true, allow_person_names: false, context_categories: CONTEXT_CATEGORIES.slice(1),
    });
    await finish(h.requests[2], { saved: Object.keys(h.requests[2].payload), result: 'ok' });
    expect(screen.queryByText(/Could not save settings/)).not.toBeInTheDocument();
  });

  it('R4-control an unblurred edit cancels a real post-save probe and rejects its stale response', async () => {
    const h = await harness();
    const probe = deferred<TestConnectionResponse>();
    vi.mocked(h.api.testConnection).mockReturnValue(probe.promise);
    const url = screen.getByLabelText('Service API URL');
    const urlA = 'https://review-a.example.com';
    type(url, urlA); fireEvent.blur(url); await flush();
    h.persist({ ...defaultSettings, url: urlA, effective_target_url: urlA });
    await finish(h.requests[0], { saved: ['url'], result: 'ok' });
    expect(h.api.testConnection).toHaveBeenCalledTimes(1);
    const card = screen.getByTestId('acx-target-card-service');
    expect(card).toHaveTextContent('Saved. Checking health…');
    type(url, 'https://review-uncommitted.example.com');
    expect(card).not.toHaveTextContent('Saved. Checking health…');
    await act(async () => { probe.resolve({
      outcome: 'connected', probe_mode: 'service_auth', status_code: 200,
      probed_url: urlA + '/health/detailed',
      body: { status: 'ok', model_cache: { status: 'ok', profile: 'insightface' } },
    }); });
    await flush();
    expect(screen.queryByTestId('acx-test-connection-banner')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Check health' })).toBeEnabled();
    expect(url).toHaveValue('https://review-uncommitted.example.com');
    expect(h.requests).toHaveLength(1);
  });

  it.each(['ok', 'transport', 'partial'] as const)('QCR retains and sends committed B after pending A: %s', async (outcome) => {
    const h = await harness();
    const key = screen.getByLabelText('API Key');
    type(key, 'draft-A'); fireEvent.blur(key); await flush();
    type(key, 'draft-B'); fireEvent.blur(key);
    expect(h.requests).toHaveLength(1);
    expect(screen.getByRole('button', { name: 'Check health' })).toBeEnabled();
    if (outcome === 'transport') { await act(() => Promise.resolve(h.requests[0].reject(new Error('transport failed')))); await flush(); }
    else { await finish(h.requests[0], outcome === 'ok' ? { saved: ['api_key'], result: 'ok' } : { saved: [], failed: ['api_key'], result: 'error' }); }
    expect(key).toHaveValue('draft-B');
    expect(h.requests.map((r) => r.payload)).toEqual([{ api_key: 'draft-A' }, { api_key: 'draft-B' }]);
  });

  it.each(['api_key', 'url'] as const)('QCR retains B across an actual partial response with failed %s', async (failedField) => {
    const h = await harness();
    const key = screen.getByLabelText('API Key');
    const url = screen.getByLabelText('Service API URL');
    const urlA = 'https://partial.example.com';
    type(url, urlA); type(key, 'draft-A'); fireEvent.blur(key); await flush();
    type(key, 'draft-B'); fireEvent.blur(key);
    if (failedField === 'api_key') h.persist({ ...defaultSettings, url: urlA, effective_target_url: urlA });
    await finish(h.requests[0], { saved: [failedField === 'api_key' ? 'url' : 'api_key'], failed: [failedField], result: 'partial' });
    expect(key).toHaveValue('draft-B');
    expect(h.requests[1].payload).toEqual(failedField === 'api_key' ? { api_key: 'draft-B' } : { url: urlA, api_key: 'draft-B' });
    expect(h.api.testConnection).not.toHaveBeenCalled();
  });

  it('QCR does not persist C typed without blur after a queued B blur', async () => {
    const h = await harness();
    const key = screen.getByLabelText('API Key');
    type(key, 'draft-A'); fireEvent.blur(key); await flush();
    type(key, 'draft-B'); fireEvent.blur(key);
    type(key, 'uncommitted-C');
    await finish(h.requests[0], { saved: ['api_key'], result: 'ok' });
    expect(key).toHaveValue('uncommitted-C');
    expect(h.requests.map((r) => r.payload)).toEqual([{ api_key: 'draft-A' }, { api_key: 'draft-B' }]);
  });

  it.each([false, true])('QCR preserves revert to the original URL through A readback, blur=%s', async (blur) => {
    const h = await harness();
    const url = screen.getByLabelText('Service API URL');
    const urlA = 'https://pending.example.com';
    type(url, urlA); fireEvent.blur(url); await flush();
    type(url, defaultSettings.url); if (blur) fireEvent.blur(url);
    h.persist({ ...defaultSettings, url: urlA, effective_target_url: urlA });
    await finish(h.requests[0], { saved: ['url'], result: 'ok' });
    if (blur) {
      expect(h.requests[1].payload).toEqual({ url: defaultSettings.url });
      await act(() => Promise.resolve(h.requests[1].reject(new Error('second write failed')))); await flush();
    }
    expect(url).toHaveValue(defaultSettings.url);
  });

  it('QCR acknowledges committed B without clearing uncommitted C', async () => {
    const h = await harness();
    const key = screen.getByLabelText('API Key');
    type(key, 'draft-A'); fireEvent.blur(key); await flush();
    type(key, 'draft-B'); fireEvent.blur(key);
    type(key, 'uncommitted-C');
    await finish(h.requests[0], { saved: ['api_key'], result: 'ok' });
    await finish(h.requests[1], { saved: ['api_key'], result: 'ok' });
    expect(key).toHaveValue('uncommitted-C');
    expect(h.requests.map((r) => r.payload)).toEqual([{ api_key: 'draft-A' }, { api_key: 'draft-B' }]);
  });

  it('QCR keeps a newer same-value secret edit after the original acknowledgement', async () => {
    const h = await harness();
    const key = screen.getByLabelText('API Key');
    type(key, 'draft-A'); fireEvent.blur(key); await flush();
    type(key, 'draft-B');
    type(key, 'draft-A');
    await finish(h.requests[0], { saved: ['api_key'], result: 'ok' });
    expect(key).toHaveValue('draft-A');
    expect(h.requests).toHaveLength(1);
  });

  it('QCR sends committed URL B while retaining uncommitted C through both readbacks', async () => {
    const h = await harness();
    const url = screen.getByLabelText('Service API URL');
    const urlA = 'https://pending.example.com';
    const urlB = 'https://committed.example.com';
    const urlC = 'https://typing.example.com';
    type(url, urlA); fireEvent.blur(url); await flush();
    type(url, urlB); fireEvent.blur(url);
    type(url, urlC);
    h.persist({ ...defaultSettings, url: urlA, effective_target_url: urlA });
    await finish(h.requests[0], { saved: ['url'], result: 'ok' });
    expect(h.requests.map((r) => r.payload)).toEqual([{ url: urlA }, { url: urlB }]);
    h.persist({ ...defaultSettings, url: urlB, effective_target_url: urlB });
    await finish(h.requests[1], { saved: ['url'], result: 'ok' });
    expect(url).toHaveValue(urlC);
    expect(h.requests).toHaveLength(2);
  });

  it('QCR does not resend acknowledged A when persisted readback fails', async () => {
    const h = await harness();
    const key = screen.getByLabelText('API Key');
    type(key, 'draft-A'); fireEvent.blur(key); await flush();
    type(screen.getByLabelText('Maximum description attempts'), '4');
    fireEvent.submit(screen.getByRole('button', { name: 'Saving…' }).closest('form')!);
    vi.mocked(h.api.fetchSettings).mockRejectedValue(new Error('readback unavailable'));
    await finish(h.requests[0], { saved: ['api_key'], result: 'ok' });
    expect(key).toHaveValue('');
    expect(h.api.testConnection).not.toHaveBeenCalled();
    expect(h.requests.map((r) => r.payload)).toEqual([{ api_key: 'draft-A' }, { description_budget: { max_attempts: 4 } }]);
  });

  it('QCR empty newer key cancels the replacement without clearing persisted credentials', async () => {
    const h = await harness();
    const key = screen.getByLabelText('API Key');
    type(key, 'draft-A'); fireEvent.blur(key); await flush();
    type(key, 'draft-B'); fireEvent.blur(key);
    type(key, ''); fireEvent.blur(key);
    await finish(h.requests[0], { saved: ['api_key'], result: 'ok' });
    expect(key).toHaveValue('');
    expect(h.requests).toHaveLength(1);
  });

  it('QCR repeated pending key values are written once and cleared after acknowledgement', async () => {
    const h = await harness();
    const key = screen.getByLabelText('API Key');
    type(key, 'draft-A'); fireEvent.blur(key); await flush();
    fireEvent.blur(key);
    await finish(h.requests[0], { saved: ['api_key'], result: 'ok' });
    expect(key).toHaveValue('');
    expect(h.requests).toHaveLength(1);
  });

  it('QCR an unrelated setting save retains an unblurred newer secret without submitting it', async () => {
    const h = await harness();
    type(screen.getByLabelText('Maximum description attempts'), '4');
    fireEvent.click(screen.getByRole('button', { name: 'Save Settings' })); await flush();
    const key = screen.getByLabelText('API Key'); type(key, 'uncommitted-B');
    h.persist({ ...defaultSettings, description_budget: { ...defaultSettings.description_budget, max_attempts: 4 } });
    await finish(h.requests[0], { saved: ['description_budget'], result: 'ok' });
    expect(key).toHaveValue('uncommitted-B');
    expect(h.requests.map((r) => r.payload)).toEqual([{ description_budget: { max_attempts: 4 } }]);
    expect(h.api.testConnection).not.toHaveBeenCalled();
  });

  it('QCR health intent waits while persisted readback is deferred', async () => {
    const h = await harness();
    const urlA = 'https://pending.example.com';
    const url = screen.getByLabelText('Service API URL');
    type(url, urlA); fireEvent.click(screen.getByRole('button', { name: 'Check health' })); await flush();
    const readback = deferred<SettingsResponse>();
    vi.mocked(h.api.fetchSettings).mockReturnValue(readback.promise);
    await finish(h.requests[0], { saved: ['url'], result: 'ok' });
    expect(h.api.testConnection).not.toHaveBeenCalled();
    expect(screen.getByRole('button', { name: 'Check health' })).toBeEnabled();
    await act(() => Promise.resolve(readback.resolve({ ...defaultSettings, url: urlA, effective_target_url: urlA }))); await flush();
    expect(h.api.testConnection).toHaveBeenCalledTimes(1);
  });
  it('QR2 keeps queued full-form fields when later routing commits replace the credentials', async () => {
    const h = await harness();
    const key = screen.getByLabelText('API Key');
    const budget = screen.getByLabelText('Maximum description attempts');
    type(key, 'probe-A'); fireEvent.blur(key); await flush();
    type(budget, '4');
    fireEvent.submit(key.closest('form')!);
    type(budget, '9');
    type(key, 'probe-B'); fireEvent.keyDown(key, { key: 'Enter' });
    type(key, 'probe-C');
    await finish(h.requests[0], { saved: ['api_key'], result: 'ok' });
    expect(h.requests.map(r => r.payload)).toEqual([
      { api_key: 'probe-A' }, { api_key: 'probe-B', description_budget: { max_attempts: 4 } },
    ]);
    h.persist({ ...defaultSettings, description_budget: { ...defaultSettings.description_budget, max_attempts: 4 } });
    await finish(h.requests[1], { saved: ['description_budget'], failed: ['api_key'], result: 'partial' });
    expect(key).toHaveValue('probe-C');
    expect(h.requests).toHaveLength(2);
    fireEvent.blur(key); await flush();
    expect(h.requests[2].payload).toEqual({ api_key: 'probe-C' });
  });

  it('QR2 drains the latest committed transition through readback error then retries the newer draft', async () => {
    const h = await harness(); const key = screen.getByLabelText('API Key');
    type(key, 'probe-A'); fireEvent.blur(key); await flush();
    type(key, 'probe-B'); fireEvent.blur(key);
    type(key, 'probe-D'); fireEvent.blur(key);
    type(key, 'probe-C');
    vi.mocked(h.api.fetchSettings).mockRejectedValue(new Error('probe readback failure'));
    await finish(h.requests[0], { saved: ['api_key'], result: 'ok' });
    expect(h.requests.map(r => r.payload)).toEqual([{ api_key: 'probe-A' }, { api_key: 'probe-D' }]);
    expect(key).toHaveValue('probe-C');
    expect(h.api.testConnection).not.toHaveBeenCalled();
    vi.mocked(h.api.fetchSettings).mockResolvedValue(defaultSettings);
    await finish(h.requests[1], { saved: ['api_key'], result: 'ok' });
    expect(key).toHaveValue('probe-C');
    fireEvent.blur(key); await flush();
    await act(async () => {
      h.requests[2].reject(new Error('probe transport failure'));
      await h.requests[2].promise.catch(() => undefined);
    }); await flush();
    expect(key).toHaveValue('probe-C');
    fireEvent.keyDown(key, { key: 'Enter' }); await flush();
    expect(h.requests.map(r => r.payload)).toEqual([
      { api_key: 'probe-A' }, { api_key: 'probe-D' }, { api_key: 'probe-C' }, { api_key: 'probe-C' },
    ]);
  });

  it('QR2 distinguishes a committed A-B-A key edit from repeated blur after acknowledgement and readback failure', async () => {
    const h = await harness(); const key = screen.getByLabelText('API Key');
    type(key, 'probe-A'); fireEvent.blur(key); await flush();
    type(key, 'probe-B'); fireEvent.blur(key);
    type(key, 'probe-A'); fireEvent.blur(key);
    vi.mocked(h.api.fetchSettings).mockRejectedValue(new Error('probe readback failure'));
    await finish(h.requests[0], { saved: ['api_key'], result: 'ok' });
    expect(key).toHaveValue('probe-A');
    expect(h.requests.map(r => r.payload)).toEqual([{ api_key: 'probe-A' }, { api_key: 'probe-A' }]);
    vi.mocked(h.api.fetchSettings).mockResolvedValue(defaultSettings);
    await finish(h.requests[1], { saved: ['api_key'], result: 'ok' });
    expect(key).toHaveValue('');
    expect(h.requests).toHaveLength(2);
  });

  it('QR2 preserves edits committed during a deferred partial readback and later uncommitted input', async () => {
    const h = await harness(); const key = screen.getByLabelText('API Key'); const url = screen.getByLabelText('Service API URL');
    const urlA = 'https://probe-a.example.com'; const urlC = 'https://probe-c.example.com';
    type(url, urlA); type(key, 'probe-A'); fireEvent.blur(key); await flush();
    const readback = deferred<SettingsResponse>();
    vi.mocked(h.api.fetchSettings).mockReturnValue(readback.promise);
    await finish(h.requests[0], { saved: ['api_key'], failed: ['url'], result: 'partial' });
    expect(key).toHaveValue('');
    type(key, 'probe-B'); fireEvent.keyDown(key, { key: 'Enter' });
    type(key, 'probe-C'); type(url, urlC);
    await act(async () => { readback.resolve(defaultSettings); await readback.promise; }); await flush();
    expect(h.requests[1].payload).toEqual({ url: urlA, api_key: 'probe-B' });
    expect(url).toHaveValue(urlC); expect(key).toHaveValue('probe-C');
    vi.mocked(h.api.fetchSettings).mockResolvedValue({ ...defaultSettings, url: urlA, effective_target_url: urlA });
    await finish(h.requests[1], { saved: ['url'], failed: ['api_key'], result: 'partial' });
    expect(url).toHaveValue(urlC); expect(key).toHaveValue('probe-C');
    expect(h.api.testConnection).not.toHaveBeenCalled();
  });

  it('QR2 preserves a same-value URL transition during delayed query effects and later failed retry', async () => {
    const h = await harness(); const url = screen.getByLabelText('Service API URL');
    const urlA = 'https://probe-a.example.com'; const urlB = 'https://probe-b.example.com';
    type(url, urlA); fireEvent.blur(url); await flush();
    const readback = deferred<SettingsResponse>();
    vi.mocked(h.api.fetchSettings).mockReturnValue(readback.promise);
    await finish(h.requests[0], { saved: ['url'], result: 'ok' });
    type(url, urlB); type(url, urlA); fireEvent.blur(url);
    await act(async () => { readback.resolve({ ...defaultSettings, url: urlA, effective_target_url: urlA }); await readback.promise; }); await flush();
    expect(url).toHaveValue(urlA); expect(h.requests).toHaveLength(1);
    // A new edit after that no-op commit must also survive an external query publication.
    type(url, defaultSettings.url);
    vi.mocked(h.api.fetchSettings).mockResolvedValue({ ...defaultSettings, url: urlB, effective_target_url: urlB });
    await act(async () => { await h.client.invalidateQueries({ queryKey: queryKeys.settings.all }); }); await flush();
    expect(screen.getByTestId('acx-effective-routing')).toHaveTextContent(urlB);
    expect(url).toHaveValue(defaultSettings.url);
    fireEvent.blur(url); await flush();
    expect(h.requests[1].payload).toEqual({ url: defaultSettings.url });
    await act(async () => {
      h.requests[1].reject(new Error('probe retry failure'));
      await h.requests[1].promise.catch(() => undefined);
    }); await flush();
    expect(url).toHaveValue(defaultSettings.url);
  });

  it('QR2 URL and key acknowledgement followed by failed readback retains a newer draft and queued unrelated fields', async () => {
    const h = await harness(); const key = screen.getByLabelText('API Key'); const url = screen.getByLabelText('Service API URL');
    const urlA = 'https://probe-a.example.com'; const urlC = 'https://probe-c.example.com';
    type(url, urlA); type(key, 'probe-A'); fireEvent.blur(key); await flush();
    type(screen.getByLabelText('Maximum description attempts'), '4'); fireEvent.submit(key.closest('form')!);
    type(url, urlC); type(key, 'probe-C');
    vi.mocked(h.api.fetchSettings).mockRejectedValue(new Error('probe readback failure'));
    await finish(h.requests[0], { saved: ['url', 'api_key'], result: 'ok' });
    expect(url).toHaveValue(urlC); expect(key).toHaveValue('probe-C');
    // The queue drains against the acknowledged URL A, so A is not resent (gate1 F1).
    expect(h.requests[1].payload).toEqual({ description_budget: { max_attempts: 4 } });
    expect(h.api.testConnection).not.toHaveBeenCalled();
  });

  it('QR2 no-op committed URL revision follows a later persisted URL update', async () => {
    const h = await harness(defaultSettings, 0); const url = screen.getByLabelText('Service API URL');
    const transient = 'https://probe-transient.example.com'; const external = 'https://probe-external.example.com';
    type(url, transient); type(url, defaultSettings.url); fireEvent.blur(url); await flush();
    expect(h.requests).toHaveLength(0);
    expect(url).toHaveValue(defaultSettings.url);
    h.persist({ ...defaultSettings, url: external, effective_target_url: external });
    await act(async () => { await h.client.invalidateQueries({ queryKey: queryKeys.settings.all }); }); await flush();
    expect(screen.getByTestId('acx-effective-routing')).toHaveTextContent(external);
    expect(url).toHaveValue(external);
  });

  it('QR2 no-op committed URL must not be resubmitted by a later key save after persisted routing changes', async () => {
    const h = await harness(defaultSettings, 0); const url = screen.getByLabelText('Service API URL'); const key = screen.getByLabelText('API Key');
    type(url, 'https://probe-transient.example.com'); type(url, defaultSettings.url); fireEvent.blur(url); await flush();
    expect(h.requests).toHaveLength(0);
    const external = 'https://probe-external.example.com';
    type(screen.getByLabelText('Maximum description attempts'), '4');
    fireEvent.click(screen.getByRole('button', { name: 'Save Settings' })); await flush();
    expect(h.requests[0].payload).toEqual({ description_budget: { max_attempts: 4 } });
    h.persist({ ...defaultSettings, url: external, effective_target_url: external, description_budget: { ...defaultSettings.description_budget, max_attempts: 4 } });
    await finish(h.requests[0], { saved: ['description_budget'], result: 'ok' });
    expect(screen.getByTestId('acx-effective-routing')).toHaveTextContent(external);
    type(key, 'probe-key'); fireEvent.blur(key); await flush();
    expect(h.requests[1].payload).toEqual({ api_key: 'probe-key' });
  });

  it.each([false, true])('C3 full-form commit retires only its satisfied URL, budget change=%s', async (changeBudget) => {
    const h = await harness(defaultSettings, 0);
    const url = screen.getByLabelText('Service API URL');
    const key = screen.getByLabelText('API Key');
    const external = 'https://probe-external.example.com';
    type(url, 'https://probe-transient.example.com');
    type(url, defaultSettings.url);
    if (changeBudget) type(screen.getByLabelText('Maximum description attempts'), '4');
    fireEvent.submit(url.closest('form')!);
    await flush();
    const persisted = {
      ...defaultSettings, url: external, effective_target_url: external,
      description_budget: { ...defaultSettings.description_budget, max_attempts: changeBudget ? 4 : defaultSettings.description_budget.max_attempts },
    };
    h.persist(persisted);
    if (changeBudget) {
      expect(h.requests[0].payload).toEqual({ description_budget: { max_attempts: 4 } });
      await finish(h.requests[0], { saved: ['description_budget'], result: 'ok' });
    } else {
      expect(h.requests).toHaveLength(0);
      await act(async () => { await h.client.invalidateQueries({ queryKey: queryKeys.settings.all }); });
      await flush();
    }
    expect(screen.getByTestId('acx-effective-routing')).toHaveTextContent(external);
    expect(url).toHaveValue(external);
    type(key, 'probe-key');
    fireEvent.blur(key);
    await flush();
    expect(h.requests[changeBudget ? 1 : 0].payload).toEqual({ api_key: 'probe-key' });
  });

  it.each([
    { fullForm: false, newerDraft: false },
    { fullForm: true, newerDraft: false },
    { fullForm: false, newerDraft: true },
    { fullForm: true, newerDraft: true },
  ])('C3 queued no-op retires its committed revision and preserves newer same-value edits: %j', async ({ fullForm, newerDraft }) => {
    const h = await harness(defaultSettings, 0);
    const url = screen.getByLabelText('Service API URL');
    const saved = 'https://probe-saved.example.com';
    const transient = 'https://probe-transient.example.com';
    const external = 'https://probe-external.example.com';
    type(url, saved);
    fireEvent.blur(url);
    await flush();
    type(url, transient);
    type(url, saved);
    if (fullForm) fireEvent.submit(url.closest('form')!);
    else fireEvent.blur(url);
    if (newerDraft) {
      type(url, transient);
      type(url, saved);
    }
    h.persist({ ...defaultSettings, url: saved, effective_target_url: saved });
    await finish(h.requests[0], { saved: ['url'], result: 'ok' });
    expect(h.requests.map(r => r.payload)).toEqual([{ url: saved }]);
    expect(url).toHaveValue(saved);
    h.persist({ ...defaultSettings, url: external, effective_target_url: external });
    await act(async () => { await h.client.invalidateQueries({ queryKey: queryKeys.settings.all }); });
    await flush();
    expect(screen.getByTestId('acx-effective-routing')).toHaveTextContent(external);
    expect(url).toHaveValue(newerDraft ? saved : external);
    expect(h.requests).toHaveLength(1);
  });

  it.each([
    { matchesCommit: true, newerDraft: false },
    { matchesCommit: true, newerDraft: true },
    { matchesCommit: false, newerDraft: false },
  ])('C3 no-op committed during refetch waits for settled data: %j', async ({ matchesCommit, newerDraft }) => {
    const h = await harness(defaultSettings, 0);
    const url = screen.getByLabelText('Service API URL');
    const transient = 'https://probe-transient.example.com';
    const external = 'https://probe-external.example.com';
    const readback = deferred<SettingsResponse>();
    vi.mocked(h.api.fetchSettings).mockReturnValue(readback.promise);
    let refresh!: Promise<void>;
    act(() => { refresh = h.client.invalidateQueries({ queryKey: queryKeys.settings.all }); });
    await flush();
    type(url, transient);
    type(url, defaultSettings.url);
    fireEvent.blur(url);
    if (newerDraft) {
      type(url, transient);
      type(url, defaultSettings.url);
    }
    expect(h.requests).toHaveLength(0);
    await act(async () => {
      readback.resolve(matchesCommit ? defaultSettings : { ...defaultSettings, url: external, effective_target_url: external });
      await refresh;
    });
    await flush();
    vi.mocked(h.api.fetchSettings).mockResolvedValue({ ...defaultSettings, url: external, effective_target_url: external });
    await act(async () => { await h.client.invalidateQueries({ queryKey: queryKeys.settings.all }); });
    await flush();
    expect(screen.getByTestId('acx-effective-routing')).toHaveTextContent(external);
    expect(url).toHaveValue(matchesCommit && !newerDraft ? external : defaultSettings.url);
    expect(h.requests).toHaveLength(0);
  });

  it.each([false, true])('C3 uncertain write needs fresh readback to complete a queued URL restore, satisfied=%s', async (satisfied) => {
    const h = await harness(defaultSettings, 0);
    const url = screen.getByLabelText('Service API URL');
    const pending = 'https://probe-pending.example.com';
    const external = 'https://probe-external.example.com';
    type(url, pending);
    fireEvent.blur(url);
    await flush();
    type(url, defaultSettings.url);
    fireEvent.blur(url);
    await act(async () => {
      h.requests[0].reject(new Error('probe uncertain write outcome'));
      await h.requests[0].promise.catch(() => undefined);
    });
    await flush();
    expect(url).toHaveValue(defaultSettings.url);
    expect(h.requests.map(r => r.payload)).toEqual([{ url: pending }]);
    // The idle cache still contains P from before the rejected A write.
    // Only a subsequent actual read can prove whether the queued P is satisfied.
    fireEvent.blur(url);
    await flush();
    expect(h.requests).toHaveLength(1);
    h.persist(satisfied ? defaultSettings : { ...defaultSettings, url: pending, effective_target_url: pending });
    await act(async () => { await h.client.invalidateQueries({ queryKey: queryKeys.settings.all }); });
    await flush();
    expect(url).toHaveValue(defaultSettings.url);
    h.persist({ ...defaultSettings, url: external, effective_target_url: external });
    await act(async () => { await h.client.invalidateQueries({ queryKey: queryKeys.settings.all }); });
    await flush();
    expect(screen.getByTestId('acx-effective-routing')).toHaveTextContent(external);
    expect(url).toHaveValue(satisfied ? external : defaultSettings.url);
    expect(h.requests).toHaveLength(1);
  });

  // UXREC-1 gate1 timelines: acknowledged writes survive a failed readback.
  it('G1-F1 drains a queued O revert against acknowledged A when readback fails', async () => {
    const h = await harness();
    const url = screen.getByLabelText('Service API URL');
    const urlA = 'https://probe-a.example.com';
    type(url, urlA); fireEvent.blur(url); await flush();
    type(url, defaultSettings.url); fireEvent.blur(url);
    vi.mocked(h.api.fetchSettings).mockRejectedValue(new Error('probe readback failure'));
    await finish(h.requests[0], { saved: ['url'], result: 'ok' });
    expect(h.requests.map((r) => r.payload)).toEqual([{ url: urlA }, { url: defaultSettings.url }]);
    expect(screen.queryByText('All changes are saved.')).not.toBeInTheDocument();
    expect(url).toHaveValue(defaultSettings.url);
    vi.mocked(h.api.fetchSettings).mockResolvedValue(defaultSettings);
    await finish(h.requests[1], { saved: ['url'], result: 'ok' });
    expect(url).toHaveValue(defaultSettings.url);
    expect(h.requests).toHaveLength(2);
  });

  it.each(['partial', 'transport'] as const)('G1-F3 Retry save resends the failed non-routing scope of a mixed save: %s', async (outcome) => {
    const h = await harness();
    const url = screen.getByLabelText('Service API URL');
    const budget = screen.getByLabelText('Maximum description attempts');
    const urlA = 'https://probe-a.example.com';
    type(url, urlA); type(budget, '4');
    fireEvent.click(screen.getByRole('button', { name: 'Save Settings' })); await flush();
    expect(h.requests[0].payload).toEqual({ url: urlA, description_budget: { max_attempts: 4 } });
    if (outcome === 'partial') {
      h.persist({ ...defaultSettings, url: urlA, effective_target_url: urlA });
      await finish(h.requests[0], { saved: ['url'], failed: ['description_budget'], result: 'partial' });
    } else {
      await act(async () => {
        h.requests[0].reject(new Error('probe transport failure'));
        await h.requests[0].promise.catch(() => undefined);
      }); await flush();
    }
    expect(budget).toHaveValue(4);
    const card = screen.getByTestId('acx-target-card-service');
    fireEvent.click(within(card).getByRole('button', { name: 'Retry save' })); await flush();
    expect(h.requests[1]?.payload).toEqual(outcome === 'partial'
      ? { description_budget: { max_attempts: 4 } }
      : { url: urlA, description_budget: { max_attempts: 4 } });
    h.persist({ ...defaultSettings, url: urlA, effective_target_url: urlA,
      description_budget: { ...defaultSettings.description_budget, max_attempts: 4 } });
    await finish(h.requests[1], { saved: Object.keys(h.requests[1].payload), result: 'ok' });
    expect(budget).toHaveValue(4);
    expect(h.requests).toHaveLength(2);
  });

  it('G1-F3 keeps a routing-only retry for a later failed autosave', async () => {
    const h = await harness();
    const url = screen.getByLabelText('Service API URL');
    const urlA = 'https://probe-a.example.com';
    const urlB = 'https://probe-b.example.com';
    const reject = async (index: number) => {
      await act(async () => {
        h.requests[index].reject(new Error('probe transport failure'));
        await h.requests[index].promise.catch(() => undefined);
      }); await flush();
    };
    type(url, urlA); type(screen.getByLabelText('Maximum description attempts'), '4');
    fireEvent.click(screen.getByRole('button', { name: 'Save Settings' })); await flush();
    await reject(0);
    type(url, urlB); fireEvent.blur(url); await flush();
    expect(h.requests[1].payload).toEqual({ url: urlB });
    await reject(1);
    const card = screen.getByTestId('acx-target-card-service');
    fireEvent.click(within(card).getByRole('button', { name: 'Retry save' })); await flush();
    expect(h.requests[2]?.payload).toEqual({ url: urlB });
  });

  it('G1-F4 drains queued key B after a failed A readback so a later C is written last', async () => {
    const h = await harness();
    const key = screen.getByLabelText('API Key');
    type(key, 'probe-A'); fireEvent.blur(key); await flush();
    type(key, 'probe-B'); fireEvent.blur(key);
    vi.mocked(h.api.fetchSettings).mockRejectedValue(new Error('probe readback failure'));
    await finish(h.requests[0], { saved: [], failed: ['api_key'], result: 'error' });
    vi.mocked(h.api.fetchSettings).mockResolvedValue(defaultSettings);
    type(key, 'probe-C'); fireEvent.blur(key); await flush();
    await finish(h.requests[1], { saved: ['api_key'], result: 'ok' });
    await finish(h.requests[2], { saved: ['api_key'], result: 'ok' });
    expect(h.requests.map((r) => r.payload)).toEqual([
      { api_key: 'probe-A' }, { api_key: 'probe-B' }, { api_key: 'probe-C' },
    ]);
    expect(key).toHaveValue('');
  });
  it('G2-F1 queued mixed partial retry preserves the actual submitted budget', async () => {
    const h = await harness();
    const url = screen.getByLabelText('Service API URL');
    const budget = screen.getByLabelText('Maximum description attempts');
    const urlA = 'https://queued-a.example.com';
    const urlB = 'https://queued-b.example.com';
    type(budget, '4');
    type(url, urlA); fireEvent.blur(url); await flush();
    fireEvent.submit(url.closest('form')!);
    type(url, urlB); fireEvent.blur(url);
    h.persist({ ...defaultSettings, url: urlA, effective_target_url: urlA });
    await finish(h.requests[0], { saved: ['url'], result: 'ok' });
    expect(h.requests[1].payload).toEqual({ url: urlB, description_budget: { max_attempts: 4 } });
    h.persist({ ...defaultSettings, url: urlB, effective_target_url: urlB });
    await finish(h.requests[1], { saved: ['url'], failed: ['description_budget'], result: 'partial' });
    fireEvent.click(screen.getByRole('button', { name: 'Retry save' })); await flush();
    expect(budget).toHaveValue(4);
    expect(h.requests[2]?.payload).toEqual({ description_budget: { max_attempts: 4 } });
    h.persist({ ...defaultSettings, url: urlB, effective_target_url: urlB,
      description_budget: { ...defaultSettings.description_budget, max_attempts: 4 } });
    await finish(h.requests[2], { saved: ['description_budget'], result: 'ok' });
    expect(budget).toHaveValue(4);
    expect(h.requests).toHaveLength(3);
  });

  it('G2-F1 queued mixed transport failure retries the actual submitted budget', async () => {
    const h = await harness();
    const url = screen.getByLabelText('Service API URL');
    const budget = screen.getByLabelText('Maximum description attempts');
    const urlA = 'https://queued-a.example.com';
    const urlB = 'https://queued-b.example.com';
    type(budget, '4');
    type(url, urlA); fireEvent.blur(url); await flush();
    fireEvent.submit(url.closest('form')!);
    type(url, urlB); fireEvent.blur(url);
    h.persist({ ...defaultSettings, url: urlA, effective_target_url: urlA });
    await finish(h.requests[0], { saved: ['url'], result: 'ok' });
    expect(h.requests[1].payload).toEqual({ url: urlB, description_budget: { max_attempts: 4 } });
    await act(async () => {
      h.requests[1].reject(new Error('queued mixed transport failure'));
      await h.requests[1].promise.catch(() => undefined);
    }); await flush();
    fireEvent.click(screen.getByRole('button', { name: 'Retry save' })); await flush();
    expect(budget).toHaveValue(4);
    expect(h.requests[2]?.payload).toEqual({ url: urlB, description_budget: { max_attempts: 4 } });
  });

  it.each(['before-first-readback', 'during-second-write', 'during-failed-readback'] as const)(
    'G2-F1 queued mixed failure keeps a newer budget edit: %s', async (when) => {
      const h = await harness();
      const url = screen.getByLabelText('Service API URL');
      const budget = screen.getByLabelText('Maximum description attempts');
      const urlA = 'https://queued-a.example.com';
      const urlB = 'https://queued-b.example.com';
      type(budget, '4');
      type(url, urlA); fireEvent.blur(url); await flush();
      fireEvent.submit(url.closest('form')!);
      type(url, urlB); fireEvent.blur(url);
      if (when === 'before-first-readback') type(budget, '7');
      h.persist({ ...defaultSettings, url: urlA, effective_target_url: urlA });
      await finish(h.requests[0], { saved: ['url'], result: 'ok' });
      expect(h.requests[1].payload).toEqual({ url: urlB, description_budget: { max_attempts: 4 } });
      if (when === 'during-second-write') type(budget, '7');
      const persisted = { ...defaultSettings, url: urlB, effective_target_url: urlB };
      h.persist(persisted);
      const readback = deferred<SettingsResponse>();
      if (when === 'during-failed-readback') vi.mocked(h.api.fetchSettings).mockReturnValue(readback.promise);
      await finish(h.requests[1], { saved: ['url'], failed: ['description_budget'], result: 'partial' });
      if (when === 'during-failed-readback') {
        type(budget, '7');
        await act(async () => { readback.resolve(persisted); }); await flush();
      }
      expect(budget).toHaveValue(7);
      expect(h.requests).toHaveLength(2);
      fireEvent.click(screen.getByRole('button', { name: 'Retry save' })); await flush();
      expect(h.requests[2]?.payload).toEqual({ description_budget: { max_attempts: 7 } });
    },
  );

  it('G2-F1 queued mixed partial retry keeps submitted recognition and context choices', async () => {
    const h = await harness();
    const url = screen.getByLabelText('Service API URL');
    const recognition = screen.getByLabelText('Identify people in photos');
    const names = screen.getByLabelText('Include named people in descriptions');
    const context = document.getElementById(`acx-settings-context-category-${CONTEXT_CATEGORIES[0]}`)!;
    const categories = CONTEXT_CATEGORIES.slice(1);
    fireEvent.click(recognition); fireEvent.click(names); fireEvent.click(context);
    const urlA = 'https://queued-a.example.com';
    const urlB = 'https://queued-b.example.com';
    type(url, urlA); fireEvent.blur(url); await flush();
    fireEvent.submit(url.closest('form')!);
    type(url, urlB); fireEvent.blur(url);
    h.persist({ ...defaultSettings, url: urlA, effective_target_url: urlA });
    await finish(h.requests[0], { saved: ['url'], result: 'ok' });
    const failed = { recognition_enabled: false, allow_person_names: false, context_categories: categories };
    expect(h.requests[1].payload).toEqual({ url: urlB, ...failed });
    h.persist({ ...defaultSettings, url: urlB, effective_target_url: urlB });
    await finish(h.requests[1], { saved: ['url'], failed: Object.keys(failed), result: 'partial' });
    expect(recognition).not.toBeChecked();
    expect(names).not.toBeChecked();
    expect(context).not.toBeChecked();
    fireEvent.click(screen.getByRole('button', { name: 'Retry save' })); await flush();
    expect(h.requests[2]?.payload).toEqual(failed);
  });

  it('G2-F2 empty routing drain preserves mixed partial feedback and Retry save', async () => {
    const h = await harness();
    const key = screen.getByLabelText('API Key');
    type(key, 'acknowledged-key'); fireEvent.blur(key); await flush();
    await finish(h.requests[0], { saved: ['api_key'], result: 'ok' });
    const url = screen.getByLabelText('Service API URL');
    const budget = screen.getByLabelText('Maximum description attempts');
    const urlA = 'https://partial.example.com';
    type(url, urlA); type(budget, '4');
    fireEvent.click(screen.getByRole('button', { name: 'Save Settings' })); await flush();
    fireEvent.blur(url);
    h.persist({ ...defaultSettings, url: urlA, effective_target_url: urlA });
    await finish(h.requests[1], { saved: ['url'], failed: ['description_budget'], result: 'partial' });
    expect(budget).toHaveValue(4);
    expect(h.requests).toHaveLength(2);
    expect(screen.queryByText('All changes are saved.')).not.toBeInTheDocument();
    const card = screen.getByTestId('acx-target-card-service');
    expect(within(card).getByText('Could not save settings. (description_budget)')).toBeInTheDocument();
    fireEvent.click(within(card).getByRole('button', { name: 'Retry save' })); await flush();
    expect(h.requests[2]?.payload).toEqual({ description_budget: { max_attempts: 4 } });
    h.persist({ ...defaultSettings, url: urlA, effective_target_url: urlA,
      description_budget: { ...defaultSettings.description_budget, max_attempts: 4 } });
    await finish(h.requests[2], { saved: ['description_budget'], result: 'ok' });
    expect(screen.queryByText(/Could not save settings/)).not.toBeInTheDocument();
    expect(h.requests).toHaveLength(3);
  });

  // UXREC-1 gate3: failed or pending non-routing intent outlives every later
  // routing write and readback until a write acknowledges it or a newer edit replaces it.
  const budgetSettings = (url: string, maxAttempts: number): SettingsResponse => ({
    ...defaultSettings, url, effective_target_url: url,
    description_budget: { ...defaultSettings.description_budget, max_attempts: maxAttempts },
  });
  const rejectRequest = async (request: { reject: (error: Error) => void; promise: Promise<unknown> }) => {
    await act(async () => {
      request.reject(new Error('probe transport failure'));
      await request.promise.catch(() => undefined);
    }); await flush();
  };

  it.each(['4', '7'] as const)('G3-F1 queued routing C after an O-A-B mixed partial keeps failed budget %s and whole-form Retry', async (latest) => {
    const h = await harness();
    const url = screen.getByLabelText('Service API URL');
    const budget = screen.getByLabelText('Maximum description attempts');
    const urlA = 'https://probe-a.example.com';
    const urlB = 'https://probe-b.example.com';
    const urlC = 'https://probe-c.example.com';
    type(budget, '4');
    type(url, urlA); fireEvent.blur(url); await flush();
    fireEvent.click(screen.getByRole('button', { name: 'Saving…' }));
    type(url, urlB); fireEvent.blur(url);
    h.persist(budgetSettings(urlA, -1));
    await finish(h.requests[0], { saved: ['url'], result: 'ok' });
    expect(h.requests[1].payload).toEqual({ url: urlB, description_budget: { max_attempts: 4 } });
    type(url, urlC); fireEvent.blur(url);
    if (latest === '7') type(budget, '7');
    h.persist(budgetSettings(urlB, -1));
    await finish(h.requests[1], { saved: ['url'], failed: ['description_budget'], result: 'partial' });
    expect(budget).toHaveValue(Number(latest));
    expect(h.requests[2].payload).toEqual({ url: urlC });
    const probesBeforeC = vi.mocked(h.api.testConnection).mock.calls.length;
    h.persist(budgetSettings(urlC, -1));
    await finish(h.requests[2], { saved: ['url'], result: 'ok' });
    // C still gets a fresh health check, but its success cannot erase the budget failure.
    expect(vi.mocked(h.api.testConnection).mock.calls.length).toBeGreaterThan(probesBeforeC);
    expect(budget).toHaveValue(Number(latest));
    const card = screen.getByTestId('acx-target-card-service');
    expect(within(card).getByText('Could not save settings. (description_budget)')).toBeInTheDocument();
    fireEvent.click(within(card).getByRole('button', { name: 'Retry save' })); await flush();
    expect(h.requests[3]?.payload).toEqual({ description_budget: { max_attempts: Number(latest) } });
    h.persist(budgetSettings(urlC, Number(latest)));
    await finish(h.requests[3], { saved: ['description_budget'], result: 'ok' });
    expect(budget).toHaveValue(Number(latest));
    expect(screen.queryByText(/Could not save settings/)).not.toBeInTheDocument();
    expect(screen.getByText('Settings saved.')).toBeInTheDocument();
    expect(h.requests).toHaveLength(4);
  });

  it('G3-F1 direct mixed partial A+4 then queued routing B success keeps the failed budget and Retry', async () => {
    const h = await harness();
    const url = screen.getByLabelText('Service API URL');
    const budget = screen.getByLabelText('Maximum description attempts');
    const urlA = 'https://probe-a.example.com';
    const urlB = 'https://probe-b.example.com';
    type(url, urlA); type(budget, '4');
    fireEvent.submit(url.closest('form')!); await flush();
    expect(h.requests[0].payload).toEqual({ url: urlA, description_budget: { max_attempts: 4 } });
    type(url, urlB); fireEvent.blur(url);
    h.persist(budgetSettings(urlA, -1));
    await finish(h.requests[0], { saved: ['url'], failed: ['description_budget'], result: 'partial' });
    expect(h.requests[1].payload).toEqual({ url: urlB });
    h.persist(budgetSettings(urlB, -1));
    await finish(h.requests[1], { saved: ['url'], result: 'ok' });
    expect(budget).toHaveValue(4);
    const card = screen.getByTestId('acx-target-card-service');
    expect(within(card).getByText('Could not save settings. (description_budget)')).toBeInTheDocument();
    fireEvent.click(within(card).getByRole('button', { name: 'Retry save' })); await flush();
    expect(h.requests[2]?.payload).toEqual({ description_budget: { max_attempts: 4 } });
  });

  it('G3-F1 a later independent routing save keeps its routing-only Retry, then restores the budget failure', async () => {
    const h = await harness();
    const url = screen.getByLabelText('Service API URL');
    const budget = screen.getByLabelText('Maximum description attempts');
    const urlA = 'https://probe-a.example.com';
    const urlB = 'https://probe-b.example.com';
    type(url, urlA); type(budget, '4');
    fireEvent.submit(url.closest('form')!); await flush();
    h.persist(budgetSettings(urlA, -1));
    await finish(h.requests[0], { saved: ['url'], failed: ['description_budget'], result: 'partial' });
    type(url, urlB); fireEvent.blur(url); await flush();
    expect(h.requests[1].payload).toEqual({ url: urlB });
    await rejectRequest(h.requests[1]);
    const card = screen.getByTestId('acx-target-card-service');
    fireEvent.click(within(card).getByRole('button', { name: 'Retry save' })); await flush();
    expect(h.requests[2]?.payload).toEqual({ url: urlB });
    h.persist(budgetSettings(urlB, -1));
    await finish(h.requests[2], { saved: ['url'], result: 'ok' });
    expect(budget).toHaveValue(4);
    expect(within(card).getByText('Could not save settings. (description_budget)')).toBeInTheDocument();
    fireEvent.click(within(card).getByRole('button', { name: 'Retry save' })); await flush();
    expect(h.requests[3]?.payload).toEqual({ description_budget: { max_attempts: 4 } });
  });

  it('G3-F1 direct mixed transport failure keeps Retry after the queued routing B save', async () => {
    const h = await harness();
    const url = screen.getByLabelText('Service API URL');
    const budget = screen.getByLabelText('Maximum description attempts');
    const urlA = 'https://probe-a.example.com';
    const urlB = 'https://probe-b.example.com';
    type(url, urlA); type(budget, '4');
    fireEvent.submit(url.closest('form')!); await flush();
    type(url, urlB); fireEvent.blur(url);
    await rejectRequest(h.requests[0]);
    expect(h.requests[1].payload).toEqual({ url: urlB });
    h.persist(budgetSettings(urlB, -1));
    await finish(h.requests[1], { saved: ['url'], result: 'ok' });
    expect(budget).toHaveValue(4);
    const card = screen.getByTestId('acx-target-card-service');
    expect(within(card).getByText('Could not save settings. (description_budget)')).toBeInTheDocument();
    fireEvent.click(within(card).getByRole('button', { name: 'Retry save' })); await flush();
    expect(h.requests[2]?.payload).toEqual({ description_budget: { max_attempts: 4 } });
  });

  it('G3-F1 Check health with unchanged routing keeps the outstanding failure and Retry', async () => {
    const h = await harness();
    const url = screen.getByLabelText('Service API URL');
    const budget = screen.getByLabelText('Maximum description attempts');
    const urlA = 'https://probe-a.example.com';
    type(url, urlA); type(budget, '4');
    fireEvent.submit(url.closest('form')!); await flush();
    h.persist(budgetSettings(urlA, -1));
    await finish(h.requests[0], { saved: ['url'], failed: ['description_budget'], result: 'partial' });
    vi.mocked(h.api.testConnection).mockClear();
    fireEvent.click(screen.getByRole('button', { name: 'Check health' })); await flush();
    expect(h.api.testConnection).toHaveBeenCalledTimes(1);
    expect(budget).toHaveValue(4);
    const card = screen.getByTestId('acx-target-card-service');
    expect(within(card).getByText('Could not save settings. (description_budget)')).toBeInTheDocument();
    fireEvent.click(within(card).getByRole('button', { name: 'Retry save' })); await flush();
    expect(h.requests[1]?.payload).toEqual({ description_budget: { max_attempts: 4 } });
  });

  it('G3-F2 a newer budget draft typed during an acknowledged budget write survives its readback', async () => {
    const h = await harness();
    const budget = screen.getByLabelText('Maximum description attempts');
    type(budget, '4');
    fireEvent.click(screen.getByRole('button', { name: 'Save Settings' })); await flush();
    type(budget, '7');
    h.persist(budgetSettings(defaultSettings.url, 4));
    await finish(h.requests[0], { saved: ['description_budget'], result: 'ok' });
    expect(budget).toHaveValue(7);
    expect(h.requests).toHaveLength(1);
    fireEvent.click(screen.getByRole('button', { name: 'Save Settings' })); await flush();
    expect(h.requests[1]?.payload).toEqual({ description_budget: { max_attempts: 7 } });
  });

  it('G3-control a committed no-op budget edit follows a later external readback', async () => {
    const h = await harness();
    const budget = screen.getByLabelText('Maximum description attempts');
    type(budget, '4'); type(budget, '-1');
    fireEvent.click(screen.getByRole('button', { name: 'Save Settings' })); await flush();
    expect(screen.getByText('No changes to save.')).toBeInTheDocument();
    h.persist(budgetSettings(defaultSettings.url, 10));
    await act(async () => { await h.client.invalidateQueries({ queryKey: queryKeys.settings.all }); }); await flush();
    expect(budget).toHaveValue(10);
    expect(h.requests).toHaveLength(0);
  });

  it('G3-control an acknowledged budget write follows a later external readback', async () => {
    const h = await harness();
    const budget = screen.getByLabelText('Maximum description attempts');
    type(budget, '4');
    fireEvent.click(screen.getByRole('button', { name: 'Save Settings' })); await flush();
    h.persist(budgetSettings(defaultSettings.url, 4));
    await finish(h.requests[0], { saved: ['description_budget'], result: 'ok' });
    h.persist(budgetSettings(defaultSettings.url, 10));
    await act(async () => { await h.client.invalidateQueries({ queryKey: queryKeys.settings.all }); }); await flush();
    expect(budget).toHaveValue(10);
    expect(h.requests).toHaveLength(1);
  });

  it('G3-F2 repeated global Save without an edit does not reverse the queued budget', async () => {
    const h = await harness();
    const url = screen.getByLabelText('Service API URL');
    const budget = screen.getByLabelText('Maximum description attempts');
    const urlA = 'https://probe-a.example.com';
    type(url, urlA); fireEvent.blur(url); await flush();
    type(budget, '4');
    const save = screen.getByRole('button', { name: 'Saving…' });
    expect(save).toBeEnabled();
    fireEvent.click(save); await flush();
    expect(h.requests.map((r) => r.payload)).toEqual([{ url: urlA }]);
    h.persist(budgetSettings(urlA, -1));
    await finish(h.requests[0], { saved: ['url'], result: 'ok' });
    expect(h.requests[1].payload).toEqual({ description_budget: { max_attempts: 4 } });
    fireEvent.click(screen.getByRole('button', { name: 'Saving…' })); await flush();
    expect(h.requests).toHaveLength(2);
    h.persist(budgetSettings(urlA, 4));
    await finish(h.requests[1], { saved: ['description_budget'], result: 'ok' });
    expect(h.requests.map((r) => r.payload)).toEqual([
      { url: urlA }, { description_budget: { max_attempts: 4 } },
    ]);
    expect(budget).toHaveValue(4);
    expect(screen.getByText('Settings saved.')).toBeInTheDocument();
  });

  it.each([
    ['newer 7', ['7'], 7],
    ['deliberate -1', ['', '-1'], -1],
  ] as const)('G3-control %s typed during the pending budget write is queued as fresh full-form intent', async (_name, edits, expected) => {
    const h = await harness();
    const url = screen.getByLabelText('Service API URL');
    const budget = screen.getByLabelText('Maximum description attempts');
    const urlA = 'https://probe-a.example.com';
    type(url, urlA); fireEvent.blur(url); await flush();
    type(budget, '4');
    fireEvent.click(screen.getByRole('button', { name: 'Saving…' })); await flush();
    h.persist(budgetSettings(urlA, -1));
    await finish(h.requests[0], { saved: ['url'], result: 'ok' });
    expect(h.requests[1].payload).toEqual({ description_budget: { max_attempts: 4 } });
    for (const edit of edits) type(budget, edit);
    fireEvent.click(screen.getByRole('button', { name: 'Saving…' })); await flush();
    expect(h.requests).toHaveLength(2);
    h.persist(budgetSettings(urlA, 4));
    await finish(h.requests[1], { saved: ['description_budget'], result: 'ok' });
    expect(h.requests[2]?.payload).toEqual({ description_budget: { max_attempts: expected } });
    h.persist(budgetSettings(urlA, expected));
    await finish(h.requests[2], { saved: ['description_budget'], result: 'ok' });
    expect(h.requests).toHaveLength(3);
    expect(budget).toHaveValue(expected);
    expect(screen.getByText('Settings saved.')).toBeInTheDocument();
  });

  it('G3-control direct mixed transport failure then queued routing B keeps the budget value', async () => {
    const h = await harness();
    const url = screen.getByLabelText('Service API URL');
    const budget = screen.getByLabelText('Maximum description attempts');
    const urlA = 'https://probe-a.example.com';
    const urlB = 'https://probe-b.example.com';
    type(url, urlA); type(budget, '4');
    fireEvent.submit(url.closest('form')!); await flush();
    type(url, urlB); fireEvent.blur(url);
    await rejectRequest(h.requests[0]);
    expect(h.requests[1].payload).toEqual({ url: urlB });
    h.persist(budgetSettings(urlB, -1));
    await finish(h.requests[1], { saved: ['url'], result: 'ok' });
    expect(budget).toHaveValue(4);
  });

  it('G3-control repeated full submit is serialized and de-duplicated', async () => {
    const h = await harness();
    const url = screen.getByLabelText('Service API URL');
    const urlA = 'https://probe-a.example.com';
    type(url, urlA);
    fireEvent.submit(url.closest('form')!); await flush();
    fireEvent.click(screen.getByRole('button', { name: 'Saving…' })); await flush();
    fireEvent.click(screen.getByRole('button', { name: 'Saving…' })); await flush();
    expect(h.requests).toHaveLength(1);
    h.persist(budgetSettings(urlA, -1));
    await finish(h.requests[0], { saved: ['url'], result: 'ok' });
    expect(h.requests).toHaveLength(1);
    expect(screen.queryByText('Saving…')).not.toBeInTheDocument();
  });

  it('G3-control same-value newer budget edit survives a queued partial snapshot', async () => {
    const h = await harness();
    const url = screen.getByLabelText('Service API URL');
    const budget = screen.getByLabelText('Maximum description attempts');
    const urlA = 'https://probe-a.example.com';
    const urlB = 'https://probe-b.example.com';
    type(budget, '4');
    type(url, urlA); fireEvent.blur(url); await flush();
    fireEvent.submit(url.closest('form')!);
    type(url, urlB); fireEvent.blur(url);
    type(budget, '7'); type(budget, '4');
    h.persist(budgetSettings(urlA, -1));
    await finish(h.requests[0], { saved: ['url'], result: 'ok' });
    h.persist(budgetSettings(urlB, -1));
    await finish(h.requests[1], { saved: ['url'], failed: ['description_budget'], result: 'partial' });
    expect(budget).toHaveValue(4);
    fireEvent.click(screen.getByRole('button', { name: 'Retry save' })); await flush();
    expect(h.requests[2].payload).toEqual({ description_budget: { max_attempts: 4 } });
  });

  it.each(['success', 'failure'] as const)('G3-control empty routing drain after a mixed partial keeps recovery, readback %s', async (readback) => {
    const h = await harness();
    const url = screen.getByLabelText('Service API URL');
    const budget = screen.getByLabelText('Maximum description attempts');
    const urlA = 'https://probe-partial.example.com';
    type(url, urlA); type(budget, '4');
    fireEvent.submit(url.closest('form')!); await flush();
    fireEvent.blur(url);
    h.persist(budgetSettings(urlA, -1));
    if (readback === 'failure') vi.mocked(h.api.fetchSettings).mockRejectedValue(new Error('probe readback failure'));
    await finish(h.requests[0], { saved: ['url'], failed: ['description_budget'], result: 'partial' });
    expect(h.requests).toHaveLength(1);
    expect(budget).toHaveValue(4);
    expect(screen.getByText('Could not save settings. (description_budget)')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Retry save' })); await flush();
    expect(h.requests[1].payload).toEqual({ description_budget: { max_attempts: 4 } });
  });

  it('G3-control queued full transport failure retries a still-newer unsubmitted budget', async () => {
    const h = await harness();
    const url = screen.getByLabelText('Service API URL');
    const budget = screen.getByLabelText('Maximum description attempts');
    const urlA = 'https://probe-a.example.com';
    const urlB = 'https://probe-b.example.com';
    type(budget, '4');
    type(url, urlA); fireEvent.blur(url); await flush();
    fireEvent.submit(url.closest('form')!);
    type(url, urlB); fireEvent.blur(url);
    type(budget, '7');
    h.persist(budgetSettings(urlA, -1));
    await finish(h.requests[0], { saved: ['url'], result: 'ok' });
    expect(h.requests[1].payload).toEqual({ url: urlB, description_budget: { max_attempts: 4 } });
    await rejectRequest(h.requests[1]);
    expect(budget).toHaveValue(7);
    fireEvent.click(screen.getByRole('button', { name: 'Retry save' })); await flush();
    expect(h.requests[2].payload).toEqual({ url: urlB, description_budget: { max_attempts: 7 } });
  });

  it('G3-control unmount clears a scheduled post-save health deadline', async () => {
    const h = await harness();
    const timers = vi.spyOn(globalThis, 'setTimeout');
    const clear = vi.spyOn(globalThis, 'clearTimeout');
    try {
      vi.mocked(h.api.testConnection).mockImplementation(() => new Promise(() => undefined));
      const url = screen.getByLabelText('Service API URL');
      const urlA = 'https://probe-a.example.com';
      type(url, urlA); fireEvent.blur(url); await flush();
      h.persist(budgetSettings(urlA, -1));
      await finish(h.requests[0], { saved: ['url'], result: 'ok' });
      const index = timers.mock.calls.map((args) => args[1]).lastIndexOf(15000);
      expect(index).toBeGreaterThanOrEqual(0);
      const handle: unknown = timers.mock.results[index].value;
      h.view.unmount();
      expect(clear).toHaveBeenCalledWith(handle);
    } finally {
      timers.mockRestore();
      clear.mockRestore();
    }
  });

  // R6 continuations exercise the real QueryClient and deferred API producers.
  it.each(['transport', 'partial'] as const)('R6-F1 a failed budget write still gives accepted health a terminal deadline: %s', async (mode) => {
    const h = await harness();
    const probe = deferred<TestConnectionResponse>();
    vi.mocked(h.api.testConnection).mockReturnValue(probe.promise);
    const timers = vi.spyOn(globalThis, 'setTimeout');
    try {
      await acceptCheckDuringBudgetSave(h);
      const budget = screen.getByLabelText('Maximum description attempts');
      type(budget, '7');
      await settleBudgetWrite(h, h.requests[0], mode);
      expect(h.api.testConnection).toHaveBeenCalledTimes(1);
      expect(vi.mocked(h.api.testConnection).mock.calls[0][0]).toEqual({});
      expect(screen.getByRole('button', { name: 'Checking…' })).toBeDisabled();
      const deadline = timers.mock.calls.filter((args) => args[1] === 15000).at(-1);
      expect(deadline).toBeDefined();
      await act(async () => { (deadline![0] as () => void)(); }); await flush();
      const card = screen.getByTestId('acx-target-card-service');
      expect(card).toHaveTextContent(/Health not checked|health check timed out|Could not check/);
      expect(within(card).getByRole('button', { name: 'Check health' })).toBeEnabled();
      expect(card).toHaveTextContent('Could not save settings. (description_budget)');
      expect(budget).toHaveValue(7);
      expect(screen.queryByText('Saved. Checking health…')).not.toBeInTheDocument();
      await act(async () => {
        probe.resolve({ outcome: 'connected', auth_ok: true, health: { status: 'ok' } } as TestConnectionResponse);
        await probe.promise;
      }); await flush();
      expect(within(card).queryByTestId('acx-test-connection-banner')).not.toBeInTheDocument();
      vi.mocked(h.api.testConnection).mockResolvedValue({ outcome: 'network_error' });
      fireEvent.click(within(card).getByRole('button', { name: 'Check health' })); await flush();
      expect(h.api.testConnection).toHaveBeenCalledTimes(2);
      expect(within(card).getByTestId('acx-test-connection-banner')).toHaveTextContent('Could not reach the recognition service.');
      fireEvent.click(within(card).getByRole('button', { name: 'Retry save' })); await flush();
      expect(h.requests[1].payload).toEqual({ description_budget: { max_attempts: 7 } });
    } finally { timers.mockRestore(); }
  });

  it('R6-F1 real 15.1 second deadline settles health independently of the failed budget Save', async () => {
    const h = await harness();
    const probe = deferred<TestConnectionResponse>();
    vi.mocked(h.api.testConnection).mockReturnValue(probe.promise);
    await acceptCheckDuringBudgetSave(h);
    await settleBudgetWrite(h, h.requests[0], 'transport');
    expect(h.api.testConnection).toHaveBeenCalledTimes(1);
    await act(async () => { await new Promise((resolve) => setTimeout(resolve, 15100)); }); await flush();
    const card = screen.getByTestId('acx-target-card-service');
    expect(card).toHaveTextContent(/Health not checked|health check timed out|Could not check/);
    expect(within(card).getByRole('button', { name: 'Check health' })).toBeEnabled();
    expect(card).toHaveTextContent('Could not save settings. (description_budget)');
    expect(screen.getByLabelText('Maximum description attempts')).toHaveValue(4);
    fireEvent.click(within(card).getByRole('button', { name: 'Retry save' })); await flush();
    expect(h.requests[1].payload).toEqual({ description_budget: { max_attempts: 4 } });
  }, 22000);

  it.each(['url', 'key', 'url-roundtrip', 'key-roundtrip'] as const)('R6-F2 a routing edit revokes deferred Reload health ownership: %s', async (edit) => {
    const h = await harness();
    await acceptCheckDuringBudgetSave(h);
    await settleBudgetWrite(h, h.requests[0], 'partial-readback-error');
    const card = screen.getByTestId('acx-target-card-service');
    expect(card).toHaveTextContent('Health not checked: settings could not reload.');
    const reload = deferred<SettingsResponse>();
    const probe = deferred<TestConnectionResponse>();
    vi.mocked(h.api.fetchSettings).mockReturnValue(reload.promise);
    vi.mocked(h.api.testConnection).mockReturnValue(probe.promise);
    fireEvent.click(within(card).getByRole('button', { name: 'Reload settings' })); await flush();
    expect(h.client.getQueryState(queryKeys.settings.all)?.fetchStatus).toBe('fetching');
    const field = screen.getByLabelText(edit.startsWith('url') ? 'Service API URL' : 'API Key');
    const original = (field as HTMLInputElement).value;
    const newer = edit.startsWith('url') ? 'https://newer-uncommitted.example.com' : 'newer-uncommitted-key';
    type(field, newer);
    if (edit.endsWith('roundtrip')) type(field, original);
    await act(async () => { reload.resolve(defaultSettings); await reload.promise; }); await flush();
    expect(h.api.testConnection).not.toHaveBeenCalled();
    expect(field).toHaveValue(edit.endsWith('roundtrip') ? original : newer);
    expect(screen.getByLabelText('Maximum description attempts')).toHaveValue(4);
    expect(h.client.getQueryState(queryKeys.settings.all)?.status).toBe('success');
    expect(within(card).queryByTestId('acx-settings-reload-warning')).not.toBeInTheDocument();
    expect(card).toHaveTextContent('Could not save settings. (description_budget)');
    expect(h.requests).toHaveLength(1);
  });

  it('R6-F2 old-key health cannot publish after a newer key revoked Reload recovery', async () => {
    const h = await harness();
    await acceptCheckDuringBudgetSave(h);
    await settleBudgetWrite(h, h.requests[0], 'partial-readback-error');
    const card = screen.getByTestId('acx-target-card-service');
    const reload = deferred<SettingsResponse>();
    const probe = deferred<TestConnectionResponse>();
    vi.mocked(h.api.fetchSettings).mockReturnValue(reload.promise);
    vi.mocked(h.api.testConnection).mockReturnValue(probe.promise);
    fireEvent.click(within(card).getByRole('button', { name: 'Reload settings' })); await flush();
    type(screen.getByLabelText('API Key'), 'newer-uncommitted-key');
    await act(async () => { reload.resolve(defaultSettings); await reload.promise; }); await flush();
    await act(async () => {
      probe.resolve({ outcome: 'connected', auth_ok: true, health: { status: 'ok' } } as TestConnectionResponse);
      await probe.promise;
    }); await flush();
    expect(within(card).queryByTestId('acx-test-connection-banner')).not.toBeInTheDocument();
    expect(screen.getByLabelText('API Key')).toHaveValue('newer-uncommitted-key');
    expect(card).toHaveTextContent('Could not save settings. (description_budget)');
    expect(h.requests).toHaveLength(1);
  });

  it('R6-F3 current manual health success retires only the stale health clause after a successful write and failed readback', async () => {
    const h = await harness();
    await acceptCheckDuringBudgetSave(h);
    await settleBudgetWrite(h, h.requests[0], 'ok-readback-error');
    const card = screen.getByTestId('acx-target-card-service');
    expect(card).toHaveTextContent('Health not checked: settings could not reload.');
    expect(h.api.testConnection).not.toHaveBeenCalled();
    vi.mocked(h.api.testConnection).mockResolvedValue({ outcome: 'connected', auth_ok: true, health: { status: 'ok' } } as TestConnectionResponse);
    fireEvent.click(within(card).getByRole('button', { name: 'Check health' })); await flush();
    expect(h.api.testConnection).toHaveBeenCalledTimes(1);
    expect(within(card).getByTestId('acx-test-connection-banner')).toHaveTextContent('Connection successful.');
    expect(card).not.toHaveTextContent('Health not checked: settings could not reload.');
    expect(screen.getByText('Saved, but the page could not reload settings: settings unavailable.')).toBeInTheDocument();
    expect(screen.getByLabelText('Maximum description attempts')).toHaveValue(4);
    expect(h.requests).toHaveLength(1);
  });

  it('R6-control unrelated budget edits preserve Reload health ownership and real whole-form Retry', async () => {
    const h = await harness();
    await acceptCheckDuringBudgetSave(h);
    await settleBudgetWrite(h, h.requests[0], 'partial-readback-error');
    const card = screen.getByTestId('acx-target-card-service');
    const reload = deferred<SettingsResponse>();
    const probe = deferred<TestConnectionResponse>();
    vi.mocked(h.api.fetchSettings).mockReturnValue(reload.promise);
    vi.mocked(h.api.testConnection).mockReturnValue(probe.promise);
    fireEvent.click(within(card).getByRole('button', { name: 'Reload settings' })); await flush();
    type(screen.getByLabelText('Maximum description attempts'), '7');
    await act(async () => { reload.resolve(defaultSettings); await reload.promise; }); await flush();
    expect(h.api.testConnection).toHaveBeenCalledTimes(1);
    expect(vi.mocked(h.api.testConnection).mock.calls[0][0]).toEqual({});
    await act(async () => {
      probe.resolve({ outcome: 'connected', auth_ok: true, health: { status: 'ok' } } as TestConnectionResponse);
      await probe.promise;
    }); await flush();
    expect(within(card).getByTestId('acx-test-connection-banner')).toHaveTextContent('Connection successful.');
    expect(screen.getByLabelText('Maximum description attempts')).toHaveValue(7);
    expect(card).toHaveTextContent('Could not save settings. (description_budget)');
    fireEvent.click(within(card).getByRole('button', { name: 'Retry save' })); await flush();
    expect(h.requests[1].payload).toEqual({ description_budget: { max_attempts: 7 } });
  });

  it('R6-control an immediate health error leaves a usable Check health and failed-budget Retry', async () => {
    const h = await harness();
    const probe = deferred<TestConnectionResponse>();
    vi.mocked(h.api.testConnection).mockReturnValue(probe.promise);
    await acceptCheckDuringBudgetSave(h);
    await settleBudgetWrite(h, h.requests[0], 'transport');
    expect(h.api.testConnection).toHaveBeenCalledTimes(1);
    await act(async () => { probe.reject(new Error('private health failure')); await probe.promise.catch(() => undefined); }); await flush();
    const card = screen.getByTestId('acx-target-card-service');
    expect(within(card).getByTestId('acx-test-connection-banner')).toHaveTextContent('Could not reach the recognition service.');
    expect(within(card).getByRole('button', { name: 'Check health' })).toBeEnabled();
    expect(card).toHaveTextContent('Could not save settings. (description_budget)');
    expect(screen.queryByText('private health failure')).not.toBeInTheDocument();
    fireEvent.click(within(card).getByRole('button', { name: 'Retry save' })); await flush();
    expect(h.requests[1].payload).toEqual({ description_budget: { max_attempts: 4 } });
  });

  it.each(['transport', 'partial-readback-error', 'ok-readback-error'] as const)('R6-control budget settlement never probes without explicit intent: %s', async (mode) => {
    const h = await harness();
    type(screen.getByLabelText('Maximum description attempts'), '4');
    fireEvent.click(screen.getByRole('button', { name: 'Save Settings' })); await flush();
    await settleBudgetWrite(h, h.requests[0], mode);
    expect(h.api.testConnection).not.toHaveBeenCalled();
    expect(h.requests).toHaveLength(1);
    expect(screen.getByLabelText('Maximum description attempts')).toHaveValue(4);
  });

  it.each(['unknown', 'stopped'] as const)('R6-control dormant health never promotes prior GPU state: %s', async (prior) => {
    const previous = gpuStatusQueryResult.data.gpu_state.state;
    gpuStatusQueryResult.data.gpu_state.state = prior;
    try {
      const h = await harness();
      vi.mocked(h.api.testConnection).mockResolvedValue({ outcome: 'starting', probe_mode: 'service_auth', health: { status: 'dormant' } } as TestConnectionResponse);
      await acceptCheckDuringBudgetSave(h);
      await settleBudgetWrite(h, h.requests[0], 'transport');
      expect(h.api.testConnection).toHaveBeenCalledTimes(1);
      expect(screen.getByText(prior === 'unknown' ? 'Service: not reported' : 'Service: stopped')).toBeInTheDocument();
      expect(screen.queryByText('Service: ready')).not.toBeInTheDocument();
      expect(screen.queryByText(/pool is healthy|GPU online/i)).not.toBeInTheDocument();
      expect(screen.getByTestId('acx-test-connection-banner')).toHaveTextContent('Description service is starting.');
      expect(screen.getByLabelText('Maximum description attempts')).toHaveValue(4);
      expect(screen.getByRole('button', { name: 'Retry save' })).toBeEnabled();
    } finally { gpuStatusQueryResult.data.gpu_state.state = previous; }
  });

  // R5-F1: an accepted Check health settles once the write that carried it settles.
  const PRIVATE_DETAIL = /private (budget write|readback) unavailable/;
  type Harness = Awaited<ReturnType<typeof harness>>;
  const settleBudgetWrite = async (
    h: Harness,
    request: Harness['requests'][number],
    outcome: 'ok' | 'ok-readback-error' | 'transport' | 'partial' | 'partial-readback-error',
    maxAttempts = 4,
  ) => {
    if (outcome === 'transport') {
      await act(async () => {
        request.reject(new Error('private budget write unavailable'));
        await request.promise.catch(() => undefined);
      }); await flush();
      return;
    }
    if (outcome.endsWith('readback-error')) {
      vi.mocked(h.api.fetchSettings).mockRejectedValue(new Error('private readback unavailable'));
    }
    if (outcome.startsWith('ok')) {
      h.persist(budgetSettings(defaultSettings.url, maxAttempts));
      await finish(request, { saved: ['description_budget'], result: 'ok' });
    } else {
      await finish(request, { saved: [], failed: ['description_budget'], result: 'error' });
    }
  };
  const acceptCheckDuringBudgetSave = async (h: Harness) => {
    type(screen.getByLabelText('Maximum description attempts'), '4');
    fireEvent.click(screen.getByRole('button', { name: 'Save Settings' })); await flush();
    const check = screen.getByRole('button', { name: 'Check health' });
    expect(check).toBeEnabled();
    fireEvent.click(check); fireEvent.click(check); await flush();
    expect(h.api.testConnection).not.toHaveBeenCalled();
    expect(h.requests[0].payload).toEqual({ description_budget: { max_attempts: 4 } });
    return check;
  };

  it.each(['transport', 'partial', 'partial-readback-error'] as const)('R5-F1 Check health accepted during a failed budget-only Save settles exactly once: %s', async (mode) => {
    const h = await harness();
    const budget = screen.getByLabelText('Maximum description attempts');
    const check = await acceptCheckDuringBudgetSave(h);
    await settleBudgetWrite(h, h.requests[0], mode);
    const card = screen.getByTestId('acx-target-card-service');
    if (mode === 'partial-readback-error') {
      // No trustworthy readback to bind: a bounded cause and a working recovery.
      expect(h.api.testConnection).not.toHaveBeenCalled();
      const notice = within(card).getByTestId('acx-settings-reload-warning');
      expect(notice).toHaveAttribute('role', 'status');
      expect(notice).toHaveAttribute('aria-live', 'polite');
      expect(notice).toHaveTextContent('Health not checked: settings could not reload.');
      vi.mocked(h.api.fetchSettings).mockResolvedValue(defaultSettings);
      fireEvent.click(within(card).getByRole('button', { name: 'Reload settings' })); await flush();
      expect(within(card).queryByTestId('acx-settings-reload-warning')).not.toBeInTheDocument();
    }
    expect(h.api.testConnection).toHaveBeenCalledTimes(1);
    expect(vi.mocked(h.api.testConnection).mock.calls[0][0]).toEqual({});
    expect(within(card).getByTestId('acx-test-connection-banner')).toBeInTheDocument();
    expect(within(card).getByText('Could not save settings. (description_budget)')).toBeInTheDocument();
    expect(screen.queryByText('Saved. Checking health…')).not.toBeInTheDocument();
    expect(screen.queryByText(PRIVATE_DETAIL)).not.toBeInTheDocument();
    expect(budget).toHaveValue(4);
    expect(h.requests).toHaveLength(1);
    expect(screen.getByRole('button', { name: 'Save Settings' })).toBeEnabled();
    await flush();
    expect(h.api.testConnection).toHaveBeenCalledTimes(1);
    fireEvent.click(check); await flush();
    expect(h.api.testConnection).toHaveBeenCalledTimes(2);
    fireEvent.click(within(card).getByRole('button', { name: 'Retry save' })); await flush();
    expect(h.requests[1].payload).toEqual({ description_budget: { max_attempts: 4 } });
  });

  it('R5-F1 Check health accepted during a budget-only Save reports why it was not checked when the readback fails', async () => {
    const h = await harness();
    const budget = screen.getByLabelText('Maximum description attempts');
    await acceptCheckDuringBudgetSave(h);
    await settleBudgetWrite(h, h.requests[0], 'ok-readback-error');
    const card = screen.getByTestId('acx-target-card-service');
    expect(h.api.testConnection).not.toHaveBeenCalled();
    expect(screen.getByText('Saved, but the page could not reload settings: settings unavailable.')).toBeInTheDocument();
    expect(within(card).getByTestId('acx-settings-reload-warning'))
      .toHaveTextContent('Health not checked: settings could not reload.');
    expect(within(card).getAllByRole('button', { name: 'Reload settings' })).toHaveLength(1);
    expect(screen.queryByText(PRIVATE_DETAIL)).not.toBeInTheDocument();
    expect(budget).toHaveValue(4);
    vi.mocked(h.api.fetchSettings).mockResolvedValue(budgetSettings(defaultSettings.url, 4));
    fireEvent.click(within(card).getByRole('button', { name: 'Reload settings' })); await flush();
    expect(h.api.testConnection).toHaveBeenCalledTimes(1);
    expect(within(card).queryByTestId('acx-settings-reload-warning')).not.toBeInTheDocument();
    expect(budget).toHaveValue(4);
    expect(h.requests).toHaveLength(1);
  });

  it('R5-F1 Check health accepted during a routing save keeps one Reload settings when the readback fails', async () => {
    const h = await harness();
    const url = screen.getByLabelText('Service API URL');
    const urlA = 'https://private-a.example.com';
    type(url, urlA); fireEvent.blur(url); await flush();
    fireEvent.click(screen.getByRole('button', { name: 'Check health' })); await flush();
    h.persist({ ...defaultSettings, url: urlA, effective_target_url: urlA });
    vi.mocked(h.api.fetchSettings).mockRejectedValue(new Error('private readback unavailable'));
    await finish(h.requests[0], { saved: ['url'], result: 'ok' });
    const card = screen.getByTestId('acx-target-card-service');
    expect(h.api.testConnection).not.toHaveBeenCalled();
    expect(within(card).getByTestId('acx-settings-routing-save-message'))
      .toHaveTextContent('Saved, but the page could not reload settings: settings unavailable.');
    expect(within(card).getByTestId('acx-settings-reload-warning'))
      .toHaveTextContent('Health not checked: settings could not reload.');
    expect(within(card).getAllByRole('button', { name: 'Reload settings' })).toHaveLength(1);
    vi.mocked(h.api.fetchSettings).mockResolvedValue({ ...defaultSettings, url: urlA, effective_target_url: urlA });
    fireEvent.click(within(card).getByRole('button', { name: 'Reload settings' })); await flush();
    expect(h.api.testConnection).toHaveBeenCalledTimes(1);
    expect(h.requests).toHaveLength(1);
  });

  it('R5-F1 a budget-only transport failure while settings remain unreadable reports why health was not checked', async () => {
    const h = await harness();
    const budget = screen.getByLabelText('Maximum description attempts');
    type(budget, '4');
    fireEvent.click(screen.getByRole('button', { name: 'Save Settings' })); await flush();
    await settleBudgetWrite(h, h.requests[0], 'partial-readback-error');
    expect(h.client.getQueryState(queryKeys.settings.all)?.status).toBe('error');
    type(budget, '5');
    fireEvent.click(screen.getByRole('button', { name: 'Save Settings' })); await flush();
    fireEvent.click(screen.getByRole('button', { name: 'Check health' })); await flush();
    await settleBudgetWrite(h, h.requests[1], 'transport');
    const card = screen.getByTestId('acx-target-card-service');
    expect(h.api.testConnection).not.toHaveBeenCalled();
    expect(within(card).getByTestId('acx-settings-reload-warning'))
      .toHaveTextContent('Health not checked: settings could not reload.');
    expect(within(card).getByText('Could not save settings. (description_budget)')).toBeInTheDocument();
    expect(budget).toHaveValue(5);
    vi.mocked(h.api.fetchSettings).mockResolvedValue(budgetSettings(defaultSettings.url, 4));
    fireEvent.click(within(card).getByRole('button', { name: 'Reload settings' })); await flush();
    expect(h.api.testConnection).toHaveBeenCalledTimes(1);
    expect(budget).toHaveValue(5);
    expect(h.requests).toHaveLength(2);
  });

  it('R5-control an accepted check never probes a stale target after its routing write fails', async () => {
    const h = await harness();
    const url = screen.getByLabelText('Service API URL');
    const budget = screen.getByLabelText('Maximum description attempts');
    const urlA = 'https://private-a.example.com';
    type(url, urlA); type(budget, '4');
    fireEvent.click(screen.getByRole('button', { name: 'Save Settings' })); await flush();
    fireEvent.click(screen.getByRole('button', { name: 'Check health' })); await flush();
    await settleBudgetWrite(h, h.requests[0], 'transport');
    expect(h.requests[1].payload).toEqual({ url: urlA });
    await settleBudgetWrite(h, h.requests[1], 'transport');
    const card = screen.getByTestId('acx-target-card-service');
    expect(h.api.testConnection).not.toHaveBeenCalled();
    expect(within(card).getByText('Not saved: Failed to save settings. Your edit is kept.')).toBeInTheDocument();
    expect(screen.queryByText(/Health not checked/)).not.toBeInTheDocument();
    expect(screen.queryByText(PRIVATE_DETAIL)).not.toBeInTheDocument();
    expect(url).toHaveValue(urlA);
    expect(budget).toHaveValue(4);
    fireEvent.click(within(card).getByRole('button', { name: 'Retry save' })); await flush();
    expect(h.requests[2].payload).toEqual({ url: urlA });
    h.persist({ ...defaultSettings, url: urlA, effective_target_url: urlA });
    await finish(h.requests[2], { saved: ['url'], result: 'ok' });
    expect(h.api.testConnection).toHaveBeenCalledTimes(1);
    await flush();
    expect(h.api.testConnection).toHaveBeenCalledTimes(1);
    expect(within(card).getByText('Could not save settings. (description_budget)')).toBeInTheDocument();
  });

  it.each(['transport', 'partial-readback-error'] as const)('R5-control a newer budget typed after the accepted check survives the failed write: %s', async (mode) => {
    const h = await harness();
    const budget = screen.getByLabelText('Maximum description attempts');
    await acceptCheckDuringBudgetSave(h);
    type(budget, '7');
    await settleBudgetWrite(h, h.requests[0], mode);
    expect(budget).toHaveValue(7);
    expect(h.requests).toHaveLength(1);
    fireEvent.submit(budget.closest('form')!); await flush();
    expect(h.requests[1].payload).toEqual({ description_budget: { max_attempts: 7 } });
  });

  it.each(['ok', 'transport', 'partial-readback-error'] as const)('R5-control a newer routing edit cancels the accepted check: %s', async (mode) => {
    const h = await harness();
    const url = screen.getByLabelText('Service API URL');
    await acceptCheckDuringBudgetSave(h);
    type(url, 'https://private-newer.example.com');
    await settleBudgetWrite(h, h.requests[0], mode);
    expect(h.api.testConnection).not.toHaveBeenCalled();
    expect(h.requests).toHaveLength(1);
    expect(url).toHaveValue('https://private-newer.example.com');
    expect(screen.queryByText('Saved. Checking health…')).not.toBeInTheDocument();
    expect(screen.queryByText(/Health not checked/)).not.toBeInTheDocument();
  });

  it('R5-control an accepted check carries through a queued later Save and probes once', async () => {
    const h = await harness();
    const budget = screen.getByLabelText('Maximum description attempts');
    await acceptCheckDuringBudgetSave(h);
    type(budget, '7'); fireEvent.submit(budget.closest('form')!); await flush();
    await settleBudgetWrite(h, h.requests[0], 'transport');
    expect(h.requests).toHaveLength(2);
    expect(h.requests[1].payload).toEqual({ description_budget: { max_attempts: 7 } });
    expect(h.api.testConnection).not.toHaveBeenCalled();
    await settleBudgetWrite(h, h.requests[1], 'ok', 7);
    expect(h.api.testConnection).toHaveBeenCalledTimes(1);
    await flush();
    expect(h.api.testConnection).toHaveBeenCalledTimes(1);
    expect(budget).toHaveValue(7);
    expect(screen.queryByText(/Could not save settings/)).not.toBeInTheDocument();
  });

  it.each(['independent', 'queued'] as const)('R5-control reload and Retry preserve a genuine newer budget seven: %s', async (mode) => {
    const h = await harness();
    const url = screen.getByLabelText('Service API URL');
    const budget = screen.getByLabelText('Maximum description attempts');
    const urlA = 'https://private-a.example.com';
    const urlB = 'https://private-b.example.com';
    type(url, urlA); type(budget, '4');
    fireEvent.click(screen.getByRole('button', { name: 'Save Settings' })); await flush();
    if (mode === 'queued') { type(url, urlB); fireEvent.blur(url); await flush(); }
    h.persist({ ...defaultSettings, url: urlA, effective_target_url: urlA });
    await finish(h.requests[0], { saved: ['url'], failed: ['description_budget'], result: 'partial' });
    if (mode === 'independent') { type(url, urlB); fireEvent.blur(url); await flush(); }
    type(budget, '7');
    vi.mocked(h.api.fetchSettings).mockRejectedValue(new Error('private readback unavailable'));
    await finish(h.requests[1], { saved: ['url'], result: 'ok' });
    const card = screen.getByTestId('acx-target-card-service');
    const error = within(card).getByTestId('acx-settings-routing-save-message');
    expect(error).toHaveAttribute('role', 'status');
    expect(error).toHaveAttribute('aria-live', 'polite');
    expect(within(card).getByTestId('acx-settings-reload-warning')).toHaveAttribute('aria-live', 'polite');
    expect(budget).toHaveValue(7);
    const reload = within(card).getByRole('button', { name: 'Reload settings' });
    reload.focus(); expect(reload).toHaveFocus();
    vi.mocked(h.api.fetchSettings).mockResolvedValue({ ...defaultSettings, url: urlB, effective_target_url: urlB });
    fireEvent.click(reload); await flush();
    expect(budget).toHaveValue(7);
    expect(h.requests).toHaveLength(2);
    fireEvent.click(within(card).getByRole('button', { name: 'Retry save' })); await flush();
    expect(h.requests[2].payload).toEqual({ description_budget: { max_attempts: 7 } });
  });
});


describe('QCR further cross-save probes', () => {
  it('QCR never persists a never-blurred secret after an unrelated save and unchanged URL blur', async () => {
    const real = await vi.importActual<typeof import('@tanstack/react-query')>('@tanstack/react-query');
    const api = await import('../../api/settingsApi');
    const client = new QueryClient({ defaultOptions: { queries: { gcTime: Infinity, retry: false, staleTime: Infinity }, mutations: { gcTime: Infinity, retry: false } } });
    client.setQueryData(queryKeys.settings.all, defaultSettings);
    mockQueryClientRef.current = client;
    mockUseQuery.mockImplementation(real.useQuery as never);
    mockUseMutation.mockImplementation(real.useMutation as never);
    vi.mocked(api.fetchSettings).mockResolvedValue({ ...defaultSettings, description_budget: { ...defaultSettings.description_budget, max_attempts: 4 } });
    vi.mocked(api.testConnection).mockResolvedValue({ outcome: 'network_error' });
    let release!: (data: import('../../api/settingsApi').SaveSettingsResponse) => void;
    const first = new Promise<import('../../api/settingsApi').SaveSettingsResponse>((yes) => { release = yes; });
    vi.mocked(api.saveSettings).mockReturnValue(first);
    const view = render(<real.QueryClientProvider client={client}><SettingsPageWithRouter /></real.QueryClientProvider>);
    const flush = async () => { await act(async () => { for (let i = 0; i < 20; i++) await Promise.resolve(); }); };
    try {
      await flush();
      fireEvent.change(screen.getByLabelText('Maximum description attempts'), { target: { value: '4' } });
      fireEvent.click(screen.getByRole('button', { name: 'Save Settings' })); await flush();
      fireEvent.blur(screen.getByLabelText('Service API URL'));
      const key = screen.getByLabelText('API Key');
      fireEvent.change(key, { target: { value: 'still-typing' } });
      vi.mocked(api.saveSettings).mockImplementation(() => new Promise(() => undefined));
      await act(() => Promise.resolve(release({ saved: ['description_budget'], result: 'ok' }))); await flush();
      expect(key).toHaveValue('still-typing');
      expect(vi.mocked(api.saveSettings).mock.calls.map(([payload]) => payload)).toEqual([{ description_budget: { max_attempts: 4 } }]);
    } finally { view.unmount(); client.clear(); }
  });
});
