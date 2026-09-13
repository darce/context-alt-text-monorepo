import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

import { type Root } from 'react-dom/client';
import { act, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import {
  CASE_STUDY_URL,
  PUBLIC_GUIDE_FALLBACK,
  PUBLIC_GUIDE_LOADING,
  guidedCopy,
} from '../../admin/guidedPrototype/publicGuideCopy';
import { mountPublicGuide } from '../main';
import { attachPublicGuideLoadWatch } from '../publicGuideShell';

const viteConfig = (): string =>
  readFileSync(resolve(__dirname, '../../../vite.config.ts'), 'utf8');

describe('public guide entry', () => {
  afterEach(() => {
    document.body.innerHTML = '';
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it('registers the third Vite input as js/guide/main.tsx', () => {
    expect(viteConfig()).toMatch(/guide:\s*path\.resolve\(__dirname,\s*'js\/guide\/main\.tsx'\)/);
  });

  it('registers a dedicated Vite input for the public guide watch entry', () => {
    expect(viteConfig()).toMatch(
      /'guide-watch':\s*path\.resolve\(__dirname,\s*'js\/guide\/publicGuideWatch\.ts'\)/,
    );
  });

  it('does not rely on an inline script in the public guide template', () => {
    const template = readFileSync(resolve(__dirname, '../../../src/public/templates/public-guide.php'), 'utf8');
    expect(template).not.toMatch(/<script(?![^>]*\bsrc=)/);
  });

  it('hides the fallback, mounts the public walkthrough, and uses the external Home link', () => {
    document.body.innerHTML = `
      <main id="acx-public-guide" data-home-url="https://demo.example/" data-scope="recorded" data-example="bundled">
        <p class="acx-public-guide__loading" aria-live="polite">${PUBLIC_GUIDE_LOADING}</p>
        <p class="acx-public-guide__fallback" role="alert" hidden>${PUBLIC_GUIDE_FALLBACK}</p>
      </main>
    `;

    act(() => {
      mountPublicGuide();
    });

    const loading = document.querySelector('.acx-public-guide__loading');
    const fallback = document.querySelector('.acx-public-guide__fallback');
    expect(loading).toBeInstanceOf(HTMLElement);
    expect((loading as HTMLElement).hidden).toBe(true);
    expect(fallback).toBeInstanceOf(HTMLElement);
    expect((fallback as HTMLElement).hidden).toBe(true);
    expect(document.getElementById('acx-public-guide')?.getAttribute('data-acx-mounted')).toBe('1');
    expect(document.querySelectorAll('main')).toHaveLength(1);
    expect(document.getElementById('acx-public-guide')?.tagName).toBe('MAIN');
    expect(document.getElementById('acx-public-guide')).toHaveClass('acx-public-guide');
    expect(screen.getByTestId('guided-demo-root').tagName).toBe('DIV');
    expect(screen.getByTestId('guided-scope')).toHaveTextContent(guidedCopy('scope.public'));
    const home = within(screen.getByRole('navigation', { name: guidedCopy('nav.leave') })).getByRole('link', {
      name: `${guidedCopy('nav.home')} (opens in a new window)`,
    });
    expect(home).toHaveAttribute('href', 'https://altcontext.com/');
    expect(home).toHaveAttribute('target', '_blank');
    expect(home).toHaveAttribute('rel', 'noreferrer');
    expect(
      screen.getByRole('link', { name: `${guidedCopy('entry.read_case_study')} (opens in a new window)` }),
    ).toHaveAttribute('href', CASE_STUDY_URL);
  });

  it('ignores data-home-url when rendering the external Home link', () => {
    document.body.innerHTML = '<main id="acx-public-guide" data-home-url="https://demo.example/"></main>';
    act(() => {
      mountPublicGuide();
    });
    const home = within(screen.getByRole('navigation', { name: guidedCopy('nav.leave') })).getByRole('link', {
      name: `${guidedCopy('nav.home')} (opens in a new window)`,
    });
    expect(home).toHaveAttribute('href', 'https://altcontext.com/');
    expect(home).toHaveAttribute('target', '_blank');
    expect(home).toHaveAttribute('rel', 'noreferrer');
  });

  it('leaves the HTML fallback visible when createRoot throws', () => {
    const errorSpy = vi.spyOn(console, 'error').mockImplementation(() => undefined);
    document.body.innerHTML = `
      <main id="acx-public-guide">
        <p class="acx-public-guide__loading" aria-live="polite">${PUBLIC_GUIDE_LOADING}</p>
        <p class="acx-public-guide__fallback" role="alert" hidden>${PUBLIC_GUIDE_FALLBACK}</p>
      </main>
    `;

    act(() => {
      mountPublicGuide(document.getElementById('acx-public-guide'), {
        createRoot: () => {
          throw new Error('createRoot failed');
        },
      });
    });

    const loading = document.querySelector('.acx-public-guide__loading');
    const fallback = document.querySelector('.acx-public-guide__fallback');
    expect(loading).toBeInstanceOf(HTMLElement);
    expect((loading as HTMLElement).hidden).toBe(true);
    expect(fallback).toBeInstanceOf(HTMLElement);
    expect((fallback as HTMLElement).hidden).toBe(false);
    expect(fallback).toHaveTextContent(PUBLIC_GUIDE_FALLBACK);
    expect(document.body.textContent).not.toMatch(/Something went wrong/);
    expect(errorSpy).toHaveBeenCalled();
    expect(errorSpy.mock.calls.some((args) => args.some((arg) => String(arg).includes('createRoot failed')))).toBe(
      true,
    );
  });

  it('unmounts a created root and logs when render throws', () => {
    const errorSpy = vi.spyOn(console, 'error').mockImplementation(() => undefined);
    const unmount = vi.fn();
    document.body.innerHTML = `
      <main id="acx-public-guide">
        <p class="acx-public-guide__loading" aria-live="polite">${PUBLIC_GUIDE_LOADING}</p>
        <p class="acx-public-guide__fallback" role="alert" hidden>${PUBLIC_GUIDE_FALLBACK}</p>
      </main>
    `;

    const failedRoot: Root = {
      render: () => {
        throw new Error('render failed');
      },
      unmount,
    };

    act(() => {
      mountPublicGuide(document.getElementById('acx-public-guide'), {
        createRoot: () => failedRoot,
      });
    });

    const fallback = document.querySelector('.acx-public-guide__fallback');
    expect(fallback).toBeInstanceOf(HTMLElement);
    expect((fallback as HTMLElement).hidden).toBe(false);
    expect(unmount).toHaveBeenCalledTimes(1);
    expect(errorSpy).toHaveBeenCalled();
    expect(errorSpy.mock.calls.some((args) => args.some((arg) => String(arg).includes('render failed')))).toBe(true);
  });

  it('keeps a polite loading state until the bundle mounts, errors, or times out', () => {
    document.body.innerHTML = `
      <main id="acx-public-guide">
        <p class="acx-public-guide__loading" aria-live="polite">${PUBLIC_GUIDE_LOADING}</p>
        <p class="acx-public-guide__fallback" role="alert" hidden>${PUBLIC_GUIDE_FALLBACK}</p>
      </main>
    `;

    const loading = document.querySelector('.acx-public-guide__loading');
    const fallback = document.querySelector('.acx-public-guide__fallback');
    expect(loading).toBeInstanceOf(HTMLElement);
    expect((loading as HTMLElement).hidden).toBe(false);
    expect(loading).toHaveAttribute('aria-live', 'polite');
    expect(loading).toHaveTextContent(PUBLIC_GUIDE_LOADING);
    expect(fallback).toBeInstanceOf(HTMLElement);
    expect((fallback as HTMLElement).hidden).toBe(true);
    expect(screen.queryByRole('alert')).toBeNull();
  });

  it('swaps loading to the alert fallback after the bounded timeout', () => {
    vi.useFakeTimers();
    document.body.innerHTML = `
      <main id="acx-public-guide">
        <p class="acx-public-guide__loading" aria-live="polite">${PUBLIC_GUIDE_LOADING}</p>
        <p class="acx-public-guide__fallback" role="alert" hidden>${PUBLIC_GUIDE_FALLBACK}</p>
      </main>
    `;
    const root = document.getElementById('acx-public-guide');
    expect(root).toBeInstanceOf(HTMLElement);
    const stop = attachPublicGuideLoadWatch(root as HTMLElement, 1000);

    act(() => {
      vi.advanceTimersByTime(1000);
    });

    const loading = document.querySelector('.acx-public-guide__loading');
    const fallback = document.querySelector('.acx-public-guide__fallback');
    expect((loading as HTMLElement).hidden).toBe(true);
    expect((fallback as HTMLElement).hidden).toBe(false);
    expect(screen.getByRole('alert')).toHaveTextContent(PUBLIC_GUIDE_FALLBACK);
    stop();
    vi.useRealTimers();
  });

  it('swaps loading to the alert fallback when the guide bundle script errors', () => {
    document.body.innerHTML = `
      <main id="acx-public-guide">
        <p class="acx-public-guide__loading" aria-live="polite">${PUBLIC_GUIDE_LOADING}</p>
        <p class="acx-public-guide__fallback" role="alert" hidden>${PUBLIC_GUIDE_FALLBACK}</p>
      </main>
    `;
    const root = document.getElementById('acx-public-guide');
    expect(root).toBeInstanceOf(HTMLElement);
    const stop = attachPublicGuideLoadWatch(root as HTMLElement);

    const script = document.createElement('script');
    script.id = 'acx-public-guide-js';
    document.body.appendChild(script);
    script.dispatchEvent(new Event('error', { bubbles: true }));

    const loading = document.querySelector('.acx-public-guide__loading');
    const fallback = document.querySelector('.acx-public-guide__fallback');
    expect((loading as HTMLElement).hidden).toBe(true);
    expect((fallback as HTMLElement).hidden).toBe(false);
    expect(screen.getByRole('alert')).toHaveTextContent(PUBLIC_GUIDE_FALLBACK);
    stop();
  });
});
