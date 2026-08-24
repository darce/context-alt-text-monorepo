import { act, fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {
  MemoryRouter,
  Route,
  Routes,
  UNSAFE_createMemoryHistory as createMemoryHistory,
  unstable_HistoryRouter as HistoryRouter,
  useLocation,
} from 'react-router-dom';
import { vi } from 'vitest';

import type { RosterEntry } from '../../../api/rosterApi';
import { useCreatePerson, useDeletePerson, useUpdatePerson } from '../../../hooks/useRosterHooks';
import { createMockMutation } from '../../../test-utils/mockHooks';
import { RosterEntriesSection, SEARCH_STATUS_DEBOUNCE_MS } from '../RosterEntriesSection';
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

const directory: RosterEntry[] = [
  makeEntry({
    id: 1,
    person_uuid: 'person-uuid-alice',
    name: 'Alice Anderson',
    tags: ['family'],
    cluster_count: 2,
    queue_memberships: ['singleton-proposals'],
  }),
  makeEntry({
    id: 2,
    person_uuid: 'person-uuid-bob',
    name: 'Bob Baker',
    tags: ['work'],
    cluster_count: 0,
    queue_memberships: ['hard-examples'],
  }),
  makeEntry({
    id: 3,
    person_uuid: 'person-uuid-sarah',
    name: 'Sarah Chen',
    tags: ['hard-examples-tag'],
    cluster_count: 1,
    queue_memberships: ['hard-examples'],
  }),
  makeEntry({
    id: 4,
    person_uuid: 'person-uuid-unnamed',
    name: '',
    tags: ['orphan'],
    cluster_count: 0,
    queue_memberships: [],
  }),
];

const readyQuery = (data: RosterEntry[] = directory): RosterEntriesQuery => ({
  isLoading: false,
  isError: false,
  data,
  refetch: vi.fn(),
});

const LocationProbe = () => {
  const location = useLocation();
  return <output data-testid="location-search">{location.search}</output>;
};

const createMutation = createMockMutation<
  RosterEntry,
  Error,
  { name: string; tags?: string[] },
  { previousEntries: RosterEntry[] | undefined; optimisticId: number }
>({
  mutate: vi.fn(),
  isPending: false,
});
const updateMutation = createMockMutation({ mutate: vi.fn(), isPending: false });
const deleteMutation = createMockMutation({ mutate: vi.fn(), isPending: false });

const renderSection = (query: RosterEntriesQuery, route = '/?tab=entries') =>
  render(
    <MemoryRouter initialEntries={[route]}>
      <RosterEntriesSection query={query} />
      <LocationProbe />
    </MemoryRouter>,
  );

const renderSectionWithHistory = (
  history: ReturnType<typeof createMemoryHistory>,
  query: RosterEntriesQuery,
) =>
  render(
    <HistoryRouter history={history}>
      <Routes>
        <Route
          path="*"
          element={
            <>
              <RosterEntriesSection query={query} />
              <LocationProbe />
            </>
          }
        />
      </Routes>
    </HistoryRouter>,
  );

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(useCreatePerson).mockReturnValue(createMutation);
  vi.mocked(useUpdatePerson).mockReturnValue(updateMutation as never);
  vi.mocked(useDeletePerson).mockReturnValue(deleteMutation as never);
});

