import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { ClusterActions } from '../ClusterActions';

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
}));

const baseProps = {
  canEdit: true,
  canSearchForMatch: false,
  hasLabel: true,
  isAutoLabel: false,
  canSplit: true,
  isPending: false,
  onEdit: vi.fn(),
  onWrongPerson: vi.fn(),
  onSplit: vi.fn(),
};

describe('ClusterActions split state matrix (A11Y-24)', () => {
  it('hides split in empty capability state (canSplit false)', () => {
    render(<ClusterActions {...baseProps} canSplit={false} />);

    expect(screen.queryByRole('button', { name: 'Split group' })).not.toBeInTheDocument();
  });

  it('disables split while a mutation is pending (loading)', () => {
    render(<ClusterActions {...baseProps} isPending />);

    expect(screen.getByRole('button', { name: 'Split group' })).toBeDisabled();
  });

  it('disables split with offline reason and does not fire (offline)', async () => {
    const onSplit = vi.fn();
    render(
      <ClusterActions
        {...baseProps}
        onSplit={onSplit}
        splitDisabled
        splitAriaDisabled
        splitTitle="Unavailable while the recognition service is offline"
      />,
    );

    const button = screen.getByRole('button', { name: 'Split group' });
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute('title', 'Unavailable while the recognition service is offline');
    expect(button).toHaveAttribute('aria-disabled', 'true');
    await userEvent.click(button);
    expect(onSplit).not.toHaveBeenCalled();
  });

  it('fires split when online and enabled', async () => {
    const onSplit = vi.fn();
    render(<ClusterActions {...baseProps} onSplit={onSplit} />);

    await userEvent.click(screen.getByRole('button', { name: 'Split group' }));
    expect(onSplit).toHaveBeenCalledOnce();
  });
});
