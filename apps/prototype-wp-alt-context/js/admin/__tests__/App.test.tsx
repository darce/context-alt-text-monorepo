import React from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';

import { App, determineInitialRoute } from '../App';

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

vi.mock('../context/ToastContext', () => ({
  ToastProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  useToast: () => ({
    success: vi.fn(),
    error: vi.fn(),
  }),
}));

describe('App route boot', () => {
  const originalHash = window.location.hash;
  const originalHref = window.location.href;

  beforeEach(() => {
    vi.clearAllMocks();
    window.history.replaceState({}, '', '/');
    window.location.hash = '';
  });

  afterEach(() => {
    window.history.replaceState({}, '', originalHref);
    window.location.hash = originalHash;
  });

  it('maps the retention admin page query arg to the retention route', () => {
    window.history.replaceState({}, '', '/wp-admin/admin.php?page=alt-context-retention');

    expect(determineInitialRoute()).toBe('/retention');
  });

  it('redirects the /retention hash route to settings with the retention section', () => {
    window.history.replaceState({}, '', '/wp-admin/admin.php?page=alt-context-settings');
    window.location.hash = '#/retention';

    render(<App />);

    expect(window.location.hash).toBe('#/settings?section=retention');
    expect(screen.getByText('Settings')).toBeInTheDocument();
    expect(screen.queryByRole('region', { name: 'Data Retention' })).not.toBeInTheDocument();
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

  it('boots settings from the retention admin page query arg via the /retention redirect', () => {
    window.history.replaceState({}, '', '/wp-admin/admin.php?page=alt-context-retention');

    render(<App />);

    expect(window.location.hash).toBe('#/settings?section=retention');
    expect(screen.getByText('Settings')).toBeInTheDocument();
  });
});
