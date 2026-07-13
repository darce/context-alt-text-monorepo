import { render, screen, act } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { ToastProvider, useToast } from '../ToastContext';

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
}));

const ToastProbe = (): React.JSX.Element => {
  const { success, error, info } = useToast();
  return (
    <div>
      <button type="button" onClick={() => success('Saved')}>
        success
      </button>
      <button type="button" onClick={() => error('Failed')}>
        error
      </button>
      <button type="button" onClick={() => info('Heads up')}>
        info
      </button>
    </div>
  );
};

describe('ToastContext second channels', () => {
  it('renders a distinct icon and severity label per toast type', () => {
    render(
      <ToastProvider>
        <ToastProbe />
      </ToastProvider>,
    );

    act(() => {
      screen.getByRole('button', { name: 'success' }).click();
      screen.getByRole('button', { name: 'error' }).click();
      screen.getByRole('button', { name: 'info' }).click();
    });

    const successIcon = screen.getByTestId('acx-toast-icon-success');
    const errorIcon = screen.getByTestId('acx-toast-icon-error');
    const infoIcon = screen.getByTestId('acx-toast-icon-info');

    expect(successIcon).toHaveAttribute('data-toast-severity', 'success');
    expect(errorIcon).toHaveAttribute('data-toast-severity', 'error');
    expect(infoIcon).toHaveAttribute('data-toast-severity', 'info');

    // Each severity must render a distinct visible glyph (svg path/shape), not only the wrapper attr.
    const successGlyph = successIcon.innerHTML;
    const errorGlyph = errorIcon.innerHTML;
    const infoGlyph = infoIcon.innerHTML;
    expect(successGlyph.length).toBeGreaterThan(0);
    expect(errorGlyph.length).toBeGreaterThan(0);
    expect(infoGlyph.length).toBeGreaterThan(0);
    expect(successGlyph).not.toBe(errorGlyph);
    expect(successGlyph).not.toBe(infoGlyph);
    expect(errorGlyph).not.toBe(infoGlyph);

    expect(screen.getByText('Success')).toBeInTheDocument();
    expect(screen.getByText('Error')).toBeInTheDocument();
    expect(screen.getByText('Info')).toBeInTheDocument();
    expect(screen.getByText('Saved')).toBeInTheDocument();
    expect(screen.getByText('Failed')).toBeInTheDocument();
    expect(screen.getByText('Heads up')).toBeInTheDocument();
  });
});
