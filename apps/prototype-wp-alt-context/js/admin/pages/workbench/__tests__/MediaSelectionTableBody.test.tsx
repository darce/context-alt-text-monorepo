/**
 * Decorative first-class on the wire [A11Y-02][A11Y-04]:
 * - isDecorative rows render alt="" (screen readers skip)
 * - thumb link keeps an accessible name from the title, not via decorative alt
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import React from 'react';
import { describe, expect, it, vi } from 'vitest';

import type { WorkbenchMediaItem } from '../../../hooks/useWorkbenchMedia';
import { MediaSelectionTableBody } from '../MediaSelectionTableBody';

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
  sprintf: (format: string, ...args: (string | number)[]) => {
    let sequentialIndex = 0;
    return format.replace(/%((\d+)\$)?[sd]/g, (_match, _positional, explicitIndex) => {
      if (explicitIndex) {
        return String(args[Number(explicitIndex) - 1] ?? '');
      }
      return String(args[sequentialIndex++] ?? '');
    });
  },
}));

vi.mock('../../../api/describeApi', async () => {
  const actual = await vi.importActual<typeof import('../../../api/describeApi')>(
    '../../../api/describeApi',
  );
  return {
    ...actual,
    correctDescriptionHistoryItem: vi.fn(),
    describeMedia: vi.fn(),
  };
});

const makeItem = (overrides: Partial<WorkbenchMediaItem> = {}): WorkbenchMediaItem => ({
  id: 42,
  title: 'Ornamental border',
  status: 'complete',
  thumbnailUrl: 'http://example.test/thumb.jpg',
  altText: null,
  isDecorative: false,
  editUrl: null,
  tags: [],
  ...overrides,
});

const renderBody = (items: WorkbenchMediaItem[]) => {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <table>
        <tbody>
          <MediaSelectionTableBody
            items={items}
            isLoading={false}
            detailIsLoading={false}
            onToggleRow={() => undefined}
            selection={{}}
          />
        </tbody>
      </table>
    </QueryClientProvider>,
  );
};

describe('MediaSelectionTableBody — decorative alt + link name [A11Y-02][A11Y-04]', () => {
  it('renders empty alt for isDecorative rows so screen readers skip the image', () => {
    const { container } = renderBody([
      makeItem({ isDecorative: true, altText: null, status: 'complete' }),
    ]);

    // alt="" removes the image from the a11y tree — query the DOM node directly.
    const img = container.querySelector('img');
    expect(img).not.toBeNull();
    // Decorative contract: alt="" — never the title fallback.
    expect(img?.getAttribute('alt')).toBe('');
    expect(img?.getAttribute('alt')).not.toBe('Ornamental border');
  });

  it('names the thumb edit link from the title when the image is decorative', () => {
    renderBody([makeItem({ isDecorative: true, altText: null, status: 'complete' })]);

    // Link must keep an accessible name after decorative img loses the title alt.
    const link = screen.getByRole('link', { name: /Edit Ornamental border/i });
    expect(link).toBeInTheDocument();
    expect(link).toHaveAttribute('aria-label', 'Edit Ornamental border');
  });

  it('still uses decoded altText for non-decorative described images', () => {
    renderBody([
      makeItem({
        isDecorative: false,
        altText: 'A stone bridge',
        status: 'complete',
        title: 'Bridge',
      }),
    ]);

    const img = screen.getByRole('img');
    expect(img).toHaveAttribute('alt', 'A stone bridge');
  });

  it('falls back to title alt only when not decorative and alt is missing', () => {
    renderBody([
      makeItem({
        isDecorative: false,
        altText: null,
        status: 'missing',
        title: 'Still missing',
      }),
    ]);

    const img = screen.getByRole('img');
    expect(img).toHaveAttribute('alt', 'Still missing');
  });
});
