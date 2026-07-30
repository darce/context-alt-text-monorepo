import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, useLocation } from 'react-router-dom';

import type { RosterEntry } from '../../api/rosterApi';
import { useCreatePerson, useDeletePerson, useUpdatePerson } from '../../hooks/useRosterHooks';
import { createMockMutation } from '../../test-utils/mockHooks';
import { RosterEntriesSection } from '../roster/RosterEntriesSection';
import type { RosterEntriesQuery } from '../roster/RosterEntriesSection';
import { derivePersonState, PERSON_STATES, type PersonState } from '../roster/personState';
import { RosterEntriesTable } from '../roster/RosterEntriesTable';
import { vi } from 'vitest';

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
  _n: (single: string) => single,
}));

vi.mock('../../hooks/useRosterHooks', () => ({
  useCreatePerson: vi.fn(),
  useUpdatePerson: vi.fn(),
  useDeletePerson: vi.fn(),
}));

const makeEntry = (overrides: Partial<RosterEntry> = {}): RosterEntry => ({
  id: 1,
  person_uuid: 'person-uuid-default',
  name: 'Default',
  tags: [],
  cluster_count: 0,
  clusters: [],
  queue_memberships: [],
  updated_at: new Date().toISOString(),
  source_version: 1,
  projection_status: 'current',
  projection_refreshed_at: new Date().toISOString(),
  ...overrides,
});

const entries: RosterEntry[] = [
  makeEntry({
    id: 1,
    person_uuid: 'person-uuid-alice',
    name: 'Alice',
    tags: ['tag-a'],
    cluster_count: 2,
    queue_memberships: ['singleton-proposals'],
  }),
  makeEntry({
    id: 2,
    person_uuid: 'person-uuid-bob',
    name: 'Bob',
    tags: [],
    cluster_count: 0,
    queue_memberships: ['hard-examples'],
  }),
];

/** One real fixture per MECE person state — no dead categories. */
const needsReviewFixture = makeEntry({
  id: 10,
  person_uuid: 'person-uuid-needs-review',
  name: 'Queued Person',
  tags: ['fixture-needs-review'],
  queue_memberships: ['needs-confirmation-after-merge'],
});

const unnamedFixture = makeEntry({
  id: 11,
  person_uuid: 'person-uuid-unnamed',
  name: '',
  tags: ['fixture-unnamed'],
  queue_memberships: [],
});

const namedFixture = makeEntry({
  id: 12,
  person_uuid: 'person-uuid-named',
  name: 'Fully Named',
  tags: ['fixture-named'],
  queue_memberships: [],
});

/** Blank name *and* non-empty queue — precedence pin (needs-review wins). */
const bothConditionsFixture = makeEntry({
  id: 13,
  person_uuid: 'person-uuid-both',
  name: '',
  tags: ['fixture-both'],
  queue_memberships: ['singleton-proposals'],
});

const STATE_LABELS: Record<PersonState, string> = {
  [PERSON_STATES.NEEDS_REVIEW]: 'Needs review',
  [PERSON_STATES.UNNAMED]: 'Unnamed',
  [PERSON_STATES.NAMED]: 'Named',
};

const rowForTag = (tag: string): HTMLElement => {
  const cell = screen.getByText(tag);
  const row = cell.closest('tr');
  if (!row) {
    throw new Error(`No table row for tag ${tag}`);
  }
  return row;
};

interface CreateRosterMutationContext {
  previousEntries: RosterEntry[] | undefined;
  optimisticId: number;
}

interface RosterMutationContext {
  previousEntries: RosterEntry[] | undefined;
  optimisticId?: number;
}

const createMutation = createMockMutation<
  RosterEntry,
  Error,
  { name: string; tags?: string[] },
  CreateRosterMutationContext
>({
  mutate: vi.fn(),
  isPending: false,
});
const updateMutation = createMockMutation<
  RosterEntry,
  Error,
  { id: number; name?: string; tags?: string[] },
  RosterMutationContext
>({
  mutate: vi.fn(),
  isPending: false,
});
const deleteMutation = createMockMutation<void, Error, number, RosterMutationContext>({
  mutate: vi.fn(),
  isPending: false,
});

const LocationProbe = () => {
  const location = useLocation();
  return <output data-testid="location-search">{location.search}</output>;
};

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(useCreatePerson).mockReturnValue(createMutation);
  vi.mocked(useUpdatePerson).mockReturnValue(updateMutation);
  vi.mocked(useDeletePerson).mockReturnValue(deleteMutation);
});

