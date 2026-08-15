import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { IdentityThumbnail, thumbnailCropOwnerId } from '../IdentityThumbnail';
import type { ClusterIdentity } from '../../../api/recognition';

const identity: ClusterIdentity = {
  identity_id: 'identity-1',
  media_id: 100,
  similarity: 0.5,
  confidence: 0.8,
  bbox: { x: 0, y: 0, width: 20, height: 40 },
};

const DEDICATED_THUMB = 'https://example.test/wp-content/uploads/recognition/face-thumbs/rep-1.jpg';
const ATTACHMENT_AS_THUMB = 'https://example.com/thumb.jpg';

/**
 * Interactive-element contract for !namedPending placeholders [A11Y-11][TEST-17].
 * Pins "must not be interactive" rather than a specific tagName (div vs span are
 * both valid; button / a[href] / input / role=button / contenteditable / tab-order
 * entries are not). Structural selector + tabIndex — not element identity.
 */
const INTERACTIVE_CONTROL_SELECTOR = [
  'button',
  'a[href]',
  'input',
  'select',
  'textarea',
  'summary',
  '[role="button"]',
  '[role="link"]',
  '[contenteditable]:not([contenteditable="false"])',
].join(', ');

const isInteractiveControl = (el: Element): boolean => {
  if (!(el instanceof HTMLElement)) {
    return false;
  }
  if (el.matches(INTERACTIVE_CONTROL_SELECTOR)) {
    return true;
  }
  // In the tab order (tabIndex >= 0) even without a matching tag/role.
  return el.tabIndex >= 0;
};

describe('thumbnailCropOwnerId', () => {
  it('includes bbox on assigned identities so a usability change invalidates the crop [E21-19-REV1-05]', () => {
    expect(
      thumbnailCropOwnerId({
        media_id: 100,
        identity_id: 'identity-first',
        bbox: { x: 10, y: 20, width: 30, height: 40 },
      }),
    ).toBe('identity-first:10,20,30,40');
    expect(
      thumbnailCropOwnerId({
        media_id: 100,
        identity_id: 'identity-first',
        bbox: { x: 0, y: 0, width: 0, height: 0 },
      }),
    ).toBe('identity-first:0,0,0,0');
    expect(
      thumbnailCropOwnerId({
        media_id: 100,
        identity_id: 'identity-first',
      }),
    ).toBe('identity-first:none');
    expect(
      thumbnailCropOwnerId({
        media_id: 200,
        identity_id: 'identity-second',
        bbox: { x: 10, y: 20, width: 30, height: 40 },
      }),
    ).toBe('identity-second:10,20,30,40');
  });

  it('folds bbox into the unassigned media fallback [E21-19-R2-BR-01]', () => {
    expect(
      thumbnailCropOwnerId({
        media_id: 100,
        bbox: { x: 10, y: 20, width: 30, height: 40 },
      }),
    ).toBe('media:100:10,20,30,40');
    expect(
      thumbnailCropOwnerId({
        media_id: 100,
        bbox: { x: 5, y: 5, width: 50, height: 50 },
      }),
    ).toBe('media:100:5,5,50,50');
    expect(
      thumbnailCropOwnerId({
        media_id: 100,
      }),
    ).toBe('media:100');
  });
});

