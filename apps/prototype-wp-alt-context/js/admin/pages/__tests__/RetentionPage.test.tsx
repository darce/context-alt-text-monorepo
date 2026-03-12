import { fireEvent, render, screen, waitFor } from '@testing-library/react';

import { RetentionPage } from '../RetentionPage';
import {
  useExportTenantData,
  usePurgeTenantData,
  useRetentionStatus,
  useUpdateRetentionPolicy,
} from '../../hooks/useRetentionStatus';
import { createMockMutation, createMockQuery } from '../../test-utils/mockHooks';

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
  usePurgeTenantData: vi.fn(),
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
  const mockedUsePurgeTenantData = vi.mocked(usePurgeTenantData);

  const updateMutateAsync = vi.fn();
  const exportMutateAsync = vi.fn();
  const purgeMutateAsync = vi.fn();
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
    exportMutateAsync.mockResolvedValue({
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
    mockedUsePurgeTenantData.mockReturnValue(
      createMockMutation({
        mutateAsync: purgeMutateAsync,
      }),
    );

    URL.createObjectURL = vi.fn(() => 'blob:test');
    URL.revokeObjectURL = vi.fn();
    HTMLAnchorElement.prototype.click = vi.fn();
    vi.stubGlobal('Blob', blobMock as unknown as typeof Blob);
  });

  it('renders policy state and audit history', () => {
    render(<RetentionPage />);

    expect(screen.getByText('Retention & Audit Controls')).toBeInTheDocument();
    expect(screen.getByRole('radio', { name: /Dispose after acknowledgement/ })).toBeChecked();
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

  it('exports tenant data after confirmation', async () => {
    render(<RetentionPage />);

    fireEvent.click(screen.getByRole('button', { name: 'Export data' }));
    fireEvent.click(screen.getByRole('button', { name: 'Download export' }));

    await waitFor(() => {
      expect(exportMutateAsync).toHaveBeenCalledTimes(1);
    });

    expect(blobMock).toHaveBeenCalledTimes(1);
    expect(JSON.parse(blobPayloads[0] ?? '')).toEqual({
      tenant_id: 'tenant-1',
      exported_at: '2026-03-12T12:00:00Z',
      schema_version: 1,
      counts: { clusters: 0 },
      data: { clusters: [] },
    });
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
});
