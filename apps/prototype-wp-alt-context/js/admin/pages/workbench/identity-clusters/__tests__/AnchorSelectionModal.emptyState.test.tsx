import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { vi } from 'vitest';

import { AnchorSelectionModal } from '../AnchorSelectionModal';

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
  sprintf: (text: string) => text,
}));

it('lets operators cancel when there are no faces to select', async () => {
  const onClose = vi.fn();
  render(
    <AnchorSelectionModal
      isOpen
      label={null}
      members={[]}
      onClose={onClose}
      onSelectAnchor={vi.fn()}
    />,
  );

  await userEvent.click(screen.getByRole('button', { name: 'Back to review suggestions' }));
  expect(onClose).toHaveBeenCalled();
});
