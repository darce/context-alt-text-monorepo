/**
 * Decorative first-class on the wire [A11Y-02][A11Y-04]:
 * - isDecorative rows render alt="" (screen readers skip)
 * - thumb link keeps an accessible name from the title, not via decorative alt
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import React from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { registerConfig, resetConfigCache } from '../../../api/config';
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

const renderBody = (
  items: WorkbenchMediaItem[],
  onClearSearch = vi.fn(),
  extras: {
    searchQuery?: string;
    statusFilter?: 'all' | 'missing';
    onClearStatusFilter?: () => void;
  } = {},
) => {
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
            onClearSearch={onClearSearch}
            {...extras}
          />
        </tbody>
      </table>
    </QueryClientProvider>,
  );
};

describe('MediaSelectionTableBody — decorative alt + link name [A11Y-02][A11Y-04]', () => {
  afterEach(() => {
    resetConfigCache();
  });

  it('does not offer search recovery when the library is empty without a search [DUX-W2D6C-RV-02]', () => {
    renderBody([]);

    expect(screen.queryByText('No media matches your search.')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Clear search' })).not.toBeInTheDocument();
    expect(screen.getByTestId('acx-empty-state')).toHaveAttribute('data-variant', 'empty');
    expect(screen.queryByTestId('acx-empty-state-live-region')).not.toBeInTheDocument();
  });

  it('resolves the true-zero "Open the media library" href from configured admin URLs, not a hardcoded /wp-admin/ path [DUX-W2D6C-RV-07]', () => {
    registerConfig({
      nonce: 'n',
      ajaxUrl: '/wp-admin/admin-ajax.php',
      endpoints: {},
      adminUrls: {
        mediaLibrary: '/site/wp-admin/upload.php',
      },
    });

    renderBody([]);

    const link = screen.getByRole('link', { name: 'Open the media library' });
    const href = link.getAttribute('href') ?? '';

    // The configured (subdirectory-install) target must win over any literal.
    expect(href).toContain('/site/wp-admin/upload.php');
    // A hardcoded href would ignore the configured value entirely.
    expect(href).not.toBe('/wp-admin/upload.php');
  });

  it('does not offer a dead Clear search when only a status filter is active [DUX-W2D6C-RV-02]', () => {
    renderBody([], vi.fn(), { searchQuery: '', statusFilter: 'missing' });

    expect(screen.queryByText('No media matches your search.')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Clear search' })).not.toBeInTheDocument();
    expect(screen.getByText('No media items match the current filters.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Show all media' })).toBeInTheDocument();
  });

  it('restores media rows when Clear search runs against an active search [DUX-W2D6C-RV-02]', async () => {
    const library = [makeItem({ title: 'Harbour at dusk' })];
    const Harness = () => {
      const [searchQuery, setSearchQuery] = React.useState('nomatch');
      const items = searchQuery.trim() === '' ? library : [];
      const client = new QueryClient({
        defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
      });
      return (
        <QueryClientProvider client={client}>
          <table>
            <tbody>
              <MediaSelectionTableBody
                items={items}
                isLoading={false}
                detailIsLoading={false}
                onToggleRow={() => undefined}
                selection={{}}
                onClearSearch={() => setSearchQuery('')}
                searchQuery={searchQuery}
              />
            </tbody>
          </table>
        </QueryClientProvider>
      );
    };

    render(<Harness />);

    expect(screen.getByText('No media matches your search.')).toBeInTheDocument();
    expect(screen.queryByText('Harbour at dusk')).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Clear search' }));
    expect(screen.getByText('Harbour at dusk')).toBeInTheDocument();
    expect(screen.queryByText('No media matches your search.')).not.toBeInTheDocument();
  });

  it('moves focus to the media search input after Clear search [DUX-W2D6C-RV-03]', async () => {
    const library = [makeItem({ title: 'Harbour at dusk' })];
    const Harness = () => {
      const [searchQuery, setSearchQuery] = React.useState('nomatch');
      const items = searchQuery.trim() === '' ? library : [];
      const client = new QueryClient({
        defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
      });
      return (
        <QueryClientProvider client={client}>
          <input id="acx-media-search" defaultValue={searchQuery} />
          <table>
            <tbody>
              <MediaSelectionTableBody
                items={items}
                isLoading={false}
                detailIsLoading={false}
                onToggleRow={() => undefined}
                selection={{}}
                onClearSearch={() => setSearchQuery('')}
                searchQuery={searchQuery}
              />
            </tbody>
          </table>
        </QueryClientProvider>
      );
    };

    render(<Harness />);

    await userEvent.click(screen.getByRole('button', { name: 'Clear search' }));
    expect(screen.getByText('Harbour at dusk')).toBeInTheDocument();
    expect(document.getElementById('acx-media-search')).toHaveFocus();
  });

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

  it('qualifies Suggest and Mark decorative accessible names with the media title [B-03][A11Y-04]', () => {
    renderBody([makeItem({ title: 'Ornamental border', isDecorative: false, altText: null })]);

    // Visible labels stay short; aria-label carries the row title for AT lists.
    const suggest = screen.getByRole('button', { name: 'Suggest alt text for Ornamental border' });
    expect(suggest).toBeInTheDocument();
    expect(suggest).toHaveTextContent('Suggest alt text');

    const decorative = screen.getByRole('button', { name: 'Mark as decorative for Ornamental border' });
    expect(decorative).toBeInTheDocument();
    // Visible copy keeps the longer outcome-oriented phrase.
    expect(decorative.textContent).toMatch(/Mark as decorative/);
  });

  it('falls back to bare visible names when title is empty [B-03]', () => {
    renderBody([makeItem({ title: '', isDecorative: false, altText: null })]);

    // No aria-label — accessible name is the visible label alone.
    const suggest = screen.getByRole('button', { name: 'Suggest alt text' });
    expect(suggest).toBeInTheDocument();
    expect(suggest.getAttribute('aria-label')).toBeNull();

    const decorative = screen.getByRole('button', {
      name: /Mark as decorative — screen readers will announce nothing/,
    });
    expect(decorative).toBeInTheDocument();
    expect(decorative.getAttribute('aria-label')).toBeNull();
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

  it('prefers real altText over leftover isDecorative marker [WBUX-5-R1-01][A11Y-02]', () => {
    // Wire shape WorkbenchMediaListDecorativeTest pins: isDecorative:true with
    // non-null altText (leftover marker after a real description landed). isDecorative
    // must not win — empty alt would hide the description from assistive tech.
    const { container } = renderBody([
      makeItem({
        isDecorative: true,
        altText: 'A real description.',
        status: 'complete',
        title: 'Ornamental border',
      }),
    ]);

    const img = container.querySelector('img');
    expect(img).not.toBeNull();
    expect(img?.getAttribute('alt')).toBe('A real description.');
    expect(img?.getAttribute('alt')).not.toBe('');
    expect(img?.getAttribute('alt')).not.toBe('Ornamental border');
  });

  it('qualifies each row edit control with its media title [WBUX-5-D-05][A11Y-04]', () => {
    // MediaAltInlineEditor takes `title` optionally, so the component-level test
    // passes even when the row forgets to wire it. Pin the call site: without
    // this, every row in an AT element list reads a bare "Edit alt text".
    renderBody([
      makeItem({ id: 7, title: 'Harbour at dusk', altText: null, status: 'missing' }),
    ]);

    expect(
      screen.getByRole('button', { name: 'Edit alt text for Harbour at dusk' }),
    ).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Edit alt text' })).toBeNull();
  });
});