describe('RosterEntriesSection directory search [NAV-10]', () => {
  /**
   * Headline [TEST-06]: with several people loaded, typing a name shows only
   * the matching person. Before the change there is no searchbox, so this
   * fails at getByRole('searchbox').
   */
  it('narrows the directory to people whose name matches the typed query', async () => {
    const user = userEvent.setup();
    renderSection(readyQuery());

    // Discrimination: all three named people are present before search.
    expect(screen.getByText('Alice Anderson')).toBeInTheDocument();
    expect(screen.getByText('Bob Baker')).toBeInTheDocument();
    expect(screen.getByText('Sarah Chen')).toBeInTheDocument();

    const search = screen.getByRole('searchbox', { name: /search people/i });
    await user.type(search, 'Sarah');

    expect(screen.getByText('Sarah Chen')).toBeInTheDocument();
    expect(screen.queryByText('Alice Anderson')).not.toBeInTheDocument();
    expect(screen.queryByText('Bob Baker')).not.toBeInTheDocument();
  });

  it('composes search with an active queue filter (AND, not replace)', async () => {
    const user = userEvent.setup();
    // hard-examples queue: Bob + Sarah. Alice is singleton-proposals only.
    renderSection(readyQuery(), '/?tab=entries&queue=hard-examples');

    expect(screen.getByText('Bob Baker')).toBeInTheDocument();
    expect(screen.getByText('Sarah Chen')).toBeInTheDocument();
    expect(screen.queryByText('Alice Anderson')).not.toBeInTheDocument();

    const search = screen.getByRole('searchbox', { name: /search people/i });
    await user.type(search, 'Alice');

    // Alice matches the name but is outside the queue — must stay hidden.
    // A replace-the-filter bug would surface Alice and hide Bob/Sarah.
    expect(screen.queryByText('Alice Anderson')).not.toBeInTheDocument();
    expect(screen.queryByText('Bob Baker')).not.toBeInTheDocument();
    expect(screen.queryByText('Sarah Chen')).not.toBeInTheDocument();
    expect(screen.getByText('No people match “Alice” within the current filter.')).toBeInTheDocument();

    await user.clear(search);
    await user.type(search, 'Sarah');

    expect(screen.getByText('Sarah Chen')).toBeInTheDocument();
    expect(screen.queryByText('Bob Baker')).not.toBeInTheDocument();
    expect(screen.queryByText('Alice Anderson')).not.toBeInTheDocument();
  });

  it('matches case-insensitively and tolerates surrounding whitespace in the query', async () => {
    const user = userEvent.setup();
    renderSection(readyQuery());

    const search = screen.getByRole('searchbox', { name: /search people/i });
    // Leading/trailing spaces + mixed case — must still find Sarah.
    await user.type(search, '  sArAh  ');

    expect(screen.getByText('Sarah Chen')).toBeInTheDocument();
    expect(screen.queryByText('Alice Anderson')).not.toBeInTheDocument();
    expect(screen.queryByText('Bob Baker')).not.toBeInTheDocument();
  });

  it('matches tags as well as names', async () => {
    const user = userEvent.setup();
    renderSection(readyQuery());

    const search = screen.getByRole('searchbox', { name: /search people/i });
    await user.type(search, 'family');

    // Alice has tag "family"; nobody else does.
    expect(screen.getByText('Alice Anderson')).toBeInTheDocument();
    expect(screen.queryByText('Bob Baker')).not.toBeInTheDocument();
    expect(screen.queryByText('Sarah Chen')).not.toBeInTheDocument();
  });

  it('keeps empty-search, filter-empty, and true-zero copy distinct', () => {
    // --- Case 1: true zero (no people at all) ---
    const { unmount: unmountZero } = renderSection(readyQuery([]));
    expect(screen.getByTestId('roster-zero-state')).toBeInTheDocument();
    expect(screen.getByText('No people yet')).toBeInTheDocument();
    expect(
      screen.getByText('Add someone manually or run a scan to discover faces from your media library.'),
    ).toBeInTheDocument();
    expect(screen.queryByText(/No people match/)).not.toBeInTheDocument();
    expect(screen.queryByText('No unassigned people found.')).not.toBeInTheDocument();
    expect(screen.queryByRole('searchbox', { name: /search people/i })).not.toBeInTheDocument();
    unmountZero();

    // --- Case 2: categorical filter matched nothing (no search) ---
    const assignedOnly = [
      makeEntry({
        id: 10,
        person_uuid: 'person-uuid-chris',
        name: 'Chris',
        tags: [],
        cluster_count: 1,
        queue_memberships: [],
      }),
    ];
    const { unmount: unmountFilter } = renderSection(
      readyQuery(assignedOnly),
      '/?tab=entries&personFilter=unassigned',
    );
    expect(screen.getByText('No unassigned people found.')).toBeInTheDocument();
    expect(screen.queryByTestId('roster-zero-state')).not.toBeInTheDocument();
    expect(screen.queryByText('No people yet')).not.toBeInTheDocument();
    expect(screen.queryByText(/No people match/)).not.toBeInTheDocument();
    unmountFilter();

    // --- Case 3: search matched nothing (roster has people) ---
    renderSection(readyQuery(), '/?tab=entries&s=zzznobody');
    expect(screen.getByText('No people match “zzznobody”.')).toBeInTheDocument();
    expect(screen.queryByTestId('roster-zero-state')).not.toBeInTheDocument();
    expect(screen.queryByText('No people yet')).not.toBeInTheDocument();
    expect(screen.queryByText('No unassigned people found.')).not.toBeInTheDocument();
    // Recovery affordance is present.
    expect(screen.getByRole('button', { name: 'Clear search' })).toBeInTheDocument();
  });

  it('names both axes when filter and search together yield nothing', () => {
    renderSection(readyQuery(), '/?tab=entries&queue=hard-examples&s=Alice');

    // Must not blame only the filter or only the search.
    expect(screen.getByText('No people match “Alice” within the current filter.')).toBeInTheDocument();
    expect(screen.queryByText('No people in hard examples queue.')).not.toBeInTheDocument();
    expect(screen.queryByText('No people match “Alice”.')).not.toBeInTheDocument();
    expect(screen.queryByTestId('roster-zero-state')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Clear search' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Clear filter' })).toBeInTheDocument();
  });

  it('clearing the search restores the filter-narrowed list without clearing the filter', async () => {
    const user = userEvent.setup();
    renderSection(readyQuery(), '/?tab=entries&queue=hard-examples&s=Sarah');

    expect(screen.getByText('Sarah Chen')).toBeInTheDocument();
    expect(screen.queryByText('Bob Baker')).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Clear search' }));

    // Filter still active: Bob (hard-examples) returns; Alice (other queue) does not.
    expect(screen.getByText('Sarah Chen')).toBeInTheDocument();
    expect(screen.getByText('Bob Baker')).toBeInTheDocument();
    expect(screen.queryByText('Alice Anderson')).not.toBeInTheDocument();
    expect(screen.getByText('Filtered: Hard examples')).toBeInTheDocument();
    expect(screen.getByText('Showing hard examples queue only.')).toBeInTheDocument();
    expect(screen.getByTestId('location-search')).toHaveTextContent('queue=hard-examples');
    expect(screen.getByTestId('location-search')).not.toHaveTextContent('s=');
  });

  it('round-trips the query through the URL and replaces history (no push per keystroke)', async () => {
    const user = userEvent.setup();
    const history = createMemoryHistory({ initialEntries: ['/?tab=entries'] });
    // Seed one push so a mistaken {replace:false} would advance index past this baseline.
    history.push('/?tab=entries&s=seed');
    const startIndex = history.index;
    expect(startIndex).toBe(1);

    renderSectionWithHistory(history, readyQuery());

    const search = screen.getByRole('searchbox', { name: /search people/i });
    await user.clear(search);
    await user.type(search, 'Bob');

    // Assert on the memory history object — HistoryRouter replace updates history
    // even when a sibling useLocation probe can lag behind in this RR version.
    expect(history.location.search).toContain('s=Bob');
    expect(screen.getByText('Bob Baker')).toBeInTheDocument();
    expect(screen.queryByText('Alice Anderson')).not.toBeInTheDocument();
    // replace keeps index; push-per-keystroke would yield startIndex + len('Bob') (+ clear).
    expect(history.index).toBe(startIndex);
  });

  it('exposes the search control as an accessible searchbox by name', () => {
    renderSection(readyQuery());

    // Must use role+name, not placeholder — A11Y-02.
    const search = screen.getByRole('searchbox', { name: 'Search people' });
    expect(search).toHaveAttribute('type', 'search');
    expect(search).toBeEnabled();
  });

  it('regression pin: personFilter=unassigned badge/status/empty unchanged with no search', () => {
    const assignedOnly = [
      makeEntry({
        id: 10,
        person_uuid: 'person-uuid-chris',
        name: 'Chris',
        tags: [],
        cluster_count: 1,
        queue_memberships: [],
      }),
    ];
    const { unmount } = renderSection(readyQuery(directory), '/?tab=entries&personFilter=unassigned');

    expect(screen.getByText('Filtered: Unassigned')).toBeInTheDocument();
    expect(screen.getByText('Showing unassigned people only.')).toBeInTheDocument();
    // Bob is unassigned (cluster_count 0); Alice is not.
    expect(screen.getByText('Bob Baker')).toBeInTheDocument();
    expect(screen.queryByText('Alice Anderson')).not.toBeInTheDocument();
    // Clear filter label is unchanged; no Clear search without an active search.
    expect(screen.getByRole('button', { name: 'Clear filter' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Clear search' })).not.toBeInTheDocument();
    unmount();

    renderSection(readyQuery(assignedOnly), '/?tab=entries&personFilter=unassigned');
    expect(screen.getByText('No unassigned people found.')).toBeInTheDocument();
  });

  it('regression pin: queue filter badge/status/empty unchanged with no search', () => {
    const noQueue = [
      makeEntry({
        id: 11,
        person_uuid: 'person-uuid-dana',
        name: 'Dana',
        tags: [],
        cluster_count: 0,
        queue_memberships: [],
      }),
    ];
    const { unmount } = renderSection(readyQuery(directory), '/?tab=entries&queue=singleton-proposals');

    expect(screen.getByText('Filtered: Singleton proposals')).toBeInTheDocument();
    expect(screen.getByText('Showing singleton proposals queue only.')).toBeInTheDocument();
    expect(screen.getByText('Alice Anderson')).toBeInTheDocument();
    expect(screen.queryByText('Bob Baker')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Clear filter' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Clear search' })).not.toBeInTheDocument();
    unmount();

    renderSection(readyQuery(noQueue), '/?tab=entries&queue=singleton-proposals');
    expect(screen.getByText('No people in singleton proposals queue.')).toBeInTheDocument();
  });

  it('does not silently drop unnamed people from a tag search that matches them', async () => {
    const user = userEvent.setup();
    renderSection(readyQuery());

    const search = screen.getByRole('searchbox', { name: /search people/i });
    await user.type(search, 'orphan');

    // Unnamed row is identified by its tag cell when name is blank.
    expect(screen.getByText('orphan')).toBeInTheDocument();
    expect(screen.queryByText('Alice Anderson')).not.toBeInTheDocument();
  });

  it('loading and error states take precedence over empty-search messaging', () => {
    const { unmount: unmountLoading } = renderSection(
      { isLoading: true, isError: false, data: undefined, refetch: vi.fn() },
      '/?tab=entries&s=Sarah',
    );
    expect(screen.getByText('Loading roster entries…')).toBeInTheDocument();
    expect(screen.queryByText(/No people match/)).not.toBeInTheDocument();
    unmountLoading();

    const refetch = vi.fn();
    renderSection(
      { isLoading: false, isError: true, data: undefined, refetch },
      '/?tab=entries&s=Sarah',
    );
    expect(screen.getByText('Unable to load roster entries.')).toBeInTheDocument();
    expect(screen.queryByText(/No people match/)).not.toBeInTheDocument();
  });

  // The harness renders a <output data-testid="location-search"> (implicit
  // role=status), so bare getByRole('status') is ambiguous — scope to the
  // section's filter region.
  const getSearchStatus = (): HTMLElement => {
    const region = screen
      .getAllByRole('status')
      .find((el) => el.classList.contains('acx-roster-section__filter'));
    if (!region) {
      throw new Error('roster search status region not found');
    }
    return region;
  };

  /**
   * [ROSTER-W-03] [WBUX-5-R2-S6-BR-04] [TEST-15]
   * Filter the table immediately, but do not rewrite the role=status search
   * summary on every keystroke (WCAG 4.1.3 noise). Intermediate counts must
   * be observable here — a final-state-only assertion would stay green
   * without debounce.
   */
  it('does not announce search status per keystroke; settles to the final count [ROSTER-W-03]', () => {
    vi.useFakeTimers();
    try {
      renderSection(readyQuery());
      const search = screen.getByRole('searchbox', { name: /search people/i });

      fireEvent.change(search, { target: { value: 'S' } });
      // Immediate filter: "S" matches Alice Anderson + Sarah Chen.
      expect(screen.getByText('Alice Anderson')).toBeInTheDocument();
      expect(screen.getByText('Sarah Chen')).toBeInTheDocument();
      // Goes red if status copies the live query (Showing 2 matching “S”).
      expect(screen.queryByText(/Showing 2 matching/)).not.toBeInTheDocument();

      fireEvent.change(search, { target: { value: 'Sa' } });
      expect(screen.queryByText('Alice Anderson')).not.toBeInTheDocument();
      expect(screen.getByText('Sarah Chen')).toBeInTheDocument();
      expect(screen.queryByText(/Showing \d+ matching/)).not.toBeInTheDocument();

      fireEvent.change(search, { target: { value: 'Sarah' } });
      expect(screen.queryByText(/Showing \d+ matching/)).not.toBeInTheDocument();

      act(() => {
        vi.advanceTimersByTime(SEARCH_STATUS_DEBOUNCE_MS - 1);
      });
      expect(screen.queryByText(/Showing \d+ matching/)).not.toBeInTheDocument();

      act(() => {
        vi.advanceTimersByTime(1);
      });
      expect(within(getSearchStatus()).getByText('Showing 1 matching “Sarah”.')).toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });

  it('announces a zero-match search immediately through role=status [E21-19-REV1-03]', () => {
    vi.useFakeTimers();
    try {
      renderSection(readyQuery());
      const search = screen.getByRole('searchbox', { name: /search people/i });

      fireEvent.change(search, { target: { value: 'Sarah' } });
      act(() => {
        vi.advanceTimersByTime(SEARCH_STATUS_DEBOUNCE_MS);
      });
      expect(within(getSearchStatus()).getByText('Showing 1 matching “Sarah”.')).toBeInTheDocument();

      fireEvent.change(search, { target: { value: 'Sarahzzz' } });
      // Goes red if empty outcome waits for debounce or lives outside status.
      const status = getSearchStatus();
      expect(within(status).queryByText(/Showing \d+ matching/)).not.toBeInTheDocument();
      expect(within(status).getByText('No people match “Sarahzzz”.')).toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });

  it('drops the settled matching count immediately when Clear search is clicked [E21-19-REV1-03]', () => {
    vi.useFakeTimers();
    try {
      renderSection(readyQuery());
      const search = screen.getByRole('searchbox', { name: /search people/i });

      fireEvent.change(search, { target: { value: 'Sarah' } });
      act(() => {
        vi.advanceTimersByTime(SEARCH_STATUS_DEBOUNCE_MS);
      });
      expect(within(getSearchStatus()).getByText('Showing 1 matching “Sarah”.')).toBeInTheDocument();

      fireEvent.click(screen.getByRole('button', { name: 'Clear search' }));
      // Goes red if the stale count stays announced for the 300ms window.
      expect(screen.queryByText(/Showing \d+ matching/)).not.toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });

  it('does not warn or set state after unmount mid-status debounce [E21-19-REV1-03]', () => {
    vi.useFakeTimers();
    const errorSpy = vi.spyOn(console, 'error').mockImplementation(() => undefined);
    try {
      const { unmount } = renderSection(readyQuery());
      fireEvent.change(screen.getByRole('searchbox', { name: /search people/i }), {
        target: { value: 'S' },
      });
      unmount();
      act(() => {
        vi.advanceTimersByTime(SEARCH_STATUS_DEBOUNCE_MS);
      });
      expect(errorSpy).not.toHaveBeenCalled();
    } finally {
      errorSpy.mockRestore();
      vi.useRealTimers();
    }
  });

  it('Clear filter does not wipe an active search (separate affordances)', async () => {
    const user = userEvent.setup();
    renderSection(readyQuery(), '/?tab=entries&queue=hard-examples&s=Sarah');

    await user.click(screen.getByRole('button', { name: 'Clear filter' }));

    // Search remains; filter is gone — Alice would match "Sarah"? No. Sarah still matches.
    expect(screen.getByText('Sarah Chen')).toBeInTheDocument();
    expect(screen.getByTestId('location-search').textContent).toContain('s=Sarah');
    expect(screen.getByTestId('location-search').textContent).not.toContain('queue=');
    expect(screen.queryByText('Filtered: Hard examples')).not.toBeInTheDocument();
  });
});

const RESERVED_LABEL_MESSAGE =
  'This name format is reserved for automatic face group IDs. Choose a descriptive name.';

describe('RosterEntriesSection create reserved-label gate (BR-60)', () => {
  it('rejects cluster-7 without calling createPerson and shows reserved message', async () => {
    const user = userEvent.setup();
    renderSection(readyQuery());

    await user.click(screen.getByRole('button', { name: /Add Person/i }));
    await user.type(screen.getByRole('textbox', { name: 'Full name' }), 'cluster-7');
    await user.click(screen.getByRole('button', { name: /^Create$/i }));

    expect(createMutation.mutate).not.toHaveBeenCalled();
    expect(screen.getByRole('alert')).toHaveTextContent(RESERVED_LABEL_MESSAGE);
  });

  it('creates Pat Rivera via createPerson (human-label control)', async () => {
    const user = userEvent.setup();
    renderSection(readyQuery());

    await user.click(screen.getByRole('button', { name: /Add Person/i }));
    await user.type(screen.getByRole('textbox', { name: 'Full name' }), 'Pat Rivera');
    await user.click(screen.getByRole('button', { name: /^Create$/i }));

    expect(createMutation.mutate).toHaveBeenCalledTimes(1);
    expect(createMutation.mutate).toHaveBeenCalledWith(
      { name: 'Pat Rivera' },
      expect.any(Object),
    );
    expect(screen.queryByText(RESERVED_LABEL_MESSAGE)).not.toBeInTheDocument();
  });
});
