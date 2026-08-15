import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import type { BoundingBox } from '../../../admin/api/recognition/types/identity';
import { DurableFaceThumb } from '../DurableFaceThumb';

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
  sprintf: (template: string, ...args: (string | number)[]) => {
    let index = 0;
    return template.replace(/%(\d+\$)?[sd]/g, () => String(args[index++] ?? ''));
  },
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
    Image: ReactMod.forwardRef(function MockImage(
      { onLoadingStatusChange, ...props }: Record<string, unknown>,
      ref: unknown,
    ) {
      return ReactMod.createElement('img', {
        ...(props as React.ImgHTMLAttributes<HTMLImageElement>),
        ref,
        onLoad: (event: React.SyntheticEvent<HTMLImageElement>) => {
          if (typeof onLoadingStatusChange === 'function') {
            onLoadingStatusChange('loaded');
          }
          const onLoad = props.onLoad as React.ReactEventHandler<HTMLImageElement> | undefined;
          onLoad?.(event);
        },
        onError: (event: React.SyntheticEvent<HTMLImageElement>) => {
          if (typeof onLoadingStatusChange === 'function') {
            onLoadingStatusChange('error');
          }
          const onError = props.onError as React.ReactEventHandler<HTMLImageElement> | undefined;
          onError?.(event);
        },
      } as React.ImgHTMLAttributes<HTMLImageElement>);
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
    expect(container.querySelector('[data-avatar-state="data-missing"]')).toBeInTheDocument();
    expect(container.querySelector('.acx-durable-face-thumb--error')).toBeNull();
  });

  it('hideMissingLabel adds modifier class and keeps the accessible name', () => {
    const { container } = render(<DurableFaceThumb source={{}} hideMissingLabel />);

    expect(screen.getByRole('img', { name: 'Representative image unavailable' })).toBeInTheDocument();
    expect(container.querySelector('.acx-durable-face-thumb--hide-missing-label')).toBeInTheDocument();
  });

  it('missing state accessible names differ when callers pass distinct alts', () => {
    const { rerender } = render(<DurableFaceThumb source={{}} alt="Detected face (first cluster)" />);
    expect(screen.getByRole('img', { name: 'Detected face (first cluster) — image unavailable' })).toBeInTheDocument();

    rerender(<DurableFaceThumb source={{}} alt="Candidate face" />);
    expect(screen.getByRole('img', { name: 'Candidate face — image unavailable' })).toBeInTheDocument();
    expect(
      screen.queryByRole('img', { name: 'Detected face (first cluster) — image unavailable' }),
    ).not.toBeInTheDocument();
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
    expect(screen.getByText('Image failed to load')).toBeInTheDocument();
    expect(container.querySelector('.acx-durable-face-thumb__fallback-label')).toHaveTextContent(
      'Image failed to load',
    );
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
    expect(container.querySelector('[data-avatar-state="data-missing"]')).toBeInTheDocument();

    rerender(<DurableFaceThumb source={{ thumbUrl: BLOB_URL }} />);
    fireEvent.error(screen.getByRole('img'));
    await waitFor(() => {
      expect(container.querySelector('[data-avatar-state="error"]')).toBeInTheDocument();
    });
  });

  it('crops a non-dedicated attachment thumbUrl instead of painting it as an avatar [REV1-01]', () => {
    const { container } = render(
      <DurableFaceThumb
        source={{ thumbUrl: ATTACHMENT_URL, attachmentUrl: ATTACHMENT_URL, bbox: BBOX }}
        alt="Face to label"
      />,
    );

    const crop = screen.getByAltText('Face to label');
    expect(crop).toHaveAttribute('src', ATTACHMENT_URL);
    expect(crop.closest('.acx-face-thumbnail')).toBeInTheDocument();
    expect(container.querySelector('.acx-avatar')).toBeNull();
    expect(container.querySelector('[data-avatar-state="loading"]')).toBeInTheDocument();
  });

  it('renders a real uncropped img when mediaUrl has no croppable bbox [REV1-02]', () => {
    const { container } = render(
      <DurableFaceThumb
        source={{ mediaUrl: ATTACHMENT_URL, bbox: { x: 0, y: 0, width: 0, height: 0 } }}
        className="acx-findings-panel__preview"
      />,
    );

    const image = screen.getByAltText('Reference image');
    expect(image.tagName).toBe('IMG');
    expect(image).toHaveAttribute('src', ATTACHMENT_URL);
    expect(image).toHaveClass('acx-durable-face-thumb__uncropped');
    expect(container.querySelector('[data-avatar-state="uncropped"]')).toBeInTheDocument();
    expect(container.querySelector('.acx-durable-face-thumb--uncropped')).toBeInTheDocument();
    expect(container.querySelector('.acx-findings-panel__preview--uncropped')).toBeInTheDocument();
    expect(screen.queryByRole('img', { name: 'Representative image unavailable' })).not.toBeInTheDocument();
    expect(container.querySelector('.acx-face-thumbnail')).toBeNull();
  });

  it('uncropped hop uses uncroppedAlt when supplied and the default swap when omitted [REV4-06]', () => {
    const uncroppable = { mediaUrl: ATTACHMENT_URL, bbox: { x: 0, y: 0, width: 0, height: 0 } };
    const { rerender } = render(
      <DurableFaceThumb
        source={uncroppable}
        alt="Face image, possibly Ada Lovelace"
        uncroppedAlt="Reference image, possibly Ada Lovelace"
      />,
    );

    const labelled = screen.getByAltText('Reference image, possibly Ada Lovelace');
    expect(labelled).toHaveClass('acx-durable-face-thumb__uncropped');
    expect(screen.queryByAltText('Face image, possibly Ada Lovelace')).not.toBeInTheDocument();

    rerender(<DurableFaceThumb source={uncroppable} />);
    expect(screen.getByAltText('Reference image')).toHaveClass('acx-durable-face-thumb__uncropped');
  });

  it('fallback-crop applies a CSS translate/scale so the bbox fills the frame [REV1-13]', async () => {
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
    expect(crop.getAttribute('style')).toContain('translate(-4.799999999999999px, -19.2px)');
    expect(crop.getAttribute('style')).toContain('scale(0.96)');
    expect(crop.getAttribute('style')).toMatch(/transform-origin:\s*top left/);
  });

  it('a loaded dedicated blob stays real, not fallback-crop [REV1-13]', async () => {
    const { container } = render(
      <DurableFaceThumb
        source={{ thumbUrl: BLOB_URL, attachmentUrl: ATTACHMENT_URL, bbox: BBOX }}
        alt="Face to label"
      />,
    );

    fireEvent.load(screen.getByRole('img'));

    await waitFor(() => {
      expect(container.querySelector('.acx-durable-face-thumb')).toHaveAttribute('data-avatar-state', 'real');
    });

    expect(container.querySelector('.acx-durable-face-thumb')).not.toHaveAttribute(
      'data-avatar-state',
      'fallback-crop',
    );
    expect(container.querySelector('.acx-face-thumbnail')).toBeNull();
    expect(screen.getByRole('img')).toHaveAttribute('src', BLOB_URL);
  });
});
