import React from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

import { App, determineInitialRoute } from '../App';
import {
  useExportTenantData,
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

vi.mock('../hooks/useRetentionStatus', () => ({
  useRetentionStatus: vi.fn(),
  useUpdateRetentionPolicy: vi.fn(),
  useExportTenantData: vi.fn(),
  usePurgeTenantData: vi.fn(),
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
  const mockedUsePurgeTenantData = vi.mocked(usePurgeTenantData);
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
    mockedUsePurgeTenantData.mockReturnValue(createMockMutation());
  });

  afterEach(() => {
    window.history.replaceState({}, '', originalHref);
    window.location.hash = originalHash;
  });

  it('maps the retention admin page query arg to the retention route', () => {
    window.history.replaceState({}, '', '/wp-admin/admin.php?page=alt-context-retention');

    expect(determineInitialRoute()).toBe('/retention');
  });

  it('boots the retention page from the WordPress admin query arg and saves policy changes', async () => {
    window.history.replaceState({}, '', '/wp-admin/admin.php?page=alt-context-retention');

    render(<App />);

    expect(window.location.hash).toBe('#/retention');
    expect(screen.getByRole('heading', { name: 'Retention & Audit Controls' })).toBeInTheDocument();

    fireEvent.click(screen.getByRole('radio', { name: /Purge on demand/ }));
    fireEvent.click(screen.getByRole('button', { name: 'Save policy' }));

    await waitFor(() => {
      expect(updateMutateAsync).toHaveBeenCalledWith({ retention_mode: 'purge_on_demand' });
    });
  });
});
