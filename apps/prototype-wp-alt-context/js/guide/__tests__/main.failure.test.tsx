import { act, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { PUBLIC_GUIDE_FALLBACK } from '../../admin/guidedPrototype/publicGuideCopy';

vi.mock('../../admin/guidedPrototype/RecordedWalkthrough', () => ({
  RecordedWalkthrough: (): never => {
    throw new Error('recorded walkthrough failed');
  },
}));

import { mountPublicGuide } from '../main';

describe('public guide render failure', () => {
  afterEach(() => {
    document.body.innerHTML = '';
  });

  it('shows the public recovery copy instead of the WordPress default', () => {
    document.body.innerHTML = `
      <main id="acx-public-guide">
        <p class="acx-public-guide__fallback" role="alert">${PUBLIC_GUIDE_FALLBACK}</p>
      </main>
    `;

    act(() => {
      mountPublicGuide();
    });

    const alerts = screen.getAllByRole('alert');
    const visible = alerts.filter((node) => node instanceof HTMLElement && !node.hidden);
    expect(visible.some((node) => node.textContent?.includes('Reload the page'))).toBe(true);
    expect(document.body.textContent).not.toMatch(/Something went wrong/);
  });
});
