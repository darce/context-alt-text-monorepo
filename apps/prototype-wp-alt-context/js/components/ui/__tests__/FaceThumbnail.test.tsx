import * as React from 'react';
import { act, render, screen, fireEvent, waitFor } from '@testing-library/react';
import { vi, describe, it, expect, beforeEach } from 'vitest';

import { FaceThumbnail } from '../FaceThumbnail';
import type { BoundingBox } from '../../../admin/api/recognition/types/identity';

const mockBbox: BoundingBox = {
  x: 100,
  y: 50,
  width: 200,
  height: 200,
};

const mockMediaUrl = 'https://example.com/photo.jpg';

describe('FaceThumbnail', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe('rendering', () => {
    it('renders with default size (md = 48px)', () => {
      const { container } = render(<FaceThumbnail mediaUrl={mockMediaUrl} bbox={mockBbox} />);
      const wrapper = container.firstChild as HTMLElement;
      expect(wrapper).toHaveStyle({ width: '48px', height: '48px' });
    });

    it('renders with small size (32px)', () => {
      const { container } = render(<FaceThumbnail mediaUrl={mockMediaUrl} bbox={mockBbox} size="sm" />);
      const wrapper = container.firstChild as HTMLElement;
      expect(wrapper).toHaveStyle({ width: '32px', height: '32px' });
    });

    it('renders with large size (64px)', () => {
      const { container } = render(<FaceThumbnail mediaUrl={mockMediaUrl} bbox={mockBbox} size="lg" />);
      const wrapper = container.firstChild as HTMLElement;
      expect(wrapper).toHaveStyle({ width: '64px', height: '64px' });
    });

    it('applies correct BEM classes', () => {
      const { container } = render(<FaceThumbnail mediaUrl={mockMediaUrl} bbox={mockBbox} size="md" />);
      const wrapper = container.firstChild as HTMLElement;
      expect(wrapper).toHaveClass('acx-face-thumbnail');
      expect(wrapper).toHaveClass('acx-face-thumbnail--md');
    });

    it('applies custom className', () => {
      const { container } = render(<FaceThumbnail mediaUrl={mockMediaUrl} bbox={mockBbox} className="custom-class" />);
      const wrapper = container.firstChild as HTMLElement;
      expect(wrapper).toHaveClass('custom-class');
    });
  });

  describe('CSS transform calculations', () => {
    it('calculates correct scale for square bbox', () => {
      // bbox is 200x200, display size is 48 (md)
      // scale = 48 / max(200, 200) = 48 / 200 = 0.24
      render(<FaceThumbnail mediaUrl={mockMediaUrl} bbox={mockBbox} size="md" />);
      const img = screen.getByRole('img');
      const style = img.getAttribute('style') ?? '';
      expect(style).toContain('scale(0.24)');
    });

    it('calculates correct scale for tall bbox', () => {
      const tallBbox: BoundingBox = { x: 0, y: 0, width: 100, height: 200 };
      // scale = 48 / max(100, 200) = 48 / 200 = 0.24
      render(<FaceThumbnail mediaUrl={mockMediaUrl} bbox={tallBbox} size="md" />);
      const img = screen.getByRole('img');
      const style = img.getAttribute('style') ?? '';
      expect(style).toContain('scale(0.24)');
    });

    it('calculates correct scale for wide bbox', () => {
      const wideBbox: BoundingBox = { x: 0, y: 0, width: 200, height: 100 };
      // scale = 48 / max(200, 100) = 48 / 200 = 0.24
      render(<FaceThumbnail mediaUrl={mockMediaUrl} bbox={wideBbox} size="md" />);
      const img = screen.getByRole('img');
      const style = img.getAttribute('style') ?? '';
      expect(style).toContain('scale(0.24)');
    });
  });

  describe('accessibility', () => {
    it('uses provided alt text', () => {
      render(<FaceThumbnail mediaUrl={mockMediaUrl} bbox={mockBbox} alt="John Doe" />);
      const img = screen.getByRole('img');
      expect(img).toHaveAttribute('alt', 'John Doe');
    });

    it('uses default alt text when not provided', () => {
      render(<FaceThumbnail mediaUrl={mockMediaUrl} bbox={mockBbox} />);
      const img = screen.getByRole('img');
      expect(img).toHaveAttribute('alt', 'Detected face');
    });

    it('forwards loading prop to the img and omits the attribute when unset', () => {
      const { rerender } = render(<FaceThumbnail mediaUrl={mockMediaUrl} bbox={mockBbox} loading="lazy" />);
      expect(screen.getByRole('img')).toHaveAttribute('loading', 'lazy');

      rerender(<FaceThumbnail mediaUrl={mockMediaUrl} bbox={mockBbox} loading="eager" />);
      expect(screen.getByRole('img')).toHaveAttribute('loading', 'eager');

      rerender(<FaceThumbnail mediaUrl={mockMediaUrl} bbox={mockBbox} />);
      expect(screen.getByRole('img')).not.toHaveAttribute('loading');
    });

    it('preserves the caller alt text in the accessible error message', async () => {
      render(<FaceThumbnail mediaUrl="invalid-url" bbox={mockBbox} alt="Face on the left" />);
      const img = screen.getByRole('img', { name: 'Face on the left' });
      fireEvent.error(img);

      await waitFor(() => {
        const errorContainer = screen.getByRole('img', { name: 'Face image unavailable. Face on the left' });
        expect(errorContainer).toBeInTheDocument();
      });
    });
  });

  describe('loading states', () => {
    it('paints loading on the first commit after a loaded source changes', () => {
      const observations: string[] = [];
      function Probe({ source }: { source: string }) {
        const ref = React.useRef<HTMLDivElement>(null);
        React.useLayoutEffect(() => {
          observations.push(ref.current?.querySelector('img')?.style.opacity ?? 'missing');
        }, [source]);
        return <FaceThumbnail ref={ref} mediaUrl={source} bbox={mockBbox} />;
      }
      const { rerender } = render(<Probe source={mockMediaUrl} />);
      fireEvent.load(screen.getByRole('img'));
      rerender(<Probe source="/recognition/next.jpg" />);
      expect(observations).toEqual(['0', '0']);
    });

    it('ignores retained load and error handlers from the previous source', () => {
      const onLoad = vi.fn();
      const onError = vi.fn();
      const { rerender } = render(
        <FaceThumbnail mediaUrl={mockMediaUrl} bbox={mockBbox} onLoad={onLoad} onError={onError} />,
      );
      const previousImg = screen.getByRole('img');
      // Retain the actual handlers: dispatching on a detached node skips React delegation.
      const propsKey = Object.keys(previousImg).find((key) => key.startsWith('__reactProps$'));
      if (!propsKey) {
        throw new Error('React image event props were not found');
      }
      const props = (
        previousImg as unknown as Record<
          string,
          {
            onLoad: React.ReactEventHandler<HTMLImageElement>;
            onError: React.ReactEventHandler<HTMLImageElement>;
          }
        >
      )[propsKey];
      rerender(<FaceThumbnail mediaUrl="/recognition/next.jpg" bbox={mockBbox} onLoad={onLoad} onError={onError} />);
      const staleEvent = { currentTarget: previousImg } as React.SyntheticEvent<HTMLImageElement>;
      act(() => props.onLoad(staleEvent));
      expect(screen.getByRole('img')).toHaveStyle({ opacity: '0' });
      fireEvent.load(screen.getByRole('img'));
      act(() => props.onError(staleEvent));
      expect(screen.getByRole('img')).toHaveStyle({ opacity: '1' });
      expect(onLoad).toHaveBeenCalledOnce();
      expect(onError).not.toHaveBeenCalled();
    });

    it('shows loading state initially', () => {
      const { container } = render(<FaceThumbnail mediaUrl={mockMediaUrl} bbox={mockBbox} />);
      const wrapper = container.firstChild as HTMLElement;
      expect(wrapper).toHaveClass('acx-face-thumbnail--loading');
    });

    it('shows placeholder while loading', () => {
      const { container } = render(<FaceThumbnail mediaUrl={mockMediaUrl} bbox={mockBbox} />);
      const placeholder = container.querySelector('.acx-face-thumbnail__placeholder');
      expect(placeholder).toBeInTheDocument();
    });

    it('removes loading class after image loads', async () => {
      const { container } = render(<FaceThumbnail mediaUrl={mockMediaUrl} bbox={mockBbox} />);
      const img = screen.getByRole('img');
      fireEvent.load(img);

      await waitFor(() => {
        const wrapper = container.firstChild as HTMLElement;
        expect(wrapper).not.toHaveClass('acx-face-thumbnail--loading');
      });
    });

    it('shows image after load', async () => {
      render(<FaceThumbnail mediaUrl={mockMediaUrl} bbox={mockBbox} />);
      const img = screen.getByRole('img');

      // Before load, image is hidden
      expect(img).toHaveStyle({ opacity: '0' });

      fireEvent.load(img);

      await waitFor(() => {
        expect(img).toHaveStyle({ opacity: '1' });
      });
    });

    it('shows image when browser cache marks image complete before load event fires', async () => {
      const completeSpy = vi.spyOn(HTMLImageElement.prototype, 'complete', 'get').mockReturnValue(true);
      const naturalWidthSpy = vi.spyOn(HTMLImageElement.prototype, 'naturalWidth', 'get').mockReturnValue(640);

      const { container } = render(<FaceThumbnail mediaUrl={mockMediaUrl} bbox={mockBbox} />);
      const img = screen.getByRole('img');

      await waitFor(() => {
        const wrapper = container.firstChild as HTMLElement;
        expect(wrapper).not.toHaveClass('acx-face-thumbnail--loading');
        expect(img).toHaveStyle({ opacity: '1' });
      });

      completeSpy.mockRestore();
      naturalWidthSpy.mockRestore();
    });
  });

  describe('error states', () => {
    it('shows error state when image fails to load', async () => {
      const { container } = render(<FaceThumbnail mediaUrl="bad-url" bbox={mockBbox} />);
      const img = screen.getByRole('img');
      fireEvent.error(img);

      await waitFor(() => {
        const wrapper = container.firstChild as HTMLElement;
        expect(wrapper).toHaveClass('acx-face-thumbnail--error');
        expect(wrapper.querySelector('.acx-face-thumbnail__warning-icon')).not.toBeNull();
        expect(wrapper.querySelector('.acx-face-thumbnail__broken-icon')).not.toBeNull();
        expect(wrapper.querySelector('.acx-face-thumbnail__error-label')).toHaveTextContent('Face image unavailable');
      });
    });

    it('hides the broken image on error', async () => {
      const { container } = render(<FaceThumbnail mediaUrl="bad-url" bbox={mockBbox} />);
      const img = screen.getByRole('img');
      fireEvent.error(img);

      await waitFor(() => {
        // After error, the img element is replaced with the error div
        expect(container.querySelector('img')).not.toBeInTheDocument();
      });
    });

    it('loads a relative media URL', () => {
      const onLoad = vi.fn();
      const { container } = render(<FaceThumbnail mediaUrl="/recognition/face.jpg" bbox={mockBbox} onLoad={onLoad} />);

      fireEvent.load(screen.getByRole('img'));

      expect(container.firstChild).not.toHaveClass('acx-face-thumbnail--loading');
      expect(screen.getByRole('img')).toHaveStyle({ opacity: '1' });
      expect(onLoad).toHaveBeenCalledOnce();
    });

    it('remounts the image and resets loading after a source swap', () => {
      const onLoad = vi.fn();
      const onError = vi.fn();
      const { container, rerender } = render(
        <FaceThumbnail mediaUrl={mockMediaUrl} bbox={mockBbox} onLoad={onLoad} onError={onError} />,
      );
      const previousImg = screen.getByRole('img');
      fireEvent.load(previousImg);
      expect(previousImg).toHaveStyle({ opacity: '1' });
      onLoad.mockClear();

      rerender(<FaceThumbnail mediaUrl="/recognition/next.jpg" bbox={mockBbox} onLoad={onLoad} onError={onError} />);
      const nextImg = screen.getByRole('img');
      expect(nextImg).not.toBe(previousImg);
      expect(previousImg).not.toBeInTheDocument();
      expect(container.firstChild).toHaveClass('acx-face-thumbnail--loading');
      expect(nextImg).toHaveStyle({ opacity: '0' });

      fireEvent.error(previousImg);
      fireEvent.load(previousImg);
      expect(container.firstChild).toHaveClass('acx-face-thumbnail--loading');
      expect(onLoad).not.toHaveBeenCalled();
      expect(onError).not.toHaveBeenCalled();

      fireEvent.load(nextImg);
      expect(container.firstChild).not.toHaveClass('acx-face-thumbnail--loading');
      expect(nextImg).toHaveStyle({ opacity: '1' });
      expect(onLoad).toHaveBeenCalledOnce();
    });

    it('resets an error to loading when the source changes', () => {
      const onError = vi.fn();
      const { container, rerender } = render(
        <FaceThumbnail mediaUrl={mockMediaUrl} bbox={mockBbox} onError={onError} />,
      );
      fireEvent.error(screen.getByRole('img'));
      expect(container.firstChild).toHaveClass('acx-face-thumbnail--error');
      expect(onError).toHaveBeenCalledOnce();

      rerender(<FaceThumbnail mediaUrl="/recognition/next.jpg" bbox={mockBbox} />);
      expect(container.firstChild).toHaveClass('acx-face-thumbnail--loading');
      expect(container.firstChild).not.toHaveClass('acx-face-thumbnail--error');
      const nextImg = screen.getByRole('img');
      expect(nextImg).toHaveAttribute('src', '/recognition/next.jpg');
      fireEvent.load(nextImg);
      expect(nextImg).toHaveStyle({ opacity: '1' });
    });
  });

  describe('forwardRef', () => {
    it('forwards ref to the container div', () => {
      const ref = vi.fn();
      render(<FaceThumbnail mediaUrl={mockMediaUrl} bbox={mockBbox} ref={ref} />);
      expect(ref).toHaveBeenCalled();
      expect(ref.mock.calls[0][0]).toBeInstanceOf(HTMLDivElement);
    });
  });
});
