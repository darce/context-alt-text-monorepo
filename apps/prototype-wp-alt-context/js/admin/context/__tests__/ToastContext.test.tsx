import { render, screen, act } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { ToastProvider, useToast } from '../ToastContext';

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
}));

const ToastProbe = (): React.JSX.Element => {
  const { toast, success, error, info } = useToast();
  return (
    <div>
      <button type="button" onClick={() => toast('Plain')}>
        plain
      </button>
      <button type="button" onClick={() => success('Saved')}>
        success
      </button>
      <button type="button" onClick={() => error('Failed')}>
        error
      </button>
      <button type="button" onClick={() => info('Heads up')}>
        info
      </button>
      <button
        type="button"
        onClick={() =>
          info('GPU ready', {
            action: {
              label: 'Back to run',
              altText: 'Return to the active describe run',
              onClick: actionClick,
            },
          })
        }
      >
        actionable
      </button>
    </div>
  );
};

const actionClick = vi.fn();

describe('ToastContext second channels', () => {
  beforeEach(() => {
    actionClick.mockClear();
  });

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

  it('keeps string-only toast helpers backward compatible', () => {
    render(
      <ToastProvider>
        <ToastProbe />
      </ToastProvider>,
    );

    act(() => {
      screen.getByRole('button', { name: 'plain' }).click();
      screen.getByRole('button', { name: 'info' }).click();
      screen.getByRole('button', { name: 'error' }).click();
    });

    expect(screen.getByText('Plain')).toBeInTheDocument();
    expect(screen.getByText('Heads up')).toBeInTheDocument();
    expect(screen.getByText('Failed')).toBeInTheDocument();
  });

  it('renders an action and invokes it exactly once', () => {
    render(
      <ToastProvider>
        <ToastProbe />
      </ToastProvider>,
    );

    act(() => screen.getByRole('button', { name: 'actionable' }).click());
    const action = screen.getByRole('button', { name: 'Back to run' });
    expect(action).toHaveAttribute('data-radix-toast-announce-alt', 'Return to the active describe run');
    act(() => action.click());

    expect(actionClick).toHaveBeenCalledOnce();
  });

  it('announces errors assertively and info politely', () => {
    const errorRender = render(
      <ToastProvider>
        <ToastProbe />
      </ToastProvider>,
    );

    act(() => screen.getByRole('button', { name: 'error' }).click());
    expect(screen.getByRole('alert')).toHaveTextContent('Failed');
    expect(screen.getByRole('status')).toHaveAttribute('aria-live', 'assertive');
    errorRender.unmount();

    render(
      <ToastProvider>
        <ToastProbe />
      </ToastProvider>,
    );
    act(() => screen.getByRole('button', { name: 'info' }).click());
    expect(screen.getByRole('status')).toHaveAttribute('aria-live', 'polite');
    expect(screen.getByText('Heads up')).toBeInTheDocument();
  });
});

describe('ToastContext dismissal timing', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    actionClick.mockClear();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('keeps actionable toasts present beyond the default timeout', () => {
    render(
      <ToastProvider>
        <ToastProbe />
      </ToastProvider>,
    );
    act(() => screen.getByRole('button', { name: 'actionable' }).click());

    act(() => {
      vi.advanceTimersByTime(5_001);
    });

    expect(screen.getByText('GPU ready')).toBeInTheDocument();
  });

  it('removes non-actionable toasts after the default timeout', () => {
    render(
      <ToastProvider>
        <ToastProbe />
      </ToastProvider>,
    );
    act(() => screen.getByRole('button', { name: 'info' }).click());

    act(() => {
      vi.advanceTimersByTime(5_000);
    });

    expect(screen.queryByText('Heads up')).not.toBeInTheDocument();
  });

  it('closes an actionable toast and clears its timer bookkeeping', () => {
    render(
      <ToastProvider>
        <ToastProbe />
      </ToastProvider>,
    );
    act(() => screen.getByRole('button', { name: 'actionable' }).click());

    act(() => screen.getByRole('button', { name: 'Close' }).click());
    act(() => {
      vi.advanceTimersByTime(5_001);
    });

    expect(screen.queryByText('GPU ready')).not.toBeInTheDocument();
    expect(actionClick).not.toHaveBeenCalled();
  });
});
