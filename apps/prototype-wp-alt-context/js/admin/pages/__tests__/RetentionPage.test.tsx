import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { RetentionPage } from '../RetentionPage';
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

describe('RetentionPage', () => {
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
    render(<RetentionPage />);

    expect(screen.getByText(/This action is irreversible/i)).toBeInTheDocument();
    expect(screen.getByTestId('acx-retention-danger-icon')).toBeInTheDocument();
    expect(document.querySelector('.acx-retention__note--danger')).toBeTruthy();
  });

  it('renders policy state and audit history', () => {
    render(<RetentionPage />);

    expect(screen.getByText('Data Retention')).toBeInTheDocument();
    expect(screen.getByRole('radio', { name: /Dispose after confirmation/ })).toBeChecked();
    expect(screen.getByText('Showing the five most recent audit events.')).toBeInTheDocument();
    expect(screen.getByText('policy_updated')).toBeInTheDocument();
    expect(screen.getByText('retention_mode: dispose_after_ack · previous: retain_all')).toBeInTheDocument();
  });

  it('updates the retention policy', async () => {
    render(<RetentionPage />);

    fireEvent.click(screen.getByRole('radio', { name: /Purge on demand/ }));
    fireEvent.click(screen.getByRole('button', { name: 'Save policy' }));

    await waitFor(() => {
      expect(updateMutateAsync).toHaveBeenCalledWith({ retention_mode: 'purge_on_demand' });
    });
  });

  it('exports tenant data: start export starts the async job', async () => {
    render(<RetentionPage />);

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

    render(<RetentionPage />);

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

    render(<RetentionPage />);

    fireEvent.click(screen.getByRole('button', { name: 'Export data' }));
    const statusRegion = screen.getByRole('status');
    expect(statusRegion).toHaveAttribute('aria-live', 'polite');

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

    fireEvent.click(screen.getByRole('button', { name: 'Export data' }));
    expect(screen.getByRole('status')).toHaveTextContent('Job ID: job-1');
    expect(screen.getByRole('button', { name: 'Start export' })).toBeDisabled();
  });

  it('requires typed confirmation before purge', async () => {
    render(<RetentionPage />);

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

  it('shows graceful fallback when retention status is unavailable', () => {
    mockedUseRetentionStatus.mockReturnValue(
      createMockQuery({
        data: {
          available: false,
          policy: null,
          recent_audit_events: [],
        },
        refetch,
      }),
    );

    render(<RetentionPage />);

    expect(screen.getByText('Backend unavailable — retention status cannot be loaded.')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    expect(refetch).toHaveBeenCalledTimes(1);
  });

  it('opens import dialog and calls importMutateAsync on confirm', async () => {
    const fileContent = JSON.stringify({ schema_version: 2, clusters: [] });
    const user = userEvent.setup();
    render(<RetentionPage />);

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

  it('full audit log shows events returned by useAuditEvents', () => {
    mockedUseAuditEvents.mockReturnValue(
      createMockQuery({
        data: {
          items: [
            {
              id: 'evt-audit-1',
              event_type: 'import_completed',
              actor: 'api_key:test',
              scope: 'tenant',
              payload: { schema_version: 2 },
              result_status: 'success',
              created_at: '2026-03-23T10:00:00Z',
            },
          ],
          total: 1,
          limit: 20,
          offset: 0,
        },
      }),
    );

    render(<RetentionPage />);

    const auditLogSection = screen.getByRole('heading', { name: 'Full audit log' }).closest('section');
    expect(auditLogSection).toBeInTheDocument();
    expect(auditLogSection).toHaveTextContent('import_completed');
    expect(auditLogSection).toHaveTextContent('Actor: api_key:test · Result: success');
  });

  it('audit log shows Next button and advances page when total exceeds page size', () => {
    mockedUseAuditEvents.mockReturnValue(
      createMockQuery({
        data: { items: [], total: 25, limit: 20, offset: 0 },
      }),
    );

    render(<RetentionPage />);

    const nextButton = screen.getByRole('button', { name: 'Next' });
    expect(nextButton).not.toBeDisabled();

    act(() => {
      fireEvent.click(nextButton);
    });

    expect(mockedUseAuditEvents).toHaveBeenLastCalledWith({ limit: 20, offset: 20 });
  });

  it('applies GDPR preset when Apply GDPR preset button is clicked', async () => {
    render(<RetentionPage />);

    const presetButton = screen.getByRole('button', { name: 'Apply GDPR preset' });
    expect(presetButton).not.toBeDisabled();

    fireEvent.click(presetButton);

    await waitFor(() => {
      expect(presetMutateAsync).toHaveBeenCalledWith({ preset: 'gdpr' });
    });
    expect(toastSuccess).toHaveBeenCalledWith('GDPR preset applied.');
  });
});
