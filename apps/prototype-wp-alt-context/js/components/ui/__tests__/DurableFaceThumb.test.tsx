import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import type { BoundingBox } from '../../../admin/api/recognition/types/identity';
import { DurableFaceThumb } from '../DurableFaceThumb';

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
}));

vi.mock('@radix-ui/react-avatar', async () => {
  const ReactMod = await import('react');
  return {
    Root: ReactMod.forwardRef(function MockRoot({ children, ...props }: Record<string, unknown>, ref: unknown) {
      return ReactMod.createElement(
        'span',
        { ...props, ref } as React.HTMLAttributes<HTMLSpanElement>,
        children as React.ReactNode,
      );
    }),
    Image: ReactMod.forwardRef(function MockImage(props: Record<string, unknown>, ref: unknown) {
      return ReactMod.createElement('img', { ...props, ref } as React.ImgHTMLAttributes<HTMLImageElement>);
    }),
    Fallback: ReactMod.forwardRef(function MockFallback() {
      return null;
    }),
  };
});

const BBOX: BoundingBox = { x: 10, y: 20, width: 40, height: 50 };
const BLOB_URL = 'https://example.test/wp-json/acx/v1/recognition/face-thumbs/job-1/50';
const ATTACHMENT_URL = 'https://example.test/uploads/50.jpg';

describe('DurableFaceThumb [TEST-15]', () => {
  it('blob-error → attachment-bbox-crop fallback renders WITHOUT --error', async () => {
    const { container } = render(
      <DurableFaceThumb
        source={{ thumbUrl: BLOB_URL, attachmentUrl: ATTACHMENT_URL, bbox: BBOX }}
        alt="Face to label"
      />,
    );

    fireEvent.error(screen.getByRole('img'));

    await waitFor(() => {
      expect(container.querySelector('[data-avatar-state="fallback-crop"]')).toBeInTheDocument();
    });

    const crop = screen.getByAltText('Face to label');
    expect(crop).toHaveAttribute('src', ATTACHMENT_URL);
    expect(crop.closest('.acx-face-thumbnail')).toBeInTheDocument();
    expect(container.querySelector('.acx-durable-face-thumb--error')).toBeNull();
    expect(container.querySelector('.acx-face-thumbnail--error')).toBeNull();
    expect(container.querySelector('[data-avatar-state="error"]')).toBeNull();
  });

  it("missing state (no attachment/bbox) renders quiet 'Representative image unavailable'", () => {
    const { container } = render(<DurableFaceThumb source={{}} />);

    expect(screen.getByRole('img', { name: 'Representative image unavailable' })).toBeInTheDocument();
    expect(screen.getByText('No image')).toBeInTheDocument();
    expect(container.querySelector('[data-avatar-state="missing"]')).toBeInTheDocument();
    expect(container.querySelector('.acx-durable-face-thumb--error')).toBeNull();
  });

  it('genuine network failure keeps loud --error', async () => {
    const { container } = render(
      <DurableFaceThumb source={{ thumbUrl: BLOB_URL, attachmentUrl: ATTACHMENT_URL, bbox: BBOX }} />,
    );

    fireEvent.error(screen.getByRole('img'));

    await waitFor(() => {
      expect(screen.getByAltText('Detected face')).toHaveAttribute('src', ATTACHMENT_URL);
    });

    fireEvent.error(screen.getByAltText('Detected face'));

    await waitFor(() => {
      expect(container.querySelector('[data-avatar-state="error"]')).toBeInTheDocument();
    });

    expect(container.querySelector('.acx-durable-face-thumb--error')).toBeInTheDocument();
    expect(screen.getByRole('img', { name: 'Image failed to load' })).toBeInTheDocument();
  });

  it('data-avatar-state distinguishes fallback-crop vs missing vs error', async () => {
    const { rerender, container } = render(
      <DurableFaceThumb source={{ thumbUrl: BLOB_URL, attachmentUrl: ATTACHMENT_URL, bbox: BBOX }} />,
    );
    fireEvent.error(screen.getByRole('img'));
    await waitFor(() => {
      expect(container.querySelector('[data-avatar-state="fallback-crop"]')).toBeInTheDocument();
    });

    rerender(<DurableFaceThumb source={{}} />);
    expect(container.querySelector('[data-avatar-state="missing"]')).toBeInTheDocument();

    rerender(<DurableFaceThumb source={{ thumbUrl: BLOB_URL }} />);
    fireEvent.error(screen.getByRole('img'));
    await waitFor(() => {
      expect(container.querySelector('[data-avatar-state="error"]')).toBeInTheDocument();
    });
  });
});