describe('derivePersonState', () => {
  it('returns needs-review when queue_memberships is non-empty', () => {
    expect(derivePersonState(needsReviewFixture)).toBe(PERSON_STATES.NEEDS_REVIEW);
  });

  it('returns unnamed when name is blank and queue_memberships is empty', () => {
    expect(derivePersonState(unnamedFixture)).toBe(PERSON_STATES.UNNAMED);
  });

  it('returns named when name is present and queue_memberships is empty', () => {
    expect(derivePersonState(namedFixture)).toBe(PERSON_STATES.NAMED);
  });

  it('prefers needs-review over unnamed when both conditions apply', () => {
    expect(derivePersonState(bothConditionsFixture)).toBe(PERSON_STATES.NEEDS_REVIEW);
    expect(derivePersonState(bothConditionsFixture)).not.toBe(PERSON_STATES.UNNAMED);
  });

  it('treats whitespace-only names as unnamed when not queued', () => {
    expect(derivePersonState(makeEntry({ name: '   ', queue_memberships: [] }))).toBe(PERSON_STATES.UNNAMED);
  });

  it('is total: every entry shape maps to exactly one of the three states', () => {
    const shapes: RosterEntry[] = [
      needsReviewFixture,
      unnamedFixture,
      namedFixture,
      bothConditionsFixture,
      makeEntry({ name: 'Stale named', queue_memberships: [], projection_status: 'stale' }),
      makeEntry({ name: '', queue_memberships: ['hard-examples'], projection_status: 'failed' }),
      makeEntry({ name: 'Refreshing', queue_memberships: [], projection_status: 'refreshing' }),
      makeEntry({ name: 'Multi queue', queue_memberships: ['singleton-proposals', 'hard-examples'] }),
    ];

    const allowed = new Set<PersonState>(Object.values(PERSON_STATES));
    for (const entry of shapes) {
      const state = derivePersonState(entry);
      expect(allowed.has(state)).toBe(true);
      expect(state).toBeDefined();
      expect(state).not.toBeNull();
    }
    // No fourth value exists on the union surface.
    expect(Object.values(PERSON_STATES)).toHaveLength(3);
  });

  /**
   * The shapes above are all well-formed projection entries, so they cannot
   * prove totality over what the server actually sends. A pre-projection
   * backend omits `queue_memberships` entirely — the shape RosterPage.workspace
   * pins as `[PAG-M3-S2]`. Deriving state from it must degrade, not throw:
   * with no projection data we cannot know of a queue membership, so claiming
   * needs-review would be fabricated [rg-015].
   */
  it('degrades instead of throwing when projection fields are absent [PAG-M3-S2]', () => {
    const legacyNamed = { id: 7, name: 'Legacy Person', tags: [], cluster_count: 0 } as unknown as RosterEntry;
    const legacyUnnamed = { id: 8, name: '', tags: [], cluster_count: 0 } as unknown as RosterEntry;

    expect(() => derivePersonState(legacyNamed)).not.toThrow();
    expect(derivePersonState(legacyNamed)).toBe(PERSON_STATES.NAMED);
    expect(derivePersonState(legacyUnnamed)).toBe(PERSON_STATES.UNNAMED);
  });
});

