import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi, beforeEach } from 'vitest';

import type { RosterEntry } from '../../../api/rosterApi';
import { useCreatePerson, useDeletePerson, useUpdatePerson } from '../../../hooks/useRosterHooks';
import { createMockMutation } from '../../../test-utils/mockHooks';
import { RosterEntriesSection } from '../RosterEntriesSection';
import type { RosterEntriesQuery } from '../RosterEntriesSection';

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
  _n: (single: string, plural: string, count: number) => (count === 1 ? single : plural),
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

vi.mock('../../../hooks/useRosterHooks', () => ({
  useCreatePerson: vi.fn(),
  useUpdatePerson: vi.fn(),
  useDeletePerson: vi.fn(),
}));

/**
 * Sparse create_person / update_person wire body: no queue_memberships,
 * no clusters, no projection fields. Matches class-api.php create_person
 * (id/person_uuid/name/tags/cluster_count/created_at/updated_at only).
 */
const sparseLegacyEntry = {
  id: 7,
  name: 'Legacy Person',
  tags: [] as string[],
  cluster_count: 0,
} as unknown as RosterEntry;

const readyQuery = (data: RosterEntry[]): RosterEntriesQuery => ({
  isLoading: false,
  isError: false,
  data,
  refetch: vi.fn(),
});

const createMutation = createMockMutation({ mutate: vi.fn(), isPending: false });
const updateMutation = createMockMutation({ mutate: vi.fn(), isPending: false });
const deleteMutation = createMockMutation({ mutate: vi.fn(), isPending: false });

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(useCreatePerson).mockReturnValue(createMutation as never);
  vi.mocked(useUpdatePerson).mockReturnValue(updateMutation as never);
  vi.mocked(useDeletePerson).mockReturnValue(deleteMutation as never);
});

describe('RosterEntriesSection queue filter [S4-BR-01]', () => {
  it('does not crash when a sparse entry lacks queue_memberships under ?queue=', () => {
    // Regression: entry.queue_memberships.includes throws when memberships
    // are undefined (create/update person REST body written into cache).
    expect(() => {
      render(
        <MemoryRouter initialEntries={['/?queue=hard-examples']}>
          <RosterEntriesSection query={readyQuery([sparseLegacyEntry])} />
        </MemoryRouter>,
      );
    }).not.toThrow();

    // Section must stay mounted (tree not unmounted by the error).
    expect(screen.getByTestId('roster-entries-section')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'People' })).toBeInTheDocument();

    // Absent memberships means not in the hard-examples queue — filtered out.
    expect(screen.queryByText('Legacy Person')).not.toBeInTheDocument();
    expect(screen.getByText('No people in hard examples queue.')).toBeInTheDocument();
  });

  it('still shows a sparse entry when no queue filter is active', () => {
    render(
      <MemoryRouter initialEntries={['/?tab=entries']}>
        <RosterEntriesSection query={readyQuery([sparseLegacyEntry])} />
      </MemoryRouter>,
    );

    expect(screen.getByTestId('roster-entries-section')).toBeInTheDocument();
    expect(screen.getByText('Legacy Person')).toBeInTheDocument();
  });
});
