import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { MediaSelectionToolbar } from '../MediaSelection';

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
}));

const noop = (): void => undefined;

describe('D-23 MediaSelectionToolbar filter zone', () => {
  it('renders loading', () => {
    render(
      <MediaSelectionToolbar
        searchQuery=""
        onSearchChange={noop}
        statusFilter="all"
        onStatusFilterChange={noop}
        statusMessage=""
        isStatusPending
        isError={false}
      />,
    );
    expect(screen.getByTestId('acx-zone-z-filters-loading')).toHaveTextContent('Loading filters…');
  });

  it('renders error', () => {
    render(
      <MediaSelectionToolbar
        searchQuery=""
        onSearchChange={noop}
        statusFilter="all"
        onStatusFilterChange={noop}
        statusMessage=""
        isStatusPending={false}
        isError
        onRetry={noop}
      />,
    );
    expect(screen.getByTestId('acx-zone-z-filters-error')).toHaveTextContent('Unable to load filters.');
  });
});
