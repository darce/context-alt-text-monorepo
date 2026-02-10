import { render, screen } from '@testing-library/react';

import { RosterEntriesSection } from '../roster/RosterEntriesSection';
import type { RosterEntriesQuery } from '../roster/RosterEntriesSection';
import { RosterEntriesTable } from '../roster/RosterEntriesTable';
import { vi } from 'vitest';

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
  _n: (single: string) => single,
}));

const entries = [
  {
    id: 1,
    name: 'Alice',
    tags: ['tag-a'],
    cluster_count: 2,
    updated_at: new Date().toISOString(),
  },
];

describe('RosterEntriesTable', () => {
  it('renders identity rows', () => {
    render(<RosterEntriesTable entries={entries} />);

    expect(screen.getByText(/Alice/)).toBeInTheDocument();
    expect(screen.getByText(/tag-a/)).toBeInTheDocument();
    expect(screen.getByText('2')).toBeInTheDocument();
  });
});

describe('RosterEntriesSection', () => {
  it('shows loading state', () => {
    const query: RosterEntriesQuery = { isLoading: true, isError: false, data: undefined, refetch: vi.fn() };
    render(<RosterEntriesSection query={query} />);
    expect(screen.getByText(/Loading roster entries/)).toBeInTheDocument();
  });
});
