import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

import { FaceLightbox } from '../FaceLightbox';
import { ReviewCardLightbox } from '../../../admin/pages/workbench/identity-clusters/ReviewCardLightbox';
import type { BoundingBox } from '../../../admin/api/recognition/types/identity';

const bbox: BoundingBox = { x: 10, y: 20, width: 40, height: 50 };
const mediaUrl = 'https://example.com/face-source.jpg';

describe('FaceLightbox', () => {
  let resizeObserverCallback: ResizeObserverCallback | null = null;

  beforeEach(() => {
    resizeObserverCallback = null;
    vi.stubGlobal(
      'ResizeObserver',
      class {
        constructor(cb: ResizeObserverCallback) {
          resizeObserverCallback = cb;
        }
        observe(): void {
          if (resizeObserverCallback) {
            resizeObserverCallback([], this);
          }
        }
        unobserve(): void {
          return undefined;
        }
        disconnect(): void {
          return undefined;
        }
      },
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('opens with dialog accessible name and closes via Close', async () => {
    const user = userEvent.setup();
    const onOpenChange = vi.fn();

    const { rerender } = render(
      <FaceLightbox
        open
        onOpenChange={onOpenChange}
        mediaUrl={mediaUrl}
        bbox={bbox}
        label="Alice face"
      />,
    );

    expect(screen.getByRole('dialog', { name: 'Original media with face highlight' })).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Close' }));
    expect(onOpenChange).toHaveBeenCalledWith(false);

    rerender(
      <FaceLightbox
        open={false}
        onOpenChange={onOpenChange}
        mediaUrl={mediaUrl}
        bbox={bbox}
        label="Alice face"
      />,
    );
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('renders bbox overlay rect after image load', async () => {
    render(<FaceLightbox open onOpenChange={vi.fn()} mediaUrl={mediaUrl} bbox={bbox} label="Face" />);

    const frame = document.querySelector('.acx-review-card-lightbox__frame');
    expect(frame).toBeInstanceOf(HTMLElement);
    Object.defineProperty(frame, 'clientWidth', { configurable: true, value: 400 });
    Object.defineProperty(frame, 'clientHeight', { configurable: true, value: 300 });
    if (resizeObserverCallback) {
      resizeObserverCallback([], {} as ResizeObserver);
    }

    const img = screen.getByRole('img', { name: 'Face' });
    Object.defineProperty(img, 'naturalWidth', { configurable: true, value: 200 });
    Object.defineProperty(img, 'naturalHeight', { configurable: true, value: 150 });
    fireEvent.load(img);

    await waitFor(() => {
      expect(document.querySelector('.acx-review-card-lightbox__bbox')).toBeInTheDocument();
    });
  });
});

describe('ReviewCardLightbox shim', () => {
  it('renders FaceLightbox via shim import path', () => {
    render(
      <ReviewCardLightbox
        open
        onOpenChange={vi.fn()}
        mediaUrl={mediaUrl}
        bbox={bbox}
        label="Shim face"
      />,
    );

    expect(screen.getByRole('dialog', { name: 'Original media with face highlight' })).toBeInTheDocument();
    expect(document.querySelector('.acx-review-card-lightbox')).toBeInTheDocument();
  });
});
