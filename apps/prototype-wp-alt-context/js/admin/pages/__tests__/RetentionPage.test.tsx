import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { AuthExpiredError, HTTPError } from '../../utils/http';
import { RetentionSection } from '../RetentionPage';
import { retentionReducer, type RetentionDialogState } from '../retention/useRetentionPageState';
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
import type { ExportJobStatusResponse } from '../../api/recognition/types/retention';

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
  sprintf: (format: string, ...args: (string | number)[]) => {
    let sequentialIndex = 0;
    return format.replace(/%((\d+)\$)?[sd]/g, (_match, _positional, explicitIndex) => {
      if (explicitIndex) {
        return String(args[Number(explicitIndex) - 1] ?? '');
      }
      return String(args[sequentialIndex++] ?? '');
    });
  },
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

const toastSuccess = vi.fn();
const toastError = vi.fn();

vi.mock('../../context/ToastContext', () => ({
  useToast: () => ({
    success: toastSuccess,
    error: toastError,
  }),
}));

describe('RetentionSection', () => {
  const ActualBlob = globalThis.Blob;
  const mockedUseRetentionStatus = vi.mocked(useRetentionStatus);
  const mockedUseUpdateRetentionPolicy = vi.mocked(useUpdateRetentionPolicy);
  const mockedUseExportTenantData = vi.mocked(useExportTenantData);
  const mockedUseExportJobStatus = vi.mocked(useExportJobStatus);
  const mockedUseDownloadExportJobData = vi.mocked(useDownloadExportJobData);
  const mockedUsePurgeTenantData = vi.mocked(usePurgeTenantData);
  const mockedUseImportTenantData = vi.mocked(useImportTenantData);
  const mockedUseAuditEvents = vi.mocked(useAuditEvents);
  const mockedUseApplyRetentionPreset = vi.mocked(useApplyRetentionPreset);

  const updateMutateAsync = vi.fn();
  const exportMutateAsync = vi.fn();
  const downloadMutateAsync = vi.fn();
  const purgeMutateAsync = vi.fn();
  const importMutateAsync = vi.fn();
  const presetMutateAsync = vi.fn();
  const refetch = vi.fn();
  const blobPayloads: string[] = [];
  const blobMock = vi.fn(function MockBlob(this: unknown, parts: BlobPart[], options?: BlobPropertyBag) {
    blobPayloads.push(typeof parts[0] === 'string' ? parts[0] : '');
    return new ActualBlob(parts, options);
  });

  beforeEach(() => {
    vi.clearAllMocks();
    blobPayloads.length = 0;
    refetch.mockResolvedValue(undefined);
    updateMutateAsync.mockResolvedValue(undefined);
    exportMutateAsync.mockResolvedValue({ job_id: 'job-1', status: 'pending' });
    downloadMutateAsync.mockResolvedValue({
      tenant_id: 'tenant-1',
      exported_at: '2026-03-12T12:00:00Z',
      schema_version: 1,
      payload: { clusters: [] },
      summary: { clusters: 0 },
    });
    purgeMutateAsync.mockResolvedValue({ deleted_counts: { media_identities: 2 } });

    mockedUseRetentionStatus.mockReturnValue(
      createMockQuery({
        data: {
          available: true,
          policy: {
            retention_mode: 'dispose_after_ack',
            last_export_at: '2026-03-10T10:00:00Z',
            last_purge_at: null,
            retention_updated_at: '2026-03-09T12:00:00Z',
          },
          recent_audit_events: [
            {
              id: 'audit-1',
              event_type: 'policy_updated',
              actor: 'api_key:abc123',
              scope: 'tenant',
              payload: { retention_mode: 'dispose_after_ack', previous: 'retain_all' },
              result_status: 'success',
              created_at: '2026-03-10T10:00:00Z',
            },
          ],
        },
        refetch,
      }),
    );
    mockedUseUpdateRetentionPolicy.mockReturnValue(
      createMockMutation({
        mutateAsync: updateMutateAsync,
      }),
    );
    mockedUseExportTenantData.mockReturnValue(
      createMockMutation({
        mutateAsync: exportMutateAsync,
      }),
    );
    mockedUseExportJobStatus.mockReturnValue(createMockQuery<ExportJobStatusResponse>({ data: undefined }));
    mockedUseDownloadExportJobData.mockReturnValue(
      createMockMutation({
        mutateAsync: downloadMutateAsync,
      }),
    );
    mockedUsePurgeTenantData.mockReturnValue(
      createMockMutation({
        mutateAsync: purgeMutateAsync,
      }),
    );
    importMutateAsync.mockResolvedValue({
      tenant_id: 't-1',
      schema_version: 2,
      imported_at: '2026-03-23T10:00:00Z',
      counts: {},
    });
    mockedUseImportTenantData.mockReturnValue(
      createMockMutation({
        mutateAsync: importMutateAsync,
      }),
    );
    mockedUseAuditEvents.mockReturnValue(
      createMockQuery({
        data: { items: [], total: 0, limit: 20, offset: 0 },
      }),
    );
    presetMutateAsync.mockResolvedValue({
      tenant_id: 'tenant-1',
      retention_mode: 'dispose_after_ack',
      last_export_at: null,
      last_purge_at: null,
      retention_updated_at: null,
      preset: 'gdpr',
    });
    mockedUseApplyRetentionPreset.mockReturnValue(
      createMockMutation({
        mutateAsync: presetMutateAsync,
      }),
    );

    URL.createObjectURL = vi.fn(() => 'blob:test');
    URL.revokeObjectURL = vi.fn();
    HTMLAnchorElement.prototype.click = vi.fn();
    vi.stubGlobal('Blob', blobMock);
  });

  it('pairs the purge danger note with an icon second channel', () => {
    render(<RetentionSection />);

    expect(screen.getByText(/This action is irreversible/i)).toBeInTheDocument();
    expect(screen.getByTestId('acx-retention-danger-icon')).toBeInTheDocument();
    expect(document.querySelector('.acx-retention__note--danger')).toBeTruthy();
  });

  it('renders policy state and links to description-run history instead of a second audit home', () => {
    render(<RetentionSection />);

    expect(screen.getByRole('heading', { name: 'Data & retention', level: 3 })).toBeInTheDocument();
    expect(screen.getByRole('radio', { name: /Dispose after confirmation/ })).toBeChecked();
    expect(screen.queryByText('Showing the five most recent audit events.')).not.toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Full audit log' })).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'See description run history' })).toHaveAttribute(
      'href',
      '#/description-history',
    );
  });

  it('updates the retention policy', async () => {
    render(<RetentionSection />);

    fireEvent.click(screen.getByRole('radio', { name: /Purge on demand/ }));
    fireEvent.click(screen.getByRole('button', { name: 'Save policy' }));

    await waitFor(() => {
      expect(updateMutateAsync).toHaveBeenCalledWith({ retention_mode: 'purge_on_demand' });
    });
  });

  it('exports tenant data: start export starts the async job', async () => {
    render(<RetentionSection />);

    fireEvent.click(screen.getByRole('button', { name: 'Export data' }));
    const startButton = screen.getByRole('button', { name: 'Start export' });
    expect(startButton).not.toBeDisabled();

    fireEvent.click(startButton);

    await waitFor(() => {
      expect(exportMutateAsync).toHaveBeenCalledTimes(1);
    });
  });

  it('exports tenant data: download button appears when job completes', async () => {
    mockedUseExportJobStatus.mockReturnValue(
      createMockQuery({
        data: { job_id: 'job-1', status: 'completed', file_size: 1024, error_message: null },
      }),
    );

    render(<RetentionSection />);

    // Open dialog and start the export
    fireEvent.click(screen.getByRole('button', { name: 'Export data' }));
    expect(screen.getByRole('button', { name: 'Start export' })).toBeInTheDocument();

    // Wrap in async act so exportMutateAsync resolves and React applies the state update
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Start export' }));
      await Promise.resolve();
    });

    // exportJobId is now set and exportJobStatus is 'completed' so download button appears
    const downloadButton = screen.getByRole('button', { name: 'Download export' });
    expect(downloadButton).not.toBeDisabled();

    await act(async () => {
      fireEvent.click(downloadButton);
      await Promise.resolve();
    });

    expect(downloadMutateAsync).toHaveBeenCalledTimes(1);
    expect(blobMock).toHaveBeenCalledTimes(1);
    expect(JSON.parse(blobPayloads[0] ?? '')).toEqual({
      tenant_id: 'tenant-1',
      exported_at: '2026-03-12T12:00:00Z',
      schema_version: 1,
      counts: { clusters: 0 },
      data: { clusters: [] },
    });
  });

  it('keeps an unsupported export job observable after the dialog closes', async () => {
    mockedUseExportJobStatus.mockReturnValue(
      createMockQuery({
        data: { job_id: 'job-1', status: 'processing', file_size: null, error_message: null },
      }),
    );

    render(<RetentionSection />);

    const exportPanel = screen.getByRole('heading', { name: 'Export controls' }).closest('section');
    expect(exportPanel).toBeTruthy();
    const statusRegion = within(exportPanel!).getByRole('status');
    expect(statusRegion).toBeEmptyDOMElement();
    expect(statusRegion).toHaveAttribute('aria-live', 'polite');

    fireEvent.click(screen.getByRole('button', { name: 'Export data' }));
    expect(within(exportPanel!).getByRole('status')).toBe(statusRegion);

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Start export' }));
      await Promise.resolve();
    });

    expect(statusRegion).toHaveTextContent('Export in progress…');
    expect(statusRegion).toHaveTextContent('Job ID: job-1');
    expect(screen.queryByRole('button', { name: 'Cancel' })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Close' }));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(mockedUseExportJobStatus).toHaveBeenLastCalledWith('job-1');
    expect(within(exportPanel!).getByRole('status')).toBe(statusRegion);
    expect(statusRegion).toHaveTextContent('Export in progress…');
    expect(statusRegion).toHaveTextContent('Job ID: job-1');
  });

  it('preserves the retained export job when the export dialog closes', () => {
    const state: RetentionDialogState = {
      draftMode: null,
      isExportDialogOpen: true,
      exportJobId: 'job-1',
      isPurgeDialogOpen: false,
      purgeScope: 'disposed',
      purgeConfirmation: '',
      isImportDialogOpen: false,
      importFile: null,
      auditPage: 0,
    };

    expect(retentionReducer(state, { type: 'CLOSE_EXPORT_DIALOG' })).toEqual({
      ...state,
      isExportDialogOpen: false,
    });
  });

  it('uses a separate persistent assertive region when an export fails', async () => {
    const { rerender } = render(<RetentionSection />);
    const exportPanel = screen.getByRole('heading', { name: 'Export controls' }).closest('section');
    expect(exportPanel).toBeTruthy();
    const statusRegion = within(exportPanel!).getByRole('status');
    const errorRegion = within(exportPanel!).getByRole('alert');
    expect(errorRegion).toBeEmptyDOMElement();
    expect(errorRegion).toHaveAttribute('aria-live', 'assertive');

    fireEvent.click(screen.getByRole('button', { name: 'Export data' }));
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Start export' }));
      await Promise.resolve();
    });

    mockedUseExportJobStatus.mockReturnValue(
      createMockQuery({
        data: { job_id: 'job-1', status: 'failed', file_size: null, error_message: 'Export failed' },
      }),
    );
    rerender(<RetentionSection />);

    expect(within(exportPanel!).getByRole('status')).toBe(statusRegion);
    expect(statusRegion).toBeEmptyDOMElement();
    expect(within(exportPanel!).getByRole('alert')).toBe(errorRegion);
    expect(errorRegion).toHaveTextContent('Export failed. Please try again. Job ID: job-1');
  });

  it('requires typed confirmation before purge', async () => {
    render(<RetentionSection />);

    fireEvent.click(screen.getByRole('button', { name: 'Purge data' }));

    const confirmButton = screen.getByRole('button', { name: 'Confirm purge' });
    expect(confirmButton).toBeDisabled();

    fireEvent.click(screen.getByRole('radio', { name: /All machine data/ }));
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'PURGE' } });
    fireEvent.click(confirmButton);

    await waitFor(() => {
      expect(purgeMutateAsync).toHaveBeenCalledWith({ scope: 'all', confirm: true });
    });
  });

  it('names the recognition service and reported cause when status is unavailable without an envelope', () => {
    mockedUseRetentionStatus.mockReturnValue(
      createMockQuery({
        data: {
          available: false,
          policy: null,
          recent_audit_events: [],
        },
        dataUpdatedAt: Date.parse('2026-09-18T14:03:22Z'),
        refetch,
      }),
    );

    render(<RetentionSection />);

    expect(screen.getByRole('heading', { name: 'Recognition service unavailable' })).toBeInTheDocument();
    expect(screen.getByText('Cause: The service reported it is unavailable.')).toBeInTheDocument();
    expect(screen.getByText('Last checked 14:03:22')).toBeInTheDocument();
    expect(screen.getByTestId('acx-retention-unavailable-icon')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    expect(refetch).toHaveBeenCalledTimes(1);
  });

  it('names the missing policy cause when status is available without a policy', () => {
    mockedUseRetentionStatus.mockReturnValue(
      createMockQuery({
        data: { available: true, policy: null, recent_audit_events: [] },
        dataUpdatedAt: Date.parse('2026-09-18T14:03:22Z'),
        refetch,
      }),
    );

    render(<RetentionSection />);

    expect(screen.getByRole('heading', { name: 'Recognition service unavailable' })).toBeInTheDocument();
    expect(screen.getByText('Cause: The service returned no retention policy.')).toBeInTheDocument();
    expect(screen.getByText('Last checked 14:03:22')).toBeInTheDocument();
  });

  it('shows HTTP status and the error timestamp for a query failure without an envelope', () => {
    const error = new HTTPError({
      status: 503,
      retryAfterSeconds: undefined,
      endpoint: '/retention',
      bodyPreview: '',
      message: 'Service error',
    });
    mockedUseRetentionStatus.mockReturnValue(
      createMockQuery({
        isError: true,
        error,
        errorUpdatedAt: Date.parse('2026-09-18T14:03:22Z'),
        refetch,
      }),
    );

    render(<RetentionSection />);

    expect(screen.getByRole('heading', { name: 'Recognition service unavailable' })).toBeInTheDocument();
    expect(screen.getByText('Cause: HTTP 503')).toBeInTheDocument();
    expect(screen.getByText('Last checked 14:03:22')).toBeInTheDocument();
  });

  it('updates the untyped error timestamp after Retry rechecks and fails again', () => {
    const error = new HTTPError({
      status: 503,
      retryAfterSeconds: undefined,
      endpoint: '/retention',
      bodyPreview: '',
      message: 'Service error',
    });
    mockedUseRetentionStatus.mockReturnValue(
      createMockQuery({
        isError: true,
        error,
        errorUpdatedAt: Date.parse('2026-09-18T14:03:22Z'),
        refetch,
      }),
    );
    const { rerender } = render(<RetentionSection />);

    expect(screen.getByText('Last checked 14:03:22')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    expect(refetch).toHaveBeenCalledTimes(1);

    mockedUseRetentionStatus.mockReturnValue(
      createMockQuery({
        isError: true,
        error,
        errorUpdatedAt: Date.parse('2026-09-18T14:04:05Z'),
        refetch,
      }),
    );
    rerender(<RetentionSection />);

    expect(screen.getByText('Last checked 14:04:05')).toBeInTheDocument();
    expect(screen.queryByText('Last checked 14:03:22')).not.toBeInTheDocument();
  });

  it.each([
    {
      error: new AuthExpiredError({ endpoint: '/retention', status: 401 }),
      expected: 'Cause: HTTP 401',
    },
    {
      error: new Error('Request to /retention failed: private response body'),
      expected: 'Cause: Unable to load retention status. Please try again.',
    },
    {
      error: null,
      expected: 'Cause: Unable to load retention status. Please try again.',
    },
    {
      error: Object.assign(new Error('Request failed'), { code: 'ECONNRESET' }),
      expected: 'Cause: error code ECONNRESET',
    },
  ])('shows safe query error copy with Retry: $expected', ({ error, expected }) => {
    mockedUseRetentionStatus.mockReturnValue(createMockQuery({ isError: true, error, refetch }));
    const { container } = render(<RetentionSection />);
    expect(screen.getByRole('heading', { name: 'Recognition service unavailable' })).toBeInTheDocument();
    expect(screen.getByRole('alert')).toHaveTextContent(expected);
    expect(container).not.toHaveTextContent(/private response body|\/retention/);
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    expect(refetch).toHaveBeenCalledTimes(1);
  });

  it.each([false, true])('shows retry progress and permits retry after failure (query error: %s)', (isError) => {
    const unavailable = { available: false, policy: null, recent_audit_events: [] };
    mockedUseRetentionStatus.mockReturnValue(createMockQuery({ data: unavailable, isError, refetch }));
    const { rerender } = render(<RetentionSection />);
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    expect(refetch).toHaveBeenCalledTimes(1);
    mockedUseRetentionStatus.mockReturnValue(createMockQuery({ data: unavailable, isError, isFetching: true, refetch }));
    rerender(<RetentionSection />);
    expect(screen.getByRole('button', { name: 'Fetching…' })).toBeDisabled();
    expect(screen.getByRole('status')).toHaveTextContent('Fetching retention status…');
    fireEvent.click(screen.getByRole('button', { name: 'Fetching…' }));
    expect(refetch).toHaveBeenCalledTimes(1);
    mockedUseRetentionStatus.mockReturnValue(createMockQuery({ data: unavailable, isError, refetch }));
    rerender(<RetentionSection />);
    expect(screen.getByRole('button', { name: 'Retry' })).toBeEnabled();
    expect(screen.getByRole('status')).toBeEmptyDOMElement();
  });

  const typedUnavailable = (
    checkedAt: string,
    overrides: {
      reason?: string;
      service?: string;
      http_status?: number | null;
      retry_after_seconds?: number | null;
    } = {},
  ) => ({
    available: false as const,
    policy: null,
    recent_audit_events: [],
    unavailable: {
      reason: 'circuit_open',
      service: 'recognition',
      http_status: null,
      retry_after_seconds: 30,
      checked_at: checkedAt,
      ...overrides,
    },
  });

  it('names the service, reason, fix, last checked, and retry countdown from unavailable', () => {
    mockedUseRetentionStatus.mockReturnValue(
      createMockQuery({
        data: typedUnavailable('2026-09-18T14:03:22Z'),
        refetch,
      }),
    );

    render(<RetentionSection />);

    expect(screen.queryByText('Backend unavailable — retention status cannot be loaded.')).not.toBeInTheDocument();
    expect(
      screen.getByText('Recognition service is unavailable because the circuit breaker is open.'),
    ).toBeInTheDocument();
    expect(screen.getByText('Wait for the cooldown, then Retry.')).toBeInTheDocument();
    expect(screen.getByText('Last checked 14:03:22')).toBeInTheDocument();
    expect(screen.getByText('Retry in 30 s')).toBeInTheDocument();
    expect(screen.getByTestId('acx-retention-unavailable-icon')).toBeInTheDocument();
    expect(screen.getByTestId('acx-retention-unavailable')).toHaveClass('acx-sync-status--warning');
    expect(screen.getByRole('button', { name: 'Retry' })).toBeEnabled();
  });

  it('updates last checked after Retry and keeps Retry pending while fetching', () => {
    mockedUseRetentionStatus.mockReturnValue(
      createMockQuery({
        data: typedUnavailable('2026-09-18T14:03:22Z'),
        refetch,
      }),
    );
    const { rerender } = render(<RetentionSection />);

    expect(screen.getByText('Last checked 14:03:22')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    expect(refetch).toHaveBeenCalledTimes(1);

    mockedUseRetentionStatus.mockReturnValue(
      createMockQuery({
        data: typedUnavailable('2026-09-18T14:03:22Z'),
        isFetching: true,
        refetch,
      }),
    );
    rerender(<RetentionSection />);
    expect(screen.getByRole('button', { name: 'Fetching…' })).toBeDisabled();
    expect(screen.getByRole('status')).toHaveTextContent('Fetching retention status…');
    expect(screen.getByText('Last checked 14:03:22')).toBeInTheDocument();

    mockedUseRetentionStatus.mockReturnValue(
      createMockQuery({
        data: typedUnavailable('2026-09-18T14:04:05Z'),
        refetch,
      }),
    );
    rerender(<RetentionSection />);
    expect(screen.getByText('Last checked 14:04:05')).toBeInTheDocument();
    expect(screen.queryByText('Last checked 14:03:22')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Retry' })).toBeEnabled();
  });

  it('omits a retry countdown when retry_after_seconds is absent', () => {
    mockedUseRetentionStatus.mockReturnValue(
      createMockQuery({
        data: typedUnavailable('2026-09-18T14:03:22Z', { retry_after_seconds: null }),
        refetch,
      }),
    );

    render(<RetentionSection />);

    expect(screen.getByText('Last checked 14:03:22')).toBeInTheDocument();
    expect(screen.queryByText(/Retry in /)).not.toBeInTheDocument();
  });

  it('uses generic copy plus the reason code for an unknown unavailable reason', () => {
    mockedUseRetentionStatus.mockReturnValue(
      createMockQuery({
        data: typedUnavailable('2026-09-18T14:03:22Z', { reason: 'mystery_code', retry_after_seconds: null }),
        refetch,
      }),
    );

    render(<RetentionSection />);

    expect(
      screen.getByText('Recognition service is unavailable because an unexpected error occurred (mystery_code).'),
    ).toBeInTheDocument();
    expect(screen.getByText('Retry. If it continues, check Settings and the service logs.')).toBeInTheDocument();
  });

  it('opens import dialog and calls importMutateAsync on confirm', async () => {
    const fileContent = JSON.stringify({ schema_version: 2, clusters: [] });
    const user = userEvent.setup();
    render(<RetentionSection />);

    await user.click(screen.getByRole('button', { name: 'Import data' }));
    expect(await screen.findByText('Import tenant data')).toBeInTheDocument();

    const file = new File([fileContent], 'export.json', { type: 'application/json' });
    // JSDOM inherits File.text() from Blob.prototype; override on the instance to
    // ensure the async read returns deterministic content in the test environment.
    (file as File & { text: () => Promise<string> }).text = () => Promise.resolve(fileContent);

    const fileInput = screen.getByLabelText('Export file (.json)');
    Object.defineProperty(fileInput, 'files', { value: [file], configurable: true });
    fireEvent.change(fileInput);

    expect(await screen.findByText('Selected: export.json')).toBeInTheDocument();

    const importButton = screen.getByRole('button', { name: 'Import' });
    expect(importButton).not.toBeDisabled();

    await user.click(importButton);

    await waitFor(() => {
      expect(importMutateAsync).toHaveBeenCalledWith({
        data: { schema_version: 2, clusters: [] },
      });
    });
    expect(toastSuccess).toHaveBeenCalledWith('Import completed.');
  });

  it('does not mount a full audit log on Data Retention', () => {
    render(<RetentionSection />);
    expect(screen.queryByRole('heading', { name: 'Full audit log' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Next' })).not.toBeInTheDocument();
  });

  it('applies GDPR preset when Apply GDPR preset button is clicked', async () => {
    render(<RetentionSection />);

    const presetButton = screen.getByRole('button', { name: 'Apply GDPR preset' });
    expect(presetButton).not.toBeDisabled();

    fireEvent.click(presetButton);

    await waitFor(() => {
      expect(presetMutateAsync).toHaveBeenCalledWith({ preset: 'gdpr' });
    });
    expect(toastSuccess).toHaveBeenCalledWith('GDPR preset applied.');
  });
});
