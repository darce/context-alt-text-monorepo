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

    expect(screen.getByTestId('acx-toast-icon-success')).toHaveAttribute('data-toast-severity', 'success');
    expect(screen.getByTestId('acx-toast-icon-error')).toHaveAttribute('data-toast-severity', 'error');
    expect(screen.getByTestId('acx-toast-icon-info')).toHaveAttribute('data-toast-severity', 'info');
    expect(screen.getByText('Success')).toBeInTheDocument();
    expect(screen.getByText('Error')).toBeInTheDocument();
    expect(screen.getByText('Info')).toBeInTheDocument();
    expect(screen.getByText('Saved')).toBeInTheDocument();
    expect(screen.getByText('Failed')).toBeInTheDocument();
    expect(screen.getByText('Heads up')).toBeInTheDocument();
  });
});
