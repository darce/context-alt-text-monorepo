import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { IdentityThumbnail } from '../IdentityThumbnail';
import type { ClusterIdentity } from '../../../api/recognition';

const identity: ClusterIdentity = {
  identity_id: 'identity-1',
  media_id: 100,
  similarity: 0.5,
  confidence: 0.8,
  bbox: { x: 0, y: 0, width: 20, height: 40 },
};

describe('IdentityThumbnail', () => {
  it('renders placeholder when no metadata is available', () => {
    const { container } = render(<IdentityThumbnail identity={identity} size={64} />);
    expect(container.querySelector('.acx-cluster-card__face--placeholder')).toBeInTheDocument();
  });

  it('uses backend-provided thumbnail when available', () => {
    render(<IdentityThumbnail identity={{ ...identity, thumb_url: 'https://example.com/thumb.jpg' }} size={96} />);
    const image = screen.getByRole('img');
    expect(image).toHaveAttribute('src', 'https://example.com/thumb.jpg');
  });

  it('calls onClick when provided', async () => {
    const onClick = vi.fn();
    // thumb_url path paints a real <img> immediately (no canvas-crop wait).
    render(
      <IdentityThumbnail
        identity={{ ...identity, thumb_url: 'https://example.com/thumb.jpg' }}
        onClick={onClick}
      />,
    );
    const thumb = screen.getByRole('img');
    await userEvent.click(thumb);
    expect(onClick).toHaveBeenCalled();
  });

  describe('lazy canvas crop [page-load]', () => {
    const OriginalImage = globalThis.Image;
    const OriginalIO = globalThis.IntersectionObserver;
    let imageConstructCount = 0;
    let observerCallback: IntersectionObserverCallback | null = null;

    beforeEach(() => {
      imageConstructCount = 0;
      observerCallback = null;

      class ControlledIntersectionObserver implements IntersectionObserver {
        readonly root: Element | Document | null = null;
        readonly rootMargin = '0px';
        readonly thresholds: readonly number[] = [0];
        constructor(callback: IntersectionObserverCallback) {
          observerCallback = callback;
        }
        observe(): void {
          // Deliberately do not auto-intersect — the test fires manually.
        }
        unobserve(): void {
          // no-op controlled stub
        }
        disconnect(): void {
          // no-op controlled stub
        }
        takeRecords(): IntersectionObserverEntry[] {
          return [];
        }
      }
      // ControlledIntersectionObserver satisfies the constructor shape; assign
      // without a redundant type assertion [sr-001].
      globalThis.IntersectionObserver = ControlledIntersectionObserver;

      class CountingImage {
        onload: ((this: GlobalEventHandlers, ev: Event) => unknown) | null = null;
        onerror: ((this: GlobalEventHandlers, ev: Event) => unknown) | null = null;
        crossOrigin = '';
        naturalWidth = 100;
        naturalHeight = 100;
        width = 100;
        height = 100;
        private _src = '';
        constructor() {
          imageConstructCount += 1;
        }
        get src(): string {
          return this._src;
        }
        set src(value: string) {
          this._src = value;
          queueMicrotask(() => {
            const handler = this.onload;
            if (handler) {
              handler.call(this as unknown as GlobalEventHandlers, new Event('load'));
            }
          });
        }
      }
      globalThis.Image = CountingImage as unknown as typeof Image;

      HTMLCanvasElement.prototype.getContext = vi.fn(() => ({
        clearRect: vi.fn(),
        drawImage: vi.fn(),
      })) as unknown as typeof HTMLCanvasElement.prototype.getContext;
      HTMLCanvasElement.prototype.toDataURL = vi.fn(() => 'data:image/jpeg;base64,cropped-face');
    });

    afterEach(() => {
      globalThis.Image = OriginalImage;
      globalThis.IntersectionObserver = OriginalIO;
      vi.restoreAllMocks();
    });

    it('does not construct Image before the host intersects', () => {
      render(
        <IdentityThumbnail
          identity={{
            media_id: 100,
            identity_id: 'identity-lazy',
            media_url: 'https://example.com/full-res.jpg',
            bbox: { x: 10, y: 20, width: 30, height: 40 },
          }}
          size={32}
        />,
      );

      // Discriminator for the "construct Image immediately" mutation: count stays 0
      // until intersection. Pending placeholder may expose role=img for a11y name
      // but must not be a real <img> element (no full-res download).
      expect(imageConstructCount).toBe(0);
      expect(document.querySelector('img')).toBeNull();
      expect(document.querySelector('[data-face-pending="true"]')).not.toBeNull();
    });

    it('constructs Image and paints a data: crop only after intersection', async () => {
      render(
        <IdentityThumbnail
          identity={{
            media_id: 100,
            identity_id: 'identity-lazy',
            media_url: 'https://example.com/full-res.jpg',
            bbox: { x: 10, y: 20, width: 30, height: 40 },
          }}
          size={32}
        />,
      );

      expect(imageConstructCount).toBe(0);

      // Async act returns a Thenable (satisfies await-thenable) and the inner
      // await satisfies require-await — without weakening any assertion [sr-001].
      await act(async () => {
        await Promise.resolve();
        const host = document.querySelector('[data-face-pending="true"]')?.parentElement;
        expect(host).toBeTruthy();
        if (!host) {
          return;
        }
        const entry: IntersectionObserverEntry = {
          isIntersecting: true,
          target: host,
          intersectionRatio: 1,
          time: 0,
          boundingClientRect: host.getBoundingClientRect(),
          intersectionRect: host.getBoundingClientRect(),
          rootBounds: null,
        };
        observerCallback?.([entry], {} as IntersectionObserver);
      });

      await waitFor(() => {
        expect(imageConstructCount).toBe(1);
        const img = screen.getByRole('img');
        expect(img.getAttribute('src')).toMatch(/^data:image\/jpeg/);
        expect(img).not.toHaveAttribute('src', 'https://example.com/full-res.jpg');
      });
    });

    it('does not construct Image for thumb_url path (no canvas crop)', () => {
      render(
        <IdentityThumbnail
          identity={{
            ...identity,
            thumb_url: 'https://example.com/thumb.jpg',
            media_url: 'https://example.com/full-res.jpg',
          }}
          size={32}
        />,
      );
      expect(imageConstructCount).toBe(0);
      expect(screen.getByRole('img')).toHaveAttribute('src', 'https://example.com/thumb.jpg');
    });

    it('pending crop inside a wrapping link keeps accessible name from default alt [A11Y-02]', () => {
      // Two distinct media_ids: the name must be derived per instance, so a
      // hardcoded aria-label string cannot satisfy both links.
      render(
        <>
          {[100, 207].map((mediaId) => (
            <a key={mediaId} href={`https://example.com/media/${mediaId}`}>
              <IdentityThumbnail
                identity={{
                  media_id: mediaId,
                  identity_id: `identity-lazy-${mediaId}`,
                  media_url: 'https://example.com/full-res.jpg',
                  bbox: { x: 10, y: 20, width: 30, height: 40 },
                }}
                size={32}
              />
            </a>
          ))}
        </>,
      );

      // Pending: no real <img src>, but the wrapping link must still have a name
      // (role=img + aria-label on the placeholder) — WCAG 2.4.4 / 4.1.2.
      expect(document.querySelectorAll('[data-face-pending="true"]')).toHaveLength(2);
      expect(document.querySelector('img')).toBeNull();

      const [first, second] = screen.getAllByRole('link');
      expect(first).toHaveAccessibleName(/Identity from media 100/);
      expect(second).toHaveAccessibleName(/Identity from media 207/);
    });

    it('pending crop with decorative alt="" stays aria-hidden and names nothing [A11Y-02]', () => {
      render(
        <a href="https://example.com/media/100">
          <IdentityThumbnail
            identity={{
              media_id: 100,
              identity_id: 'identity-lazy',
              media_url: 'https://example.com/full-res.jpg',
              bbox: { x: 10, y: 20, width: 30, height: 40 },
            }}
            alt=""
            size={32}
          />
        </a>,
      );

      const pending = document.querySelector('[data-face-pending="true"]');
      expect(pending).not.toBeNull();
      expect(pending).toHaveAttribute('aria-hidden', 'true');
      expect(pending).not.toHaveAttribute('role');
      expect(screen.getByRole('link')).toHaveAccessibleName('');
    });

    /**
     * [S6-BR-01] When the representative identity changes on the same component
     * instance (EditableRow is keyed only by entry.id), the previous crop's
     * data: URL must not remain painted under the new identity's data attributes.
     */
    it('clears the previous data: crop when identity media/bbox changes [S6-BR-01]', async () => {
      const firstCrop = 'data:image/jpeg;base64,FIRST-PERSON-CROP';
      const secondCrop = 'data:image/jpeg;base64,SECOND-PERSON-CROP';
      let cropSequence = 0;
      HTMLCanvasElement.prototype.toDataURL = vi.fn(() => {
        cropSequence += 1;
        return cropSequence === 1 ? firstCrop : secondCrop;
      });

      const firstIdentity = {
        media_id: 100,
        identity_id: 'identity-first',
        media_url: 'https://example.com/person-a.jpg',
        bbox: { x: 10, y: 20, width: 30, height: 40 },
      };
      const secondIdentity = {
        media_id: 200,
        identity_id: 'identity-second',
        media_url: 'https://example.com/person-b.jpg',
        bbox: { x: 5, y: 5, width: 50, height: 50 },
      };

      const fireIntersect = () => {
        const host =
          document.querySelector('[data-face-pending="true"]')?.parentElement ??
          document.querySelector('.acx-cluster-card__thumb')?.parentElement;
        expect(host).toBeTruthy();
        if (!host) {
          return;
        }
        const entry: IntersectionObserverEntry = {
          isIntersecting: true,
          target: host,
          intersectionRatio: 1,
          time: 0,
          boundingClientRect: host.getBoundingClientRect(),
          intersectionRect: host.getBoundingClientRect(),
          rootBounds: null,
        };
        observerCallback?.([entry], {} as IntersectionObserver);
      };

      const { rerender } = render(<IdentityThumbnail identity={firstIdentity} size={32} />);

      await act(async () => {
        await Promise.resolve();
        fireIntersect();
      });

      await waitFor(() => {
        const img = screen.getByRole('img');
        expect(img).toHaveAttribute('src', firstCrop);
        expect(img).toHaveAttribute('data-identity-id', 'identity-first');
      });

      // Same instance, new representative (media_url + bbox + identity ids change).
      rerender(<IdentityThumbnail identity={secondIdentity} size={32} />);

      // Immediately after the prop change — and on every subsequent paint until
      // the new crop is ready — the previous person's data: URL must not appear.
      await waitFor(() => {
        const stale = document.querySelector(`img[src="${firstCrop}"]`);
        expect(stale).toBeNull();
      });

      // data attributes already describe the new identity (or pending placeholder).
      const pendingOrImg =
        document.querySelector('[data-face-pending="true"]') ??
        document.querySelector('img[data-identity-id="identity-second"]');
      expect(pendingOrImg).not.toBeNull();

      await waitFor(() => {
        const img = screen.getByRole('img');
        expect(img).toHaveAttribute('src', secondCrop);
        expect(img).toHaveAttribute('data-identity-id', 'identity-second');
        expect(img).toHaveAttribute('data-media-id', '200');
        expect(img.getAttribute('src')).not.toBe(firstCrop);
      });
    });

    /**
     * [S6-BR-02] Between intersection and crop-ready the face column must not
     * paint (or fetch) the full uncropped scene via media_url.
     */
    it('keeps placeholder until crop is ready after intersection [S6-BR-02]', async () => {
      const pendingLoads: (() => void)[] = [];

      class DelayedImage {
        onload: ((this: GlobalEventHandlers, ev: Event) => unknown) | null = null;
        onerror: ((this: GlobalEventHandlers, ev: Event) => unknown) | null = null;
        crossOrigin = '';
        naturalWidth = 100;
        naturalHeight = 100;
        width = 100;
        height = 100;
        private _src = '';
        constructor() {
          imageConstructCount += 1;
        }
        get src(): string {
          return this._src;
        }
        set src(value: string) {
          this._src = value;
          // Do not auto-fire onload — test controls the crop latency window.
          pendingLoads.push(() => {
            const handler = this.onload;
            if (handler) {
              handler.call(this as unknown as GlobalEventHandlers, new Event('load'));
            }
          });
        }
      }
      globalThis.Image = DelayedImage as unknown as typeof Image;

      const mediaUrl = 'https://example.com/full-scene-uncropped.jpg';
      render(
        <IdentityThumbnail
          identity={{
            media_id: 100,
            identity_id: 'identity-crop-window',
            media_url: mediaUrl,
            bbox: { x: 10, y: 20, width: 30, height: 40 },
          }}
          size={32}
        />,
      );

      expect(document.querySelector('img')).toBeNull();

      await act(async () => {
        await Promise.resolve();
        const host = document.querySelector('[data-face-pending="true"]')?.parentElement;
        expect(host).toBeTruthy();
        if (!host) {
          return;
        }
        const entry: IntersectionObserverEntry = {
          isIntersecting: true,
          target: host,
          intersectionRatio: 1,
          time: 0,
          boundingClientRect: host.getBoundingClientRect(),
          intersectionRect: host.getBoundingClientRect(),
          rootBounds: null,
        };
        observerCallback?.([entry], {} as IntersectionObserver);
      });

      // Image construction starts, but onload has not fired yet.
      await waitFor(() => {
        expect(imageConstructCount).toBe(1);
        expect(pendingLoads.length).toBe(1);
      });

      // Critical window: no real <img> may paint the full-scene media_url.
      expect(document.querySelector(`img[src="${mediaUrl}"]`)).toBeNull();
      expect(document.querySelector('img')).toBeNull();
      expect(document.querySelector('[data-face-pending="true"]')).not.toBeNull();

      await act(async () => {
        pendingLoads[0]?.();
        await Promise.resolve();
      });

      await waitFor(() => {
        const img = screen.getByRole('img');
        expect(img.getAttribute('src')).toMatch(/^data:image\/jpeg/);
        expect(img).not.toHaveAttribute('src', mediaUrl);
      });
    });

    /**
     * [S8-BR-01] Zero-area bbox is schema-legal but must not enter the canvas
     * crop path (NaN dest size → blank toDataURL square).
     */
    it('does not canvas-crop a zero-area bbox; falls through to media_url [S8-BR-01]', async () => {
      const mediaUrl = 'https://example.com/zero-bbox-scene.jpg';
      const toDataURL = vi.fn(() => 'data:image/jpeg;base64,BLANK-ZERO-AREA');
      HTMLCanvasElement.prototype.toDataURL = toDataURL;

      render(
        <IdentityThumbnail
          identity={{
            media_id: 300,
            identity_id: 'identity-zero-bbox',
            media_url: mediaUrl,
            bbox: { x: 0, y: 0, width: 0, height: 0 },
          }}
          size={32}
        />,
      );

      // Zero-area must not arm the canvas-crop Image path at all.
      expect(imageConstructCount).toBe(0);
      expect(toDataURL).not.toHaveBeenCalled();
      // Must not be stuck in a pending-crop placeholder either.
      expect(document.querySelector('[data-face-pending="true"]')).toBeNull();

      // Even if something later tries to "intersect", crop must stay disabled.
      await act(async () => {
        await Promise.resolve();
        const host =
          document.querySelector('.acx-cluster-card__face--placeholder')?.parentElement ??
          document.querySelector('.acx-cluster-card__thumb')?.parentElement;
        if (host && observerCallback) {
          const entry: IntersectionObserverEntry = {
            isIntersecting: true,
            target: host,
            intersectionRatio: 1,
            time: 0,
            boundingClientRect: host.getBoundingClientRect(),
            intersectionRect: host.getBoundingClientRect(),
            rootBounds: null,
          };
          observerCallback([entry], {} as IntersectionObserver);
        }
      });

      await waitFor(() => {
        expect(imageConstructCount).toBe(0);
        expect(toDataURL).not.toHaveBeenCalled();
        expect(document.querySelector('img[src^="data:"]')).toBeNull();
        expect(document.querySelector('img[src="data:image/jpeg;base64,BLANK-ZERO-AREA"]')).toBeNull();
        // Untouched full media (or non-pending placeholder) — never a blank crop.
        const img = document.querySelector('img');
        if (img) {
          expect(img).toHaveAttribute('src', mediaUrl);
        } else {
          expect(document.querySelector('.acx-cluster-card__face--placeholder')).not.toBeNull();
          expect(document.querySelector('[data-face-pending="true"]')).toBeNull();
        }
      });
    });
  });
});