describe('RosterEntriesTable', () => {
  it('renders identity rows', () => {
    render(<RosterEntriesTable entries={entries} />);

    expect(screen.getByText(/Alice/)).toBeInTheDocument();
    expect(screen.getByText(/tag-a/)).toBeInTheDocument();
    expect(screen.getByText('2')).toBeInTheDocument();
  });

  it('confirms before deleting a person', async () => {
    render(<RosterEntriesTable entries={entries} />);

    await userEvent.click(screen.getAllByRole('button', { name: 'Delete person' })[0]);

    expect(
      screen.getByText('Are you sure you want to delete this person? Assigned clusters will be dissociated.'),
    ).toBeInTheDocument();

    await userEvent.click(screen.getAllByRole('button', { name: 'Delete' }).at(-1)!);

    expect(deleteMutation.mutate).toHaveBeenCalledWith(1, expect.any(Object));
  });

  it('renders a State column header', () => {
    render(<RosterEntriesTable entries={entries} />);

    expect(screen.getByRole('columnheader', { name: 'State' })).toBeInTheDocument();
  });

  it('shows needs-review with icon and text; other states absent from that row', () => {
    render(<RosterEntriesTable entries={[needsReviewFixture]} />);

    const row = rowForTag('fixture-needs-review');
    expect(within(row).getByText(STATE_LABELS[PERSON_STATES.NEEDS_REVIEW])).toBeInTheDocument();
    expect(within(row).queryByText(STATE_LABELS[PERSON_STATES.UNNAMED])).not.toBeInTheDocument();
    expect(within(row).queryByText(STATE_LABELS[PERSON_STATES.NAMED])).not.toBeInTheDocument();
    expect(row.querySelector('svg')).not.toBeNull();
  });

  it('shows unnamed with icon and text; other states absent from that row', () => {
    render(<RosterEntriesTable entries={[unnamedFixture]} />);

    const row = rowForTag('fixture-unnamed');
    expect(within(row).getByText(STATE_LABELS[PERSON_STATES.UNNAMED])).toBeInTheDocument();
    expect(within(row).queryByText(STATE_LABELS[PERSON_STATES.NEEDS_REVIEW])).not.toBeInTheDocument();
    expect(within(row).queryByText(STATE_LABELS[PERSON_STATES.NAMED])).not.toBeInTheDocument();
    expect(row.querySelector('svg')).not.toBeNull();
  });

  it('shows named with icon and text; other states absent from that row', () => {
    render(<RosterEntriesTable entries={[namedFixture]} />);

    const row = rowForTag('fixture-named');
    expect(within(row).getByText(STATE_LABELS[PERSON_STATES.NAMED])).toBeInTheDocument();
    expect(within(row).queryByText(STATE_LABELS[PERSON_STATES.NEEDS_REVIEW])).not.toBeInTheDocument();
    expect(within(row).queryByText(STATE_LABELS[PERSON_STATES.UNNAMED])).not.toBeInTheDocument();
    expect(row.querySelector('svg')).not.toBeNull();
  });

  it('renders both-conditions row as needs-review (precedence pin)', () => {
    render(<RosterEntriesTable entries={[bothConditionsFixture]} />);

    const row = rowForTag('fixture-both');
    expect(within(row).getByText(STATE_LABELS[PERSON_STATES.NEEDS_REVIEW])).toBeInTheDocument();
    expect(within(row).queryByText(STATE_LABELS[PERSON_STATES.UNNAMED])).not.toBeInTheDocument();
  });

  it('keeps state icons out of the accessibility tree; state text is the accessible carrier', () => {
    render(<RosterEntriesTable entries={[needsReviewFixture, unnamedFixture, namedFixture]} />);

    const labels = [
      STATE_LABELS[PERSON_STATES.NEEDS_REVIEW],
      STATE_LABELS[PERSON_STATES.UNNAMED],
      STATE_LABELS[PERSON_STATES.NAMED],
    ];

    for (const label of labels) {
      const text = screen.getByText(label);
      expect(text).not.toHaveAttribute('aria-hidden');
      const stateRoot = text.closest('.acx-roster-entries__state');
      expect(stateRoot).not.toBeNull();
      const icon = stateRoot!.querySelector('svg');
      expect(icon).not.toBeNull();
      expect(icon).toHaveAttribute('aria-hidden', 'true');
    }
  });
});

