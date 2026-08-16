import { render, screen, fireEvent, waitFor } from '@testing-library/react';
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
      const { rerender } = render(
        <FaceThumbnail mediaUrl={mockMediaUrl} bbox={mockBbox} loading="lazy" />,
      );
      expect(screen.getByRole('img')).toHaveAttribute('loading', 'lazy');

      rerender(<FaceThumbnail mediaUrl={mockMediaUrl} bbox={mockBbox} loading="eager" />);
      expect(screen.getByRole('img')).toHaveAttribute('loading', 'eager');

      rerender(<FaceThumbnail mediaUrl={mockMediaUrl} bbox={mockBbox} />);
      expect(screen.getByRole('img')).not.toHaveAttribute('loading');
    });

    it('shows accessible error message on load failure', async () => {
      render(<FaceThumbnail mediaUrl="invalid-url" bbox={mockBbox} />);
      const img = screen.getByRole('img');
      fireEvent.error(img);

      await waitFor(() => {
        const errorContainer = screen.getByRole('img', { name: 'Face image unavailable' });
        expect(errorContainer).toBeInTheDocument();
      });
    });
  });

  describe('loading states', () => {
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
        expect(wrapper.querySelector('.acx-face-thumbnail__error-label')).toHaveTextContent(
          'Face image unavailable',
        );
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
