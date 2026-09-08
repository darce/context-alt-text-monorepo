import { act, render, screen, waitFor, within } from '@testing-library/react';
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
  sprintf: (format: string, ...args: (string | number)[]) => {
    let index = 0;
    return format.replace(/%(s|d)/g, () => String(args[index++]));
  },
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
      screen.getByText('Are you sure you want to delete this person? Assigned faces return to the review queue.'),
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

  /**
   * [COG-02] Directory face column — recognition over recall.
   * Representative rule under test: highest identity_count; ties → cluster_id ASC.
   */
  describe('directory face thumbnails [COG-02]', () => {
    /**
     * Selection fixtures use bbox:null so media_url paints immediately without
     * the canvas-crop Image path. Crop wiring is covered by the dedicated
     * bbox test below (with Image/canvas mocks + act flush).
     */
    const sarahWithFace = makeEntry({
      id: 20,
      person_uuid: 'person-uuid-sarah',
      name: 'Sarah',
      tags: ['fixture-face-sarah'],
      cluster_count: 2,
      // High-count first deliberately: a "last cluster" mutation must not pass.
      clusters: [
        {
          cluster_id: 'cluster-high-count',
          identity_count: 5,
          representative_identity: {
            identity_id: 'identity-sarah-rep',
            media_id: 501,
            media_url: 'https://example.com/opaline-rep.jpg',
            bbox: null,
            similarity: 0.95,
          },
          instances: [],
        },
        {
          cluster_id: 'cluster-low-count',
          identity_count: 1,
          representative_identity: {
            identity_id: 'identity-wrong-face',
            media_id: 900,
            media_url: 'https://example.com/wrong-face.jpg',
            bbox: null,
            similarity: 0.5,
          },
          instances: [],
        },
      ],
    });

    const sarahWithBbox = makeEntry({
      id: 20,
      person_uuid: 'person-uuid-sarah',
      name: 'Sarah',
      tags: ['fixture-face-sarah'],
      cluster_count: 1,
      clusters: [
        {
          cluster_id: 'cluster-high-count',
          identity_count: 5,
          representative_identity: {
            identity_id: 'identity-sarah-rep',
            media_id: 501,
            media_url: 'https://example.com/opaline-rep.jpg',
            bbox: { x: 10, y: 20, width: 30, height: 40 },
            similarity: 0.95,
          },
          instances: [],
        },
      ],
    });

    it('renders the highest-identity_count cluster representative face for a person with clusters [TEST-06]', async () => {
      render(<RosterEntriesTable entries={[sarahWithFace]} />);

      const row = rowForTag('fixture-face-sarah');
      const face = await waitFor(() => {
        const el = row.querySelector('img[data-identity-id="identity-sarah-rep"]');
        expect(el).not.toBeNull();
        return el as HTMLImageElement;
      });
      expect(face).toHaveAttribute('data-media-id', '501');
      // Discrimination: must NOT show the lower-count cluster's face.
      expect(row.querySelector('img[data-identity-id="identity-wrong-face"]')).toBeNull();
      expect(row.querySelector('img[src="https://example.com/wrong-face.jpg"]')).toBeNull();
    });

    it('renders a cropped data: src when the representative has a pixel bbox [COG-02]', async () => {
      // Same canvas/Image harness as IdentityThumbnail lazy-crop tests — DirectoryFace
      // must pass bbox through so the crop path produces a data: URL, not media_url.
      const OriginalImage = globalThis.Image;
      /* Prototype method refs restored after the test; not invoked unbound. */
      // eslint-disable-next-line @typescript-eslint/unbound-method -- restore only
      const originalGetContext = HTMLCanvasElement.prototype.getContext;
      // eslint-disable-next-line @typescript-eslint/unbound-method -- restore only
      const originalToDataURL = HTMLCanvasElement.prototype.toDataURL;

      class MockImage {
        onload: ((this: GlobalEventHandlers, ev: Event) => unknown) | null = null;
        onerror: ((this: GlobalEventHandlers, ev: Event) => unknown) | null = null;
        crossOrigin = '';
        naturalWidth = 200;
        naturalHeight = 200;
        width = 200;
        height = 200;
        private _src = '';
        get src(): string {
          return this._src;
        }
        set src(value: string) {
          this._src = value;
          queueMicrotask(() => {
            const handler = this.onload;
            if (handler) {
              handler.call(this as unknown as GlobalEventHandlers, new Event('load'));
            }
          });
        }
      }
      globalThis.Image = MockImage as unknown as typeof Image;
      HTMLCanvasElement.prototype.getContext = vi.fn(() => ({
        clearRect: vi.fn(),
        drawImage: vi.fn(),
      })) as unknown as typeof HTMLCanvasElement.prototype.getContext;
      HTMLCanvasElement.prototype.toDataURL = vi.fn(() => 'data:image/jpeg;base64,directory-face-crop');

      try {
        render(<RosterEntriesTable entries={[sarahWithBbox]} />);
        // Flush MockImage onload microtask + React state (waitFor alone can miss it).
        await act(async () => {
          await Promise.resolve();
          await Promise.resolve();
          await new Promise((r) => setTimeout(r, 0));
        });
        const row = rowForTag('fixture-face-sarah');
        const face = row.querySelector('img[data-identity-id="identity-sarah-rep"]');
        expect(face).not.toBeNull();
        // Must not paint the raw full-scene media_url when a crop is available.
        expect(face).toHaveAttribute('src', 'data:image/jpeg;base64,directory-face-crop');
        expect(face!.getAttribute('src')?.startsWith('data:')).toBe(true);
      } finally {
        globalThis.Image = OriginalImage;
        HTMLCanvasElement.prototype.getContext = originalGetContext;
        HTMLCanvasElement.prototype.toDataURL = originalToDataURL;
      }
    });

    it('selects the highest-identity_count cluster when it is neither first nor last [TEST-15]', () => {
      // Middle position kills both the naive clusters[0] shortcut and the
      // "last cluster" shortcut: neither returns the correct face here.
      const midHighest = makeEntry({
        id: 22,
        person_uuid: 'person-uuid-mid',
        name: 'Mid',
        tags: ['fixture-face-mid'],
        cluster_count: 3,
        clusters: [
          {
            cluster_id: 'cluster-first-low',
            identity_count: 1,
            representative_identity: {
              identity_id: 'identity-first-low',
              media_id: 601,
              media_url: 'https://example.com/first-low.jpg',
              bbox: null,
              similarity: 0.4,
            },
            instances: [],
          },
          {
            cluster_id: 'cluster-middle-high',
            identity_count: 9,
            representative_identity: {
              identity_id: 'identity-middle-high',
              media_id: 602,
              media_url: 'https://example.com/middle-high.jpg',
              bbox: null,
              similarity: 0.9,
            },
            instances: [],
          },
          {
            cluster_id: 'cluster-last-mid',
            identity_count: 4,
            representative_identity: {
              identity_id: 'identity-last-mid',
              media_id: 603,
              media_url: 'https://example.com/last-mid.jpg',
              bbox: null,
              similarity: 0.6,
            },
            instances: [],
          },
        ],
      });

      render(<RosterEntriesTable entries={[midHighest]} />);

      const row = rowForTag('fixture-face-mid');
      expect(row.querySelector('img')).toHaveAttribute('data-identity-id', 'identity-middle-high');
      expect(row.querySelector('img[data-identity-id="identity-first-low"]')).toBeNull();
      expect(row.querySelector('img[data-identity-id="identity-last-mid"]')).toBeNull();
    });

    it('breaks identity_count ties by cluster_id ascending [TEST-15]', () => {
      // Equal counts, array ordered cluster_id DESC: the documented tie-break
      // must pick cluster-a, so a first-wins implementation fails here.
      const tied = makeEntry({
        id: 23,
        person_uuid: 'person-uuid-tied',
        name: 'Tied',
        tags: ['fixture-face-tied'],
        cluster_count: 2,
        clusters: [
          {
            cluster_id: 'cluster-b',
            identity_count: 3,
            representative_identity: {
              identity_id: 'identity-from-b',
              media_id: 701,
              media_url: 'https://example.com/from-b.jpg',
              bbox: null,
              similarity: 0.7,
            },
            instances: [],
          },
          {
            cluster_id: 'cluster-a',
            identity_count: 3,
            representative_identity: {
              identity_id: 'identity-from-a',
              media_id: 702,
              media_url: 'https://example.com/from-a.jpg',
              bbox: null,
              similarity: 0.7,
            },
            instances: [],
          },
        ],
      });

      render(<RosterEntriesTable entries={[tied]} />);

      const row = rowForTag('fixture-face-tied');
      expect(row.querySelector('img')).toHaveAttribute('data-identity-id', 'identity-from-a');
      expect(row.querySelector('img[data-identity-id="identity-from-b"]')).toBeNull();
    });

    it('picks the same representative across a rerender (deterministic)', async () => {
      const { rerender } = render(<RosterEntriesTable entries={[sarahWithFace]} />);
      const first = await waitFor(() => {
        const el = rowForTag('fixture-face-sarah').querySelector('img');
        expect(el).toHaveAttribute('data-identity-id', 'identity-sarah-rep');
        return el!;
      });

      rerender(<RosterEntriesTable entries={[sarahWithFace]} />);
      const second = await waitFor(() => {
        const el = rowForTag('fixture-face-sarah').querySelector('img');
        expect(el).toHaveAttribute('data-identity-id', 'identity-sarah-rep');
        return el!;
      });
      expect(second.getAttribute('data-identity-id')).toBe(first.getAttribute('data-identity-id'));
    });

    it('renders a deliberate no-face placeholder when the person has zero clusters', () => {
      const noClusters = makeEntry({
        id: 21,
        name: 'No Face Person',
        tags: ['fixture-zero-clusters'],
        clusters: [],
        cluster_count: 0,
      });
      render(<RosterEntriesTable entries={[noClusters]} />);

      const row = rowForTag('fixture-zero-clusters');
      expect(row.querySelector('img')).toBeNull();
      const placeholder = row.querySelector('.acx-cluster-card__face--placeholder');
      expect(placeholder).not.toBeNull();
      expect(placeholder).toHaveAttribute('data-face-missing', 'true');
      // Sized so the row does not collapse [PERC-02].
      expect(placeholder).toHaveAttribute('style');
      expect((placeholder as HTMLElement).style.width).not.toBe('');
      expect((placeholder as HTMLElement).style.height).not.toBe('');
    });

    it('renders the placeholder when representative_identity is null', () => {
      const nullRep = makeEntry({
        id: 22,
        name: 'Null Rep',
        tags: ['fixture-null-rep'],
        cluster_count: 1,
        clusters: [
          {
            cluster_id: 'cluster-null-rep',
            identity_count: 3,
            representative_identity: null,
            instances: [],
          },
        ],
      });
      render(<RosterEntriesTable entries={[nullRep]} />);

      const row = rowForTag('fixture-null-rep');
      expect(row.querySelector('img')).toBeNull();
      expect(row.querySelector('.acx-cluster-card__face--placeholder[data-face-missing="true"]')).not.toBeNull();
    });

    it('renders the placeholder when representative media_url is null', () => {
      const nullUrl = makeEntry({
        id: 23,
        name: 'Null Url',
        tags: ['fixture-null-url'],
        cluster_count: 1,
        clusters: [
          {
            cluster_id: 'cluster-null-url',
            identity_count: 2,
            representative_identity: {
              identity_id: 'identity-no-url',
              media_id: 777,
              media_url: null,
              bbox: null,
              similarity: 0.8,
            },
            instances: [],
          },
        ],
      });
      render(<RosterEntriesTable entries={[nullUrl]} />);

      const row = rowForTag('fixture-null-url');
      expect(row.querySelector('img')).toBeNull();
      expect(row.querySelector('.acx-cluster-card__face--placeholder[data-face-missing="true"]')).not.toBeNull();
    });

    it('does not announce the face as a duplicate of the person name [A11Y-21]', async () => {
      render(<RosterEntriesTable entries={[sarahWithFace]} />);

      const row = rowForTag('fixture-face-sarah');
      const face = await waitFor(() => {
        const el = row.querySelector('img');
        expect(el).not.toBeNull();
        return el!;
      });
      // Decorative: empty alt so the name cell carries the row [A11Y-21].
      expect(face).toHaveAttribute('alt', '');

      // Accessible name of the row must not contain "Sarah" twice (img alt + text).
      const nameMatches = (row.textContent ?? '').match(/Sarah/g) ?? [];
      // textContent excludes alt; use accessible name via the name cell + img role.
      // Empty-alt images are presentational — they must not contribute a second "Sarah".
      expect(face.getAttribute('alt')).not.toContain('Sarah');
      // The visible name appears once in the identity cell text.
      expect(nameMatches.filter((m) => m === 'Sarah')).toHaveLength(1);
    });

    /**
     * [S6-BR-03] Unnamed people have an empty <strong> beside the face — empty
     * alt is only valid when equivalent text is present (WCAG 1.1.1). The face
     * must expose a non-empty accessible name.
     */
    it('gives unnamed face thumbnails a non-empty accessible name [S6-BR-03]', async () => {
      const unnamedWithFace = makeEntry({
        id: 30,
        person_uuid: 'person-uuid-unnamed-face',
        name: '',
        tags: ['fixture-unnamed-face'],
        cluster_count: 1,
        clusters: [
          {
            cluster_id: 'cluster-unnamed-face',
            identity_count: 2,
            representative_identity: {
              identity_id: 'identity-unnamed-face',
              media_id: 808,
              media_url: 'https://example.com/unnamed-face.jpg',
              bbox: null,
              similarity: 0.7,
            },
            instances: [],
          },
        ],
      });

      render(<RosterEntriesTable entries={[unnamedWithFace]} />);

      const row = rowForTag('fixture-unnamed-face');
      const face = await waitFor(() => {
        // role=img with a non-empty accessible name — not alt="".
        const el = within(row).getByRole('img');
        expect(el).toBeTruthy();
        return el;
      });

      const accessibleName = face.getAttribute('alt') ?? face.getAttribute('aria-label') ?? '';
      expect(accessibleName.trim().length).toBeGreaterThan(0);
      // Empty alt is the bug: name cell is blank so the face IS the cue.
      expect(face.getAttribute('alt')).not.toBe('');
      // Default IdentityThumbnail alt includes media id when name is absent.
      expect(accessibleName).toMatch(/808|Identity|media/i);
    });
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
    await userEvent.type(screen.getByRole('textbox', { name: 'Full name' }), 'Carol');
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

    expect(screen.getByRole('link', { name: 'Review singleton proposals in the Review Queue' })).toHaveAttribute(
      'href',
      '#/workbench?tab=scan',
    );
  });

  it('routes needs-confirmation-after-merge review actions to the workbench scan tab', () => {
    const query: RosterEntriesQuery = { isLoading: false, isError: false, data: entries, refetch: vi.fn() };

    renderSection(query, '/?tab=entries&queue=needs-confirmation-after-merge');

    expect(screen.getByRole('link', { name: 'Review merge confirmations in the Review Queue' })).toHaveAttribute(
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