describe('RosterEntriesSection', () => {
  const renderSection = (query: RosterEntriesQuery, route = '/?tab=entries') =>
    render(
      <MemoryRouter initialEntries={[route]}>
        <RosterEntriesSection query={query} />
        <LocationProbe />
      </MemoryRouter>,
    );

  it('shows loading state', () => {
    const query: RosterEntriesQuery = { isLoading: true, isError: false, data: undefined, refetch: vi.fn() };
    renderSection(query);
    expect(screen.getByText(/Loading roster entries/)).toBeInTheDocument();
  });

  it('shows error state with retry button', async () => {
    const refetch = vi.fn();
    const query: RosterEntriesQuery = { isLoading: false, isError: true, data: undefined, refetch };

    renderSection(query);

    expect(screen.getByText(/Unable to load roster entries/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Retry' }));
    expect(refetch).toHaveBeenCalledTimes(1);
  });

  it('creates a new person via Add Person form', async () => {
    const query: RosterEntriesQuery = { isLoading: false, isError: false, data: entries, refetch: vi.fn() };

    renderSection(query);

    await userEvent.click(screen.getByRole('button', { name: /Add Person/ }));
    await userEvent.type(screen.getByPlaceholderText('Full Name'), 'Carol');
    await userEvent.click(screen.getByRole('button', { name: 'Create' }));

    expect(createMutation.mutate).toHaveBeenCalledTimes(1);
    expect(createMutation.mutate).toHaveBeenCalledWith({ name: 'Carol' }, expect.any(Object));

    const calls = vi.mocked(createMutation.mutate).mock.calls;
    const options = calls[0]?.[1];
    expect(options).toBeDefined();
    expect(typeof options?.onSuccess).toBe('function');
  });

  it('renders entries without filter', () => {
    const query: RosterEntriesQuery = { isLoading: false, isError: false, data: entries, refetch: vi.fn() };

    renderSection(query);

    expect(screen.getByText('Alice')).toBeInTheDocument();
    expect(screen.getByText('Bob')).toBeInTheDocument();
    expect(screen.queryByText('Filtered: Unassigned')).not.toBeInTheDocument();
    expect(screen.queryByText('Showing unassigned people only.')).not.toBeInTheDocument();
  });

  it('filters to unassigned people when personFilter=unassigned', () => {
    const query: RosterEntriesQuery = { isLoading: false, isError: false, data: entries, refetch: vi.fn() };
    renderSection(query, '/?tab=entries&personFilter=unassigned');

    expect(screen.getByText('Filtered: Unassigned')).toBeInTheDocument();
    expect(screen.getByText('Showing unassigned people only.')).toBeInTheDocument();
    expect(screen.getByText('Bob')).toBeInTheDocument();
    expect(screen.queryByText('Alice')).not.toBeInTheDocument();
  });

  it('filters to queue members when queue=singleton-proposals', () => {
    const query: RosterEntriesQuery = { isLoading: false, isError: false, data: entries, refetch: vi.fn() };

    renderSection(query, '/?tab=entries&queue=singleton-proposals');

    expect(screen.getByText('Alice')).toBeInTheDocument();
    expect(screen.queryByText('Bob')).not.toBeInTheDocument();
    expect(screen.getByText('Showing singleton proposals queue only.')).toBeInTheDocument();
  });

  it('routes singleton-proposals review actions to the workbench scan tab', () => {
    const query: RosterEntriesQuery = { isLoading: false, isError: false, data: entries, refetch: vi.fn() };

    renderSection(query, '/?tab=entries&queue=singleton-proposals');

    expect(screen.getByRole('link', { name: 'Review singleton proposals in Workbench' })).toHaveAttribute(
      'href',
      '#/workbench?tab=scan',
    );
  });

  it('routes needs-confirmation-after-merge review actions to the workbench scan tab', () => {
    const query: RosterEntriesQuery = { isLoading: false, isError: false, data: entries, refetch: vi.fn() };

    renderSection(query, '/?tab=entries&queue=needs-confirmation-after-merge');

    expect(screen.getByRole('link', { name: 'Review merge confirmations in Workbench' })).toHaveAttribute(
      'href',
      '#/workbench?tab=scan',
    );
  });

  it('explains that hard-examples review actions are unavailable until the contract lands', () => {
    const query: RosterEntriesQuery = { isLoading: false, isError: false, data: entries, refetch: vi.fn() };

    renderSection(query, '/?tab=entries&queue=hard-examples');

    expect(
      screen.getByText('Hard-examples review actions stay unavailable here until the dedicated review contract lands.'),
    ).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: /Workbench/i })).not.toBeInTheDocument();
  });

  it('shows filtered empty state and allows clearing the filter', async () => {
    const query: RosterEntriesQuery = {
      isLoading: false,
      isError: false,
      data: [
        {
          id: 3,
          person_uuid: 'person-uuid-chris',
          name: 'Chris',
          tags: [],
          cluster_count: 1,
          clusters: [],
          queue_memberships: [],
          updated_at: new Date().toISOString(),
          source_version: 1,
          projection_status: 'current',
          projection_refreshed_at: new Date().toISOString(),
        },
      ],
      refetch: vi.fn(),
    };

    renderSection(query, '/?tab=entries&personFilter=unassigned');

    expect(screen.getByText('No unassigned people found.')).toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: 'Clear filter' }));

    expect(screen.queryByText('No unassigned people found.')).not.toBeInTheDocument();
    expect(screen.getByText('Chris')).toBeInTheDocument();
    expect(screen.getByTestId('location-search')).toHaveTextContent('?tab=entries');
  });
});
