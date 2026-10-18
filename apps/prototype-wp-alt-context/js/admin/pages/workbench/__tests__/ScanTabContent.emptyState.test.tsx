import type { ReactNode } from 'react';
import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { HashRouter, Navigate, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach } from 'vitest';

import { NoMediaPanel } from '../ScanTabContent';

vi.mock('@wordpress/i18n', () => ({ __: (text: string) => text }));

/**
 * Mirrors App.tsx HashRouter + splat Navigate. A raw `#acx-workbench-scan-heading`
 * href is parsed as path `/acx-workbench-scan-heading` and replaced to dashboard.
 */
const WorkbenchWithScanHeading = ({ children }: { children: ReactNode }) => (
  <div>
    {children}
    <h3 id="acx-workbench-scan-heading" tabIndex={-1}>
      Scan
    </h3>
  </div>
);

const renderOnWorkbench = (ui: ReactNode) => {
  window.history.replaceState(null, '', '#/workbench?tab=scan');
  return render(
    <HashRouter>
      <Routes>
        <Route path="/workbench" element={<WorkbenchWithScanHeading>{ui}</WorkbenchWithScanHeading>} />
        <Route path="/dashboard" element={<div data-testid="dashboard">Dashboard</div>} />
        <Route path="*" element={<Navigate to="/dashboard" replace />} />
      </Routes>
    </HashRouter>,
  );
};

beforeEach(() => {
  window.history.replaceState(null, '', '#/workbench?tab=scan');
});

afterEach(() => {
  cleanup();
  window.history.replaceState(null, '', '/');
});

it('lands Go to Scan on the scan heading without bouncing off HashRouter [DUX-W2D6C-RV-01]', async () => {
  const user = userEvent.setup();
  renderOnWorkbench(<NoMediaPanel />);

  await user.click(screen.getByRole('link', { name: 'Go to Scan' }));

  // Destination is the workbench scan tab, not a fragment HashRouter would
  // parse as path `/acx-workbench-scan-heading` and replace to dashboard.
  expect(window.location.hash).toMatch(/^#\/workbench(?:\?|$)/);
  expect(screen.queryByTestId('dashboard')).not.toBeInTheDocument();
  expect(screen.getByRole('heading', { name: 'Scan' })).toHaveFocus();
});