describe('IdentityThumbnail', () => {
  it('renders placeholder when no metadata is available', () => {
    const { container } = render(<IdentityThumbnail identity={identity} size={64} />);
    expect(container.querySelector('.acx-cluster-card__face--placeholder')).toBeInTheDocument();
  });

  it('uses a dedicated face-thumb blob when available [REV1-07]', () => {
    render(<IdentityThumbnail identity={{ ...identity, thumb_url: DEDICATED_THUMB }} size={96} />);
    const image = screen.getByRole('img');
    expect(image).toHaveAttribute('src', DEDICATED_THUMB);
  });

  it('does not paint a non-dedicated attachment thumb_url as a face chip [REV1-07]', () => {
    render(
      <IdentityThumbnail
        identity={{
          ...identity,
          thumb_url: ATTACHMENT_AS_THUMB,
          attachment_url: 'https://example.com/full-res.jpg',
        }}
        size={96}
      />,
    );

    expect(document.querySelector('img')).toBeNull();
    expect(document.querySelector(`img[src="${ATTACHMENT_AS_THUMB}"]`)).toBeNull();
    expect(document.querySelector('[data-face-pending="true"]')).not.toBeNull();
  });

  it('calls onClick when provided', async () => {
    const onClick = vi.fn();
    // Dedicated thumb_url path paints a real <img> immediately (no canvas-crop wait).
    render(
      <IdentityThumbnail
        identity={{ ...identity, thumb_url: DEDICATED_THUMB }}
        onClick={onClick}
      />,
    );
    const thumb = screen.getByRole('img');
    await userEvent.click(thumb);
    expect(onClick).toHaveBeenCalled();
  });

  it('calls onClick on the canvas-crop pending placeholder [S3-BR-04]', async () => {
    const onClick = vi.fn();
    // No thumb_url → needsCanvasCrop; pending window has no real <img> yet.
    render(
      <IdentityThumbnail
        identity={{
          media_id: 100,
          identity_id: 'identity-crop-click',
          media_url: 'https://example.com/full-res.jpg',
          bbox: { x: 10, y: 20, width: 30, height: 40 },
        }}
        onClick={onClick}
      />,
    );

    const pending = document.querySelector('[data-face-pending="true"]');
    expect(pending).not.toBeNull();
    expect(document.querySelector('img')).toBeNull();

    // Native control (not a bare div) so the prop contract is keyboard-reachable
    // via focus + Enter/Space [A11Y-11] [A11Y-12]. Pointer click alone cannot
    // distinguish <button> from role=button div without tabIndex/onKeyDown.
    const control = screen.getByRole('button', {
      name: /Identity from media 100/,
    });
    await userEvent.click(control);
    expect(onClick, 'pending placeholder pointer activation fires onClick').toHaveBeenCalledTimes(
      1,
    );

    // After pointer activation, a real <button> retains focus; a role=button
    // div without tabIndex does not. Tab from a clean start to prove reachability.
    (document.activeElement as HTMLElement | null)?.blur();
    await userEvent.tab();
    expect(control, 'pending placeholder button is keyboard-focusable [A11Y-11]').toHaveFocus();
    await userEvent.keyboard('{Enter}');
    expect(
      onClick,
      'pending placeholder activates on Enter when focused [A11Y-12]',
    ).toHaveBeenCalledTimes(2);
  });

  /**
   * [WBUX-5-D-03] [WBUX-5-R2-01] When onClick is provided but the placeholder is
   * decorative (alt=""), do not render a hidden interactive control. Match the
   * non-onClick branch: aria-hidden div, not a button, not a tab stop, no click.
   * Hard pins only — no disjunctions that a named decorative button could pass.
   */
  it('onClick + decorative alt="" renders non-interactive aria-hidden div [A11Y-04][A11Y-11]', () => {
    const onClick = vi.fn();
    // Documented decorative usage (alt="") with the onClick placeholder branch.
    // media_id:0, no source → !resolvedSrc && onClick && !namedPending.
    render(<IdentityThumbnail identity={{ media_id: 0 }} alt="" onClick={onClick} />);

    const control = document.querySelector('.acx-cluster-card__face--placeholder');
    expect(control, 'decorative onClick path still renders a placeholder').not.toBeNull();
    if (!control) {
      return;
    }

    // Contract pin: not interactive — accepts div/span, rejects button/a/input/etc.
    // (tagName==='DIV' was an implementation pin; span is a11y-equivalent [TEST-17]).
    expect(
      isInteractiveControl(control),
      'must not be an interactive element when !namedPending [A11Y-11]',
    ).toBe(false);
    expect(control).toHaveAttribute('aria-hidden', 'true');
    expect(control.getAttribute('aria-label')).toBeNull();
    expect(control.getAttribute('role')).toBeNull();
    expect(
      (control as HTMLElement).tabIndex,
      'decorative placeholder must leave the tab order [A11Y-11]',
    ).toBeLessThan(0);
    expect(screen.queryByRole('button')).toBeNull();
  });

  /**
   * [WBUX-5-D-03] [WBUX-5-R2-03] Genuinely-missing media with onClick must use the
   * same non-interactive contract as decorative alt="" — not a hidden button that
   * still fires onClick. Hard pins; every assertion always runs (no nesting).
   */
  it('onClick + genuinely-missing media renders non-interactive aria-hidden div [A11Y-04][A11Y-11]', () => {
    const onClick = vi.fn();
    // No sourceUrl / thumb_url → data-face-missing path (not pending crop).
    render(<IdentityThumbnail identity={{ media_id: 0 }} onClick={onClick} />);

    const control = document.querySelector(
      '.acx-cluster-card__face--placeholder[data-face-missing="true"]',
    );
    expect(control, 'missing-media onClick path renders data-face-missing placeholder').not.toBeNull();
    if (!control) {
      return;
    }

    // Symmetric contract pins with the decorative arm — no disjunction, no nested if.
    expect(
      isInteractiveControl(control),
      'must not be an interactive element when !namedPending [A11Y-11]',
    ).toBe(false);
    expect(control).toHaveAttribute('aria-hidden', 'true');
    expect(control.getAttribute('aria-label')).toBeNull();
    expect(control.getAttribute('role')).toBeNull();
    expect(
      (control as HTMLElement).tabIndex,
      'missing-media placeholder must leave the tab order [A11Y-11]',
    ).toBeLessThan(0);
    expect(screen.queryByRole('button')).toBeNull();
  });

  it('onClick on non-interactive !namedPending placeholder does not fire the handler [WBUX-5-D-03]', async () => {
    const decorativeClick = vi.fn();
    const missingClick = vi.fn();

    const { unmount } = render(
      <IdentityThumbnail identity={{ media_id: 0 }} alt="" onClick={decorativeClick} />,
    );
    const decorative = document.querySelector('.acx-cluster-card__face--placeholder');
    expect(decorative).not.toBeNull();
    if (decorative) {
      await userEvent.click(decorative);
    }
    expect(
      decorativeClick,
      'decorative aria-hidden placeholder must not invoke onClick [A11Y-11]',
    ).not.toHaveBeenCalled();
    unmount();

    render(<IdentityThumbnail identity={{ media_id: 0 }} onClick={missingClick} />);
    const missing = document.querySelector(
      '.acx-cluster-card__face--placeholder[data-face-missing="true"]',
    );
    expect(missing).not.toBeNull();
    if (missing) {
      await userEvent.click(missing);
    }
    expect(
      missingClick,
      'missing-media aria-hidden placeholder must not invoke onClick [A11Y-11]',
    ).not.toHaveBeenCalled();
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

    it('does not construct Image for a dedicated face-thumb blob (no canvas crop) [REV1-07]', () => {
      render(
        <IdentityThumbnail
          identity={{
            ...identity,
            thumb_url: DEDICATED_THUMB,
            media_url: 'https://example.com/full-res.jpg',
          }}
          size={32}
        />,
      );
      expect(imageConstructCount).toBe(0);
      expect(screen.getByRole('img')).toHaveAttribute('src', DEDICATED_THUMB);
    });

    it('crops a non-dedicated attachment thumb_url instead of painting the scene [REV1-07]', () => {
      render(
        <IdentityThumbnail
          identity={{
            ...identity,
            thumb_url: ATTACHMENT_AS_THUMB,
            attachment_url: 'https://example.com/full-res.jpg',
          }}
          size={32}
        />,
      );
      expect(imageConstructCount).toBe(0);
      expect(document.querySelector('img')).toBeNull();
      expect(document.querySelector('[data-face-pending="true"]')).not.toBeNull();
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
     *
     * Controllable Image onload so we can observe the intermediate clear before
     * B resolves, and exercise the cancelled-flag race (slow A after B).
     */
    it('clears the previous data: crop when identity media/bbox changes [S6-BR-01]', async () => {
      const firstCrop = 'data:image/jpeg;base64,FIRST-PERSON-CROP';
      const secondCrop = 'data:image/jpeg;base64,SECOND-PERSON-CROP';
      let cropResult = firstCrop;
      HTMLCanvasElement.prototype.toDataURL = vi.fn(() => cropResult);

      // Hold onload until the test fires it — no queueMicrotask auto-resolve.
      const pendingLoads: (() => void)[] = [];
      class ControllableImage {
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
          pendingLoads.push(() => {
            const handler = this.onload;
            if (handler) {
              handler.call(this as unknown as GlobalEventHandlers, new Event('load'));
            }
          });
        }
      }
      globalThis.Image = ControllableImage as unknown as typeof Image;

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
        expect(imageConstructCount).toBe(1);
        expect(pendingLoads.length).toBe(1);
      });

      cropResult = firstCrop;
      await act(async () => {
        pendingLoads.shift()?.();
        await Promise.resolve();
      });

      await waitFor(() => {
        const img = screen.getByRole('img');
        expect(img).toHaveAttribute('src', firstCrop);
        expect(img).toHaveAttribute('data-identity-id', 'identity-first');
      });

      // Same instance, new representative — hold B's onload so the intermediate
      // clear is observable (not merely eventual consistency once B lands).
      const loadsBeforeB = pendingLoads.length;
      rerender(<IdentityThumbnail identity={secondIdentity} size={32} />);

      await act(async () => {
        await Promise.resolve();
      });

      // (a) Synchronously after the identity change, before B resolves:
      // previous face must be gone and pending placeholder must be painted.
      expect(document.querySelector(`img[src="${firstCrop}"]`)).toBeNull();
      expect(document.querySelector('[data-face-pending="true"]')).not.toBeNull();
      expect(document.querySelector('img[data-identity-id="identity-second"]')).toBeNull();
      expect(pendingLoads.length).toBeGreaterThan(loadsBeforeB);

      cropResult = secondCrop;
      await act(async () => {
        pendingLoads.shift()?.();
        await Promise.resolve();
      });

      await waitFor(() => {
        const img = screen.getByRole('img');
        expect(img).toHaveAttribute('src', secondCrop);
        expect(img).toHaveAttribute('data-identity-id', 'identity-second');
        expect(img).toHaveAttribute('data-media-id', '200');
        expect(img.getAttribute('src')).not.toBe(firstCrop);
      });
    });

    /**
     * [ROSTER-W-04] [WBUX-5-R2-S3-BR-01] [TEST-15]
     * The swap render must not paint the previous crop under the new
     * identity's data-* / alt. S6-BR-01 waits for effect cleanup and would
     * stay green while one frame still leaks.
     */
    it('does not paint the previous crop under the new identity on the swap render [ROSTER-W-04]', async () => {
      const firstCrop = 'data:image/jpeg;base64,OWNED-BY-FIRST';
      const secondCrop = 'data:image/jpeg;base64,OWNED-BY-SECOND';
      let cropResult = firstCrop;
      HTMLCanvasElement.prototype.toDataURL = vi.fn(() => cropResult);

      const pendingLoads: (() => void)[] = [];
      class ControllableImage {
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
          pendingLoads.push(() => {
            const handler = this.onload;
            if (handler) {
              handler.call(this as unknown as GlobalEventHandlers, new Event('load'));
            }
          });
        }
      }
      globalThis.Image = ControllableImage as unknown as typeof Image;

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
        expect(pendingLoads.length).toBe(1);
      });

      cropResult = firstCrop;
      await act(async () => {
        pendingLoads.shift()?.();
        await Promise.resolve();
      });

      await waitFor(() => {
        const img = screen.getByRole('img');
        expect(img).toHaveAttribute('src', firstCrop);
        expect(img).toHaveAttribute('data-identity-id', 'identity-first');
      });

      const painted: string[] = [];
      const recordImg = (node: Node) => {
        if (!(node instanceof HTMLImageElement)) {
          return;
        }
        painted.push(
          `${node.getAttribute('src')}|${node.getAttribute('data-identity-id')}|${node.getAttribute('data-media-id')}`,
        );
      };
      const host =
        document.querySelector('.acx-cluster-card__thumb')?.parentElement ?? document.body;
      const observer = new MutationObserver(() => {
        // Records are drained synchronously via takeRecords() after rerender.
      });
      observer.observe(host, {
        subtree: true,
        childList: true,
        attributes: true,
        attributeFilter: ['src', 'alt', 'data-identity-id', 'data-media-id'],
      });

      rerender(<IdentityThumbnail identity={secondIdentity} size={32} />);
      observer.takeRecords().forEach((mutation) => {
        if (mutation.type === 'attributes' && mutation.target instanceof HTMLImageElement) {
          recordImg(mutation.target);
        }
        mutation.addedNodes.forEach(recordImg);
      });
      observer.disconnect();

      // Goes red if the swap render writes the previous crop onto the new
      // identity's attributes before effect cleanup can run.
      expect(painted).not.toContain(`${firstCrop}|identity-second|200`);
      expect(
        document.querySelector(`img[src="${firstCrop}"][data-identity-id="identity-second"]`),
      ).toBeNull();
      expect(document.querySelector(`img[src="${firstCrop}"]`)).toBeNull();
      expect(document.querySelector('[data-face-pending="true"]')).not.toBeNull();

      cropResult = secondCrop;
      await act(async () => {
        await Promise.resolve();
        fireIntersect();
        pendingLoads.shift()?.();
        await Promise.resolve();
      });

      await waitFor(() => {
        const img = screen.getByRole('img');
        expect(img).toHaveAttribute('src', secondCrop);
        expect(img).toHaveAttribute('data-identity-id', 'identity-second');
        expect(img.getAttribute('src')).not.toBe(firstCrop);
      });
    });

    /**
     * [E21-19-R2-BR-01] [WBUX-5-R2-S3-BR-01] [TEST-15]
     * Unassigned faces on the same media share no identity_id. The owner key
     * must include bbox or a swap still paints the previous crop for one frame.
     */
    it('does not paint the previous unassigned crop when only bbox changes [E21-19-R2-BR-01]', async () => {
      const firstCrop = 'data:image/jpeg;base64,UNASSIGNED-FACE-A';
      const secondCrop = 'data:image/jpeg;base64,UNASSIGNED-FACE-B';
      let cropResult = firstCrop;
      HTMLCanvasElement.prototype.toDataURL = vi.fn(() => cropResult);

      const pendingLoads: (() => void)[] = [];
      class ControllableImage {
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
          pendingLoads.push(() => {
            const handler = this.onload;
            if (handler) {
              handler.call(this as unknown as GlobalEventHandlers, new Event('load'));
            }
          });
        }
      }
      globalThis.Image = ControllableImage as unknown as typeof Image;

      const firstIdentity = {
        media_id: 100,
        media_url: 'https://example.com/shared-scene.jpg',
        bbox: { x: 10, y: 20, width: 30, height: 40 },
      };
      const secondIdentity = {
        media_id: 100,
        media_url: 'https://example.com/shared-scene.jpg',
        bbox: { x: 50, y: 60, width: 20, height: 25 },
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
        expect(pendingLoads.length).toBe(1);
      });

      cropResult = firstCrop;
      await act(async () => {
        pendingLoads.shift()?.();
        await Promise.resolve();
      });

      await waitFor(() => {
        const img = screen.getByRole('img');
        expect(img).toHaveAttribute('src', firstCrop);
        expect(img).toHaveAttribute('data-media-id', '100');
        expect(img.getAttribute('data-identity-id')).toBeNull();
      });

      const painted: string[] = [];
      const recordImg = (node: Node) => {
        if (!(node instanceof HTMLImageElement)) {
          return;
        }
        painted.push(`${node.getAttribute('src')}|${node.getAttribute('data-media-id')}`);
      };
      const host =
        document.querySelector('.acx-cluster-card__thumb')?.parentElement ?? document.body;
      const observer = new MutationObserver(() => {
        // Records are drained synchronously via takeRecords() after rerender.
      });
      observer.observe(host, {
        subtree: true,
        childList: true,
        attributes: true,
        attributeFilter: ['src', 'alt', 'data-identity-id', 'data-media-id'],
      });

      rerender(<IdentityThumbnail identity={secondIdentity} size={32} />);
      observer.takeRecords().forEach((mutation) => {
        if (mutation.type === 'attributes' && mutation.target instanceof HTMLImageElement) {
          recordImg(mutation.target);
        }
        mutation.addedNodes.forEach(recordImg);
      });
      observer.disconnect();

      // Goes red if media-only owner keys let the first bbox crop stay painted
      // under the second face's attrs before effect cleanup can run.
      expect(painted).not.toContain(`${firstCrop}|100`);
      expect(document.querySelector(`img[src="${firstCrop}"]`)).toBeNull();
      expect(document.querySelector('[data-face-pending="true"]')).not.toBeNull();

      cropResult = secondCrop;
      await act(async () => {
        await Promise.resolve();
        fireIntersect();
        pendingLoads.shift()?.();
        await Promise.resolve();
      });

      await waitFor(() => {
        const img = screen.getByRole('img');
        expect(img).toHaveAttribute('src', secondCrop);
        expect(img).toHaveAttribute('data-media-id', '100');
        expect(img.getAttribute('src')).not.toBe(firstCrop);
      });
    });

    it('ignores a late crop from a superseded identity [S6-BR-01 cancelled]', async () => {
      const firstCrop = 'data:image/jpeg;base64,LATE-A-CROP';
      const secondCrop = 'data:image/jpeg;base64,B-WINS-CROP';
      let cropResult = firstCrop;
      HTMLCanvasElement.prototype.toDataURL = vi.fn(() => cropResult);

      const pendingLoads: (() => void)[] = [];
      class ControllableImage {
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
          pendingLoads.push(() => {
            const handler = this.onload;
            if (handler) {
              handler.call(this as unknown as GlobalEventHandlers, new Event('load'));
            }
          });
        }
      }
      globalThis.Image = ControllableImage as unknown as typeof Image;

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
        expect(pendingLoads.length).toBe(1);
      });

      // Do not resolve A — switch to B while A's Image is still in flight.
      const fireLateA = pendingLoads.shift();
      expect(fireLateA).toBeTypeOf('function');

      rerender(<IdentityThumbnail identity={secondIdentity} size={32} />);

      await act(async () => {
        await Promise.resolve();
      });

      // B constructed and held; A is superseded.
      expect(pendingLoads.length).toBeGreaterThanOrEqual(1);
      const fireB = pendingLoads.shift();
      expect(fireB).toBeTypeOf('function');

      // (b) A's late onload must not paint firstCrop after the switch.
      cropResult = firstCrop;
      await act(async () => {
        fireLateA?.();
        await Promise.resolve();
      });

      expect(document.querySelector(`img[src="${firstCrop}"]`)).toBeNull();
      expect(document.querySelector('[data-face-pending="true"]')).not.toBeNull();

      cropResult = secondCrop;
      await act(async () => {
        fireB?.();
        await Promise.resolve();
      });

      await waitFor(() => {
        const img = screen.getByRole('img');
        expect(img).toHaveAttribute('src', secondCrop);
        expect(img).toHaveAttribute('data-identity-id', 'identity-second');
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
