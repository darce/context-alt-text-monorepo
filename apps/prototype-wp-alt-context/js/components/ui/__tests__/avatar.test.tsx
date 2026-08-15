import React from 'react';
import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { AVATAR_STATES, Avatar, resolveAvatarRenderState } from '../avatar';

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
}));

// Radix Avatar.Image reports load status via onLoadingStatusChange.
// Drive that from the src query so each state can be asserted independently.
vi.mock('@radix-ui/react-avatar', async () => {
  const ReactMod = await import('react');
  return {
    Root: ReactMod.forwardRef(function MockRoot(
      { children, ...props }: Record<string, unknown>,
      ref: unknown,
    ) {
      return ReactMod.createElement(
        'span',
        { ...props, ref } as React.HTMLAttributes<HTMLSpanElement>,
        children as React.ReactNode,
      );
    }),
    Image: ReactMod.forwardRef(function MockImage(
      { onLoadingStatusChange, src, alt, ...props }: Record<string, unknown>,
      ref: unknown,
    ) {
      ReactMod.useEffect(() => {
        if (typeof onLoadingStatusChange !== 'function' || typeof src !== 'string') {
          return;
        }
        // status=hold: src changed but the new image has not reported yet.
        // Lets the swap-frame test observe the first paint without a stale
        // loaded/error callback from the previous identity.
        if (src.includes('status=hold')) {
          return;
        }
        const status = src.includes('status=error')
          ? 'error'
          : src.includes('status=loading')
            ? 'loading'
            : 'loaded';
        onLoadingStatusChange(status);
      }, [src, onLoadingStatusChange]);
      return ReactMod.createElement('img', {
        ...(props as React.ImgHTMLAttributes<HTMLImageElement>),
        src,
        alt,
        ref,
      } as React.ImgHTMLAttributes<HTMLImageElement>);
    }),
    Fallback: ReactMod.forwardRef(function MockFallback(
      { children, ...props }: Record<string, unknown>,
      ref: unknown,
    ) {
      return ReactMod.createElement(
        'span',
        { ...props, ref } as React.HTMLAttributes<HTMLSpanElement>,
        children as React.ReactNode,
      );
    }),
  };
});

