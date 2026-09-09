import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

import { act, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import { CASE_STUDY_URL, PUBLIC_GUIDE_FALLBACK, guidedCopy } from '../../admin/guidedPrototype/publicGuideCopy';
import { mountPublicGuide } from '../main';

const viteConfig = (): string =>
  readFileSync(resolve(__dirname, '../../../vite.config.ts'), 'utf8');

describe('public guide entry', () => {
  afterEach(() => {
    document.body.innerHTML = '';
  });

  it('registers the third Vite input as js/guide/main.tsx', () => {
    expect(viteConfig()).toMatch(/guide:\s*path\.resolve\(__dirname,\s*'js\/guide\/main\.tsx'\)/);
  });

  it('hides the fallback, reads data-home-url, and mounts the public walkthrough', () => {
    document.body.innerHTML = `
      <main id="acx-public-guide" data-home-url="https://demo.example/" data-scope="recorded" data-example="bundled">
        <p class="acx-public-guide__fallback" role="alert">The walkthrough could not load. Reload the page, or watch the recorded video on the case study page.</p>
      </main>
    `;

    act(() => {
      mountPublicGuide();
    });

    const fallback = document.querySelector('.acx-public-guide__fallback');
    expect(fallback).toBeInstanceOf(HTMLElement);
    expect((fallback as HTMLElement).hidden).toBe(true);
    expect(document.querySelectorAll('main')).toHaveLength(1);
    expect(document.getElementById('acx-public-guide')?.tagName).toBe('MAIN');
    expect(screen.getByTestId('guided-demo-root').tagName).toBe('DIV');
    expect(screen.getByTestId('guided-scope')).toHaveTextContent(guidedCopy('scope.public'));
    expect(screen.getByRole('navigation', { name: guidedCopy('nav.leave') }).querySelector('a')).toHaveAttribute(
      'href',
      'https://demo.example/',
    );
    expect(screen.getByRole('link', { name: guidedCopy('entry.read_case_study') })).toHaveAttribute(
      'href',
      CASE_STUDY_URL,
    );
  });

  it('falls back to / when data-home-url is missing', () => {
    document.body.innerHTML = '<main id="acx-public-guide"></main>';
    act(() => {
      mountPublicGuide();
    });
    expect(screen.getByRole('navigation', { name: guidedCopy('nav.leave') }).querySelector('a')).toHaveAttribute(
      'href',
      '/',
    );
  });

  it('leaves the HTML fallback visible when createRoot throws', () => {
    document.body.innerHTML = `
      <main id="acx-public-guide">
        <p class="acx-public-guide__fallback" role="alert">${PUBLIC_GUIDE_FALLBACK}</p>
      </main>
    `;

    act(() => {
      mountPublicGuide(document.getElementById('acx-public-guide'), {
        createRoot: () => {
          throw new Error('createRoot failed');
        },
      });
    });

    const fallback = document.querySelector('.acx-public-guide__fallback');
    expect(fallback).toBeInstanceOf(HTMLElement);
    expect((fallback as HTMLElement).hidden).toBe(false);
    expect(fallback).toHaveTextContent(PUBLIC_GUIDE_FALLBACK);
    expect(document.body.textContent).not.toMatch(/Something went wrong/);
  });
});
