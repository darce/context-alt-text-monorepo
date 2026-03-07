import { fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { ConfirmDialog } from '../ConfirmDialog';

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
}));

describe('ConfirmDialog', () => {
  it('renders copy and handles confirm/cancel/escape interactions', async () => {
    const onConfirm = vi.fn();
    const onCancel = vi.fn();
    const onOpenChange = vi.fn();

    render(
      <ConfirmDialog
        open
        onOpenChange={onOpenChange}
        onConfirm={onConfirm}
        onCancel={onCancel}
        title="Confirm merge"
        description="Merge these clusters?"
        confirmLabel="Merge"
        isPending={false}
      />,
    );

    expect(screen.getByRole('heading', { name: 'Confirm merge' })).toBeInTheDocument();
    expect(screen.getByText('Merge these clusters?')).toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(onCancel).toHaveBeenCalledTimes(1);

    await userEvent.click(screen.getByRole('button', { name: 'Merge' }));
    expect(onConfirm).toHaveBeenCalledTimes(1);

    fireEvent.keyDown(document, { key: 'Escape' });
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it('shows pending state on confirm button', () => {
    render(
      <ConfirmDialog
        open
        onOpenChange={vi.fn()}
        onConfirm={vi.fn()}
        onCancel={vi.fn()}
        title="Confirm dismiss"
        description="Dismiss selected clusters?"
        confirmLabel="Dismiss"
        isPending
      />,
    );

    expect(screen.getByRole('button', { name: 'Processing...' })).toBeDisabled();
  });
});