describe('Avatar four-state contract', () => {
  it('loading: src present and not yet loaded sets data-avatar-state=loading with aria-hidden skeleton', () => {
    const { container } = render(
      <Avatar src="https://example.com/thumb.jpg?status=loading" alt="Pending face" />,
    );

    const root = container.querySelector('[data-avatar-state]') as HTMLElement;
    expect(root).toHaveAttribute('data-avatar-state', AVATAR_STATES.loading);
    expect(root).toHaveAttribute('data-avatar-state', 'loading');

    const skeleton = container.querySelector('.acx-avatar__skeleton');
    expect(skeleton).not.toBeNull();
    expect(skeleton).toHaveAttribute('aria-hidden', 'true');
  });

  it('real: src present and load succeeded sets data-avatar-state=real and passes alt through', () => {
    const { container } = render(
      <Avatar src="https://example.com/thumb.jpg?status=loaded" alt="Alex (suggested)" />,
    );

    const root = container.querySelector('[data-avatar-state]') as HTMLElement;
    expect(root).toHaveAttribute('data-avatar-state', AVATAR_STATES.real);
    expect(root).toHaveAttribute('data-avatar-state', 'real');

    const image = screen.getByRole('img', { name: 'Alex (suggested)' });
    expect(image).toHaveAttribute('src', 'https://example.com/thumb.jpg?status=loaded');
    expect(image).toHaveAttribute('alt', 'Alex (suggested)');
  });

  it('data-missing: omitted src sets data-avatar-state=data-missing with role=img and accessible name', () => {
    const { container } = render(<Avatar />);

    const root = container.querySelector('[data-avatar-state]') as HTMLElement;
    expect(root).toHaveAttribute('data-avatar-state', AVATAR_STATES.dataMissing);
    expect(root).toHaveAttribute('data-avatar-state', 'data-missing');

    const named = screen.getByRole('img', { name: 'No image' });
    expect(named).toBe(root);
    expect(screen.getByText('No image')).toBeInTheDocument();
    expect(container.querySelector('.lucide-image-off')).not.toBeNull();
  });

  // E21-20-REV9-01 / TEST-15: missingLabel is the accessible name only.
  // Visible copy stays the short default. Mutation: render {missingLabel}
  // in the visible span (current :125) -> RED.
  it('data-missing: custom missingLabel is aria-only; visible span stays short default', () => {
    const { container } = render(<Avatar missingLabel="Representative image unavailable" />);

    const named = screen.getByRole('img', { name: 'Representative image unavailable' });
    expect(named).toHaveAccessibleName('Representative image unavailable');
    const visible = container.querySelector('.acx-avatar__missing-label');
    expect(visible).toHaveTextContent('No image');
    expect(visible).not.toHaveTextContent('Representative image unavailable');
    expect(screen.getByText('No image')).toBeInTheDocument();
    expect(screen.queryByRole('img', { name: 'No image' })).not.toBeInTheDocument();
  });

  it('data-missing: hideMissingLabel applies the Avatar hide modifier class', () => {
    const { container } = render(
      <Avatar hideMissingLabel missingLabel="Representative image unavailable" />,
    );

    const root = container.querySelector('[data-avatar-state="data-missing"]');
    expect(root).toHaveClass('acx-avatar--hide-missing-label');
    expect(container.querySelector('.acx-avatar__missing-label')).toHaveTextContent('No image');
  });

  it('data-missing: empty src is the explicit no-src branch, not error', () => {
    const { container } = render(<Avatar src="" alt="unused" />);

    const root = container.querySelector('[data-avatar-state]') as HTMLElement;
    expect(root).toHaveAttribute('data-avatar-state', 'data-missing');
    expect(root).not.toHaveAttribute('data-avatar-state', 'error');
    expect(screen.getByRole('img', { name: 'No image' })).toBeInTheDocument();
    expect(screen.queryByText('Image failed to load')).not.toBeInTheDocument();
  });

  it('error: src present and load failed sets data-avatar-state=error with sr-only failure text', () => {
    const { container } = render(
      <Avatar src="https://example.com/thumb.jpg?status=error" alt="Broken face" />,
    );

    const root = container.querySelector('[data-avatar-state]') as HTMLElement;
    expect(root).toHaveAttribute('data-avatar-state', AVATAR_STATES.error);
    expect(root).toHaveAttribute('data-avatar-state', 'error');

    expect(screen.getByText('Image failed to load')).toHaveClass('screen-reader-text');
    expect(container.querySelector('.acx-avatar__warning-icon')).not.toBeNull();
    expect(container.querySelector('.acx-avatar__broken-icon')).not.toBeNull();
    expect(screen.queryByText('No image')).not.toBeInTheDocument();
  });

  // E21-20-REV1-05 / TEST-15: passing the previous identity's loadStatus
  // through resolveAvatarState would yield real/error against the new src.
  // resolveAvatarRenderState must force idle on src change so the swap frame
  // is fallback-visible (loading), not the stale terminal state.
  it('swap frame: new src does not keep data-avatar-state=real from the previous identity', () => {
    const swapFrame = resolveAvatarRenderState(
      'https://example.com/b.jpg',
      'https://example.com/a.jpg',
      'loaded',
    );

    expect(['loading', 'idle', 'fallback-visible']).toContain(swapFrame);
    expect(swapFrame).toBe(AVATAR_STATES.loading);
    expect(swapFrame).not.toBe(AVATAR_STATES.real);
    expect(swapFrame).not.toBe(AVATAR_STATES.error);
  });

  it('swap frame: new src does not keep data-avatar-state=error from the previous identity', () => {
    const swapFrame = resolveAvatarRenderState(
      'https://example.com/b.jpg',
      'https://example.com/a.jpg',
      'error',
    );

    expect(['loading', 'idle', 'fallback-visible']).toContain(swapFrame);
    expect(swapFrame).toBe(AVATAR_STATES.loading);
    expect(swapFrame).not.toBe(AVATAR_STATES.error);
    expect(swapFrame).not.toBe(AVATAR_STATES.real);
  });

  // E21-20-REV2-07 / TEST-15: the REV1-05 cases only call the pure helper.
  // A component that stopped calling resolveAvatarRenderState and read the
  // stale loadStatus would keep those green. Rerender <Avatar> with a new
  // src that has not reported yet and assert the DOM is not the previous
  // identity's real/error frame.
  it('swap frame: rerendering Avatar with a new src does not keep data-avatar-state=real', () => {
    const { container, rerender } = render(
      <Avatar src="https://example.com/a.jpg?status=loaded" alt="Ada" />,
    );
    expect(container.querySelector('[data-avatar-state]')).toHaveAttribute(
      'data-avatar-state',
      AVATAR_STATES.real,
    );

    rerender(<Avatar src="https://example.com/b.jpg?status=hold" alt="Grace" />);
    const root = container.querySelector('[data-avatar-state]') as HTMLElement;
    expect(root).toHaveAttribute('data-avatar-state', AVATAR_STATES.loading);
    expect(root).not.toHaveAttribute('data-avatar-state', AVATAR_STATES.real);
    expect(root).not.toHaveAttribute('data-avatar-state', AVATAR_STATES.error);
  });

  it('swap frame: rerendering Avatar with a new src does not keep data-avatar-state=error', () => {
    const { container, rerender } = render(
      <Avatar src="https://example.com/a.jpg?status=error" alt="Broken" />,
    );
    expect(container.querySelector('[data-avatar-state]')).toHaveAttribute(
      'data-avatar-state',
      AVATAR_STATES.error,
    );

    rerender(<Avatar src="https://example.com/b.jpg?status=hold" alt="Grace" />);
    const root = container.querySelector('[data-avatar-state]') as HTMLElement;
    expect(root).toHaveAttribute('data-avatar-state', AVATAR_STATES.loading);
    expect(root).not.toHaveAttribute('data-avatar-state', AVATAR_STATES.error);
    expect(root).not.toHaveAttribute('data-avatar-state', AVATAR_STATES.real);
  });

  it('uses an external state override instead of the derived load status', () => {
    const { container } = render(
      <Avatar src="https://example.com/thumb.jpg?status=loading" alt="Owned" state={AVATAR_STATES.real} />,
    );
    const root = container.querySelector('[data-avatar-state]') as HTMLElement;
    expect(root).toHaveAttribute('data-avatar-state', AVATAR_STATES.real);
    expect(container.querySelector('.acx-avatar__skeleton')).toBeNull();
  });

  it('forwards onLoad and onError from onLoadingStatusChange', () => {
    const onLoad = vi.fn();
    const onError = vi.fn();
    const { rerender } = render(
      <Avatar src="https://example.com/thumb.jpg?status=loaded" alt="Loaded" onLoad={onLoad} onError={onError} />,
    );
    expect(onLoad).toHaveBeenCalledTimes(1);
    expect(onError).not.toHaveBeenCalled();

    rerender(
      <Avatar src="https://example.com/thumb.jpg?status=error" alt="Broken" onLoad={onLoad} onError={onError} />,
    );
    expect(onError).toHaveBeenCalledTimes(1);
    expect(onLoad).toHaveBeenCalledTimes(1);
  });
});
