import React from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

import { App, determineInitialRoute } from '../App';
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
} from '../hooks/useRetentionStatus';
import { createMockMutation, createMockQuery } from '../test-utils/mockHooks';

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

vi.mock('../pages/DashboardPage', () => ({
  DashboardPage: () => <div>Dashboard</div>,
}));

vi.mock('../pages/WorkbenchPage', () => ({
  WorkbenchPage: () => <div>Workbench</div>,
}));

vi.mock('../pages/RosterPage', () => ({
  RosterPage: () => <div>Roster</div>,
}));

vi.mock('../pages/SettingsPage', () => ({
  SettingsPage: () => <div>Settings</div>,
}));

vi.mock('../pages/DescriptionHistoryPage', () => ({
  DescriptionHistoryPage: () => <div>Description History</div>,
}));

vi.mock('../hooks/useRetentionStatus', () => ({
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

vi.mock('../context/ToastContext', () => ({
  ToastProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  useToast: () => ({
    success: vi.fn(),
    error: vi.fn(),
  }),
}));

describe('App route boot', () => {
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
  const originalHash = window.location.hash;
  const originalHref = window.location.href;

  beforeEach(() => {
    vi.clearAllMocks();
    window.history.replaceState({}, '', '/');
    window.location.hash = '';

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
      }),
    );
    mockedUseUpdateRetentionPolicy.mockReturnValue(
      createMockMutation({
        mutateAsync: updateMutateAsync,
      }),
    );
    mockedUseExportTenantData.mockReturnValue(createMockMutation());
    mockedUseExportJobStatus.mockReturnValue(createMockQuery());
    mockedUseDownloadExportJobData.mockReturnValue(createMockMutation());
    mockedUsePurgeTenantData.mockReturnValue(createMockMutation());
    mockedUseImportTenantData.mockReturnValue(createMockMutation());
    mockedUseAuditEvents.mockReturnValue(createMockQuery({ data: { items: [], total: 0, limit: 20, offset: 0 } }));
    mockedUseApplyRetentionPreset.mockReturnValue(createMockMutation());
  });

  afterEach(() => {
    window.history.replaceState({}, '', originalHref);
    window.location.hash = originalHash;
  });

  it('maps the retention admin page query arg to the retention route', () => {
    window.history.replaceState({}, '', '/wp-admin/admin.php?page=alt-context-retention');

    expect(determineInitialRoute()).toBe('/retention');
  });

  it('maps the settings admin page query arg to the settings route', () => {
    window.history.replaceState({}, '', '/wp-admin/admin.php?page=alt-context-settings');

    expect(determineInitialRoute()).toBe('/settings');
  });

  it('maps the description history admin page query arg to the history route', () => {
    window.history.replaceState({}, '', '/wp-admin/admin.php?page=alt-context-description-history');

    expect(determineInitialRoute()).toBe('/description-history');
  });

  it('boots the settings page from the WordPress admin query arg', () => {
    window.history.replaceState({}, '', '/wp-admin/admin.php?page=alt-context-settings');

    render(<App />);

    expect(window.location.hash).toBe('#/settings');
    expect(screen.getByText('Settings')).toBeInTheDocument();
  });

  it('boots the description history page from the WordPress admin query arg', () => {
    window.history.replaceState({}, '', '/wp-admin/admin.php?page=alt-context-description-history');

    render(<App />);

    expect(window.location.hash).toBe('#/description-history');
    expect(screen.getByText('Description History')).toBeInTheDocument();
  });

  it('boots the retention page from the WordPress admin query arg and saves policy changes', async () => {
    window.history.replaceState({}, '', '/wp-admin/admin.php?page=alt-context-retention');

    render(<App />);

    expect(window.location.hash).toBe('#/retention');
    // The visible hero title is now a <p> (WordPress shell owns the page's only
    // <h1>, ORCH-UX-UI-BR-23); assert via the section's accessible name so the
    // test still fails if the preserved id/aria-labelledby link is broken.
    expect(screen.getByRole('region', { name: 'Data Retention' })).toBeInTheDocument();

    fireEvent.click(screen.getByRole('radio', { name: /Purge on demand/ }));
    fireEvent.click(screen.getByRole('button', { name: 'Save policy' }));

    await waitFor(() => {
      expect(updateMutateAsync).toHaveBeenCalledWith({ retention_mode: 'purge_on_demand' });
    });
  });
});
