import { act } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { PUBLIC_GUIDE_FALLBACK, PUBLIC_GUIDE_LOADING } from '../../admin/guidedPrototype/publicGuideCopy';
import { bootPublicGuideWatch } from '../publicGuideWatch';

describe('public guide watch entry', () => {
  afterEach(() => {
    document.body.innerHTML = '';
    vi.useRealTimers();
  });

  it('delegates timeout fallback to attachPublicGuideLoadWatch', () => {
    vi.useFakeTimers();
    document.body.innerHTML = `
      <main id="acx-public-guide" data-acx-load-timeout="250">
        <p class="acx-public-guide__loading" aria-live="polite">${PUBLIC_GUIDE_LOADING}</p>
        <p class="acx-public-guide__fallback" role="alert" hidden>${PUBLIC_GUIDE_FALLBACK}</p>
      </main>
    `;

    const stop = bootPublicGuideWatch();
    expect(stop).toEqual(expect.any(Function));

    act(() => {
      vi.advanceTimersByTime(249);
    });
    expect((document.querySelector('.acx-public-guide__loading') as HTMLElement).hidden).toBe(false);
    expect((document.querySelector('.acx-public-guide__fallback') as HTMLElement).hidden).toBe(true);

    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect((document.querySelector('.acx-public-guide__loading') as HTMLElement).hidden).toBe(true);
    expect((document.querySelector('.acx-public-guide__fallback') as HTMLElement).hidden).toBe(false);
    stop?.();
  });

  it('swaps to the alert fallback when the guide bundle script errors', () => {
    document.body.innerHTML = `
      <main id="acx-public-guide">
        <p class="acx-public-guide__loading" aria-live="polite">${PUBLIC_GUIDE_LOADING}</p>
        <p class="acx-public-guide__fallback" role="alert" hidden>${PUBLIC_GUIDE_FALLBACK}</p>
      </main>
    `;

    const stop = bootPublicGuideWatch();
    const script = document.createElement('script');
    script.id = 'acx-public-guide-js';
    document.body.appendChild(script);
    script.dispatchEvent(new Event('error', { bubbles: true }));

    expect((document.querySelector('.acx-public-guide__loading') as HTMLElement).hidden).toBe(true);
    expect((document.querySelector('.acx-public-guide__fallback') as HTMLElement).hidden).toBe(false);
    stop?.();
  });
});
