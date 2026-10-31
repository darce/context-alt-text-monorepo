import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { MinimumPhotosControl } from '../../hooks/MinimumPhotosControl';

vi.mock('@wordpress/i18n', () => ({ __: (text: string) => text }));

describe('Minimum photos optional control', () => {
  it('labels the optional filter, defaults to All and clears by omission', () => {
    const onChange = vi.fn();
    const { rerender } = render(<MinimumPhotosControl onChange={onChange} />);
    const select = screen.getByRole('combobox', { name: 'Minimum photos (optional)' });
    expect(select).toHaveValue('');
    fireEvent.change(select, { target: { value: '3' } });
    expect(onChange).toHaveBeenLastCalledWith(3);
    rerender(<MinimumPhotosControl value={3} onChange={onChange} />);
    fireEvent.change(select, { target: { value: '' } });
    expect(onChange).toHaveBeenLastCalledWith(undefined);
    expect(screen.getByText(/Counts distinct photos.*not the number of faces/)).toBeVisible();
  });
  it('can display an applied minimum outside the preset choices honestly', () => {
    render(<MinimumPhotosControl value={4} onChange={vi.fn()} />);
    expect(screen.getByRole('combobox')).toHaveValue('4');
  });
});
