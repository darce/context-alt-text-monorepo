import { render, screen } from '@testing-library/react';

import { NoMediaPanel } from '../ScanTabContent';

vi.mock('@wordpress/i18n', () => ({ __: (text: string) => text }));

it('offers the Scan front door when the analysis queue is empty', () => {
  render(<NoMediaPanel />);

  expect(screen.getByRole('link', { name: 'Go to Scan' })).toHaveAttribute(
    'href',
    '#acx-workbench-scan-heading',
  );
});
