import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import * as i18n from '@wordpress/i18n';
import type { RepeatedRegionEvidenceView } from '../repeatedRegionEvidence';

import { IdentityClusterItem } from '../IdentityClusterItem';
import type { ClusterGroup } from '../types';
import { groupIdentitiesByClusters } from '../utils';

vi.mock('@wordpress/i18n', async () => {
  const actual = await vi.importActual<typeof import('@wordpress/i18n')>('@wordpress/i18n');
  return { ...actual, _n: vi.fn((one: string, many: string, n: number) => n === 1 ? one : many) };
});

const MATCH_DEBOUNCE_MS = 300;

const findClusterByLabel = vi.fn();
const splitMock = vi.fn();

vi.mock('../useClusterSuggestions', () => ({
  useClusterSuggestions: () => ({
    options: [],
    isLoading: false,
    collisionsByLabel: new Map(),
    findClusterByLabel,
    atRestTotal: 80,
    atRestTruncated: true,
    isAtRestMode: true,
  }),
}));

vi.mock('../useClusterMutations', () => ({
  useClusterMutations: () => ({
    isPending: false,
    isReverting: false,
    merge: vi.fn(),
    assignToCluster: vi.fn(),
    rename: vi.fn(),
    createClusterForIdentity: vi.fn(),
    reassign: vi.fn(),
    split: splitMock,
    revertMerge: vi.fn(),
    rejectSuggestion: vi.fn(),
    splitGate: { disabled: false, title: undefined, 'aria-disabled': false },
  }),
}));

const CLUSTER_ID = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee';

const member = (overrides: Partial<ClusterGroup['members'][number]> = {}): ClusterGroup['members'][number] => ({
  identity_id: 'id-1',
  representative_id: 'rep-1',
  media_id: 1,
  cluster_id: 'editable',
  cluster_label: 'bob',
  is_auto_label: false,
  is_pinned: false,
  bbox: { x: 0, y: 0, width: 1, height: 1 },
  confidence: 1,
  similarity: 1,
  detected_at: '',
  ...overrides,
});

const bobCluster = (): ClusterGroup => ({
  key: 'editable',
  clusterId: 'editable',
  label: 'bob',
  isAutoLabel: false,
  clusteringPending: false,
  members: [member()],
});

const unlabeledCluster = (overrides: Partial<ClusterGroup> = {}): ClusterGroup => ({
  key: 'unlabeled',
  clusterId: CLUSTER_ID,
  label: null,
  isAutoLabel: false,
  clusteringPending: false,
  members: [
    member({
      cluster_id: CLUSTER_ID,
      cluster_label: null,
    }),
  ],
  ...overrides,
});

const renderItem = (cluster: ClusterGroup = bobCluster(), { canMutate = true }: { canMutate?: boolean } = {}) => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <IdentityClusterItem cluster={cluster} canLabel canMutate={canMutate} />
    </QueryClientProvider>,
  );
};

const flushMatchDebounce = async () => {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(MATCH_DEBOUNCE_MS);
    await Promise.resolve();
    await Promise.resolve();
  });
};

describe('IdentityClusterItem proactive match (UXP-3-BR-39)', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    findClusterByLabel.mockReset();
  });

  afterEach(() => {
    cleanup();
    vi.useRealTimers();
  });

  it('bob→Bob with a different Bob cluster arms Merge-with preview', async () => {
    findClusterByLabel.mockResolvedValue({
      id: 'other-bob',
      label: 'Bob',
      identityCount: 2,
    });

    renderItem();

    fireEvent.click(screen.getByRole('button', { name: 'bob' }));
    fireEvent.change(screen.getByPlaceholderText(/enter a name/i), { target: { value: 'Bob' } });
    await flushMatchDebounce();

    expect(findClusterByLabel).toHaveBeenCalledWith('Bob', expect.any(AbortSignal));
    expect(screen.getByRole('button', { name: /Merge with Bob/i })).toBeInTheDocument();
  });

  it('exact same label does not arm proactive match / Merge-with preview', async () => {
    findClusterByLabel.mockResolvedValue({
      id: 'other-bob',
      label: 'bob',
      identityCount: 2,
    });

    renderItem();

    fireEvent.click(screen.getByRole('button', { name: 'bob' }));
    // Re-assert exact current label (startEditing already seeds it).
    fireEvent.change(screen.getByPlaceholderText(/enter a name/i), { target: { value: 'bob' } });
    await flushMatchDebounce();

    expect(findClusterByLabel).not.toHaveBeenCalled();
    expect(screen.queryByRole('button', { name: /Merge with/i })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^Save name$/i })).toBeInTheDocument();
  });

  it('exact-dupe remote "bob" + typed "Bob" keeps Save (no Merge-with) — UXP-3-BR-44', async () => {
    // Remote match label exactly equals current cluster label → save-path renames (BR-40).
    // Preview must not promise Merge/Assign.
    findClusterByLabel.mockResolvedValue({
      id: 'dupe-bob',
      label: 'bob',
      identityCount: 3,
    });

    renderItem();

    fireEvent.click(screen.getByRole('button', { name: 'bob' }));
    fireEvent.change(screen.getByPlaceholderText(/enter a name/i), { target: { value: 'Bob' } });
    await flushMatchDebounce();

    expect(findClusterByLabel).toHaveBeenCalledWith('Bob', expect.any(AbortSignal));
    expect(screen.queryByRole('button', { name: /Merge with/i })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^Save name$/i })).toBeInTheDocument();
  });

  it('reverting to exact label aborts in-flight match so preview stays Save — UXP-3-BR-45', async () => {
    let resolveMatch!: (value: { id: string; label: string; identityCount: number }) => void;
    const deferred = new Promise<{ id: string; label: string; identityCount: number }>((resolve) => {
      resolveMatch = resolve;
    });
    findClusterByLabel.mockImplementation((_label: string, signal?: AbortSignal) =>
      deferred.then((value) => {
        if (signal?.aborted) {
          const err = new Error('Aborted');
          err.name = 'AbortError';
          throw err;
        }
        return value;
      }),
    );

    renderItem();

    fireEvent.click(screen.getByRole('button', { name: 'bob' }));
    const input = screen.getByPlaceholderText(/enter a name/i);
    fireEvent.change(input, { target: { value: 'Bob' } });
    await flushMatchDebounce();

    expect(findClusterByLabel).toHaveBeenCalledWith('Bob', expect.any(AbortSignal));

    // Bail to exact current label before the deferred response settles.
    fireEvent.change(input, { target: { value: 'bob' } });
    await act(async () => {
      await Promise.resolve();
    });

    await act(async () => {
      resolveMatch({ id: 'other-bob', label: 'Bob', identityCount: 2 });
      await deferred;
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(screen.queryByRole('button', { name: /Merge with/i })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^Save name$/i })).toBeInTheDocument();
  });
});

describe('IdentityClusterItem Library save copy (UXW2-3-R1-16i)', () => {
  afterEach(() => {
    cleanup();
  });

  it('default Library row commit button is Save name (UXW2-3-R1-16i)', () => {
    renderItem();
    fireEvent.click(screen.getByRole('button', { name: 'bob' }));
    expect(screen.getByRole('button', { name: 'Save name' })).toBeInTheDocument();
  });
});

describe('IdentityClusterItem at-rest hint wiring (REV2-01)', () => {
  afterEach(() => {
    cleanup();
  });

  it('passes at-rest truncation props through so the labelled editor describes the truncated page', () => {
    renderItem();

    fireEvent.click(screen.getByRole('button', { name: 'bob' }));

    const hint = screen.getByText(/Showing \d+ of 80 labels/);
    expect(hint).toBeInTheDocument();
    expect(screen.getByRole('combobox', { name: 'Person name' })).toHaveAccessibleDescription(hint.textContent ?? '');
  });
});

describe('IdentityClusterItem unlabeled copy (UXW2-4-R7E-02)', () => {
  afterEach(() => {
    cleanup();
  });

  it('renders Unnamed person when the cluster has a UUID and no human label', () => {
    renderItem(unlabeledCluster());

    expect(screen.getByRole('button', { name: 'Unnamed person' })).toBeInTheDocument();
    expect(screen.queryByText(/cluster-[0-9a-f]{8}/i)).not.toBeInTheDocument();
  });

  it('does not render auto-shape cluster-* as a person name', () => {
    renderItem(
      unlabeledCluster({
        label: 'cluster-7',
        members: [member({ cluster_id: CLUSTER_ID, cluster_label: 'cluster-7' })],
      }),
    );

    expect(screen.queryByRole('button', { name: 'cluster-7' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Unnamed person' })).toBeInTheDocument();
  });
});

describe('IdentityClusterItem mutation affordance gates (WBUX6-W3-L6-02 / WBUX6-W3-L6-03)', () => {
  afterEach(() => {
    cleanup();
  });

  const splitButton = () => screen.queryByRole('button', { name: /split group/i });
  const removeButton = () => screen.queryByRole('button', { name: /remove from group/i });

  // A group whose own clusterId is null but whose member still carries one:
  // getEditableClusterId falls back to the member, so the row stays editable
  // (canEdit) and only the split gate observes the missing group id. This is the
  // only fixture shape that isolates `Boolean(cluster.clusterId)` from canEdit.
  const memberOnlyClusterId = (): ClusterGroup => ({
    key: 'member-only',
    clusterId: null,
    label: 'bob',
    isAutoLabel: false,
    clusteringPending: false,
    members: [member({ cluster_id: 'editable' })],
  });

  const twoMemberCluster = (): ClusterGroup => ({
    ...bobCluster(),
    members: [member(), member({ identity_id: 'id-2', representative_id: 'rep-2', media_id: 2 })],
  });

  it('offers Split only when the group itself carries a cluster id', () => {
    renderItem(twoMemberCluster());
    expect(screen.getByText('Not the same person?')).toBeVisible();
    expect(splitButton()).toBeInTheDocument();

    cleanup();

    renderItem(memberOnlyClusterId());
    // Row is still editable via the member-derived id, so the absence below is
    // the split gate, not a blanket "no actions" early return.
    expect(screen.getByRole('button', { name: /edit label/i })).toBeInTheDocument();
    expect(splitButton()).not.toBeInTheDocument();
  });

  it('offers Remove from group only for a single-member group', () => {
    renderItem(bobCluster());
    expect(removeButton()).toBeInTheDocument();

    cleanup();

    renderItem(twoMemberCluster());
    expect(screen.getByRole('button', { name: /edit label/i })).toBeInTheDocument();
    expect(removeButton()).not.toBeInTheDocument();
  });

  it('withholds both mutating affordances when canMutate is false', () => {
    renderItem(bobCluster(), { canMutate: false });

    expect(screen.getByRole('button', { name: /edit label/i })).toBeInTheDocument();
    expect(splitButton()).not.toBeInTheDocument();
    expect(removeButton()).not.toBeInTheDocument();
  });
});

describe('IdentityClusterItem split routing across a person-spanning group (IDCHIP-1-GROUP-R-02)', () => {
  afterEach(() => {
    cleanup();
    splitMock.mockReset();
  });

  const personSpanningCluster = (): ClusterGroup => ({
    key: 'person:7',
    clusterId: 'cluster-a',
    personId: '7',
    clusterIds: ['cluster-a', 'cluster-b'],
    identityClusterIds: { 'id-1': 'cluster-a', 'id-2': 'cluster-a', 'id-3': 'cluster-b' },
    label: 'bob',
    isAutoLabel: false,
    clusteringPending: false,
    members: [
      member({ identity_id: 'id-1', media_id: 1, cluster_id: 'cluster-a' }),
      member({ identity_id: 'id-2', media_id: 2, cluster_id: 'cluster-a' }),
      member({ identity_id: 'id-3', media_id: 3, cluster_id: 'cluster-b' }),
    ],
  });

  it('preselects the only eligible face group and excludes singleton anchors', () => {
    renderItem(personSpanningCluster());
    expect(screen.getByText('Not the same person?')).toBeVisible();
    fireEvent.click(screen.getByRole('button', { name: /split group/i }));
    expect(screen.queryByRole('combobox')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Use face from media #3/i })).not.toBeInTheDocument();
    expect(screen.getByText(/Choose a face to keep the label “bob”/)).toBeVisible();
    fireEvent.click(screen.getByRole('button', { name: /Use face from media #2/i }));
    expect(splitMock).toHaveBeenCalledWith('cluster-a', 2, 'id-2');
  });

  it('requires a face group choice and filters anchors to that group', () => {
    const cluster = personSpanningCluster();
    cluster.members.push(
      member({ identity_id: 'id-4', media_id: 4, cluster_id: 'cluster-b' }),
      member({ identity_id: 'id-5', media_id: 5, cluster_id: 'cluster-b' }),
    );
    cluster.identityClusterIds = { ...cluster.identityClusterIds, 'id-4': 'cluster-b', 'id-5': 'cluster-b' };
    cluster.members[0].media_url = 'https://example.test/face-a.jpg';
    renderItem(cluster);
    fireEvent.click(screen.getByRole('button', { name: /split group/i }));
    expect(
      screen.getByRole('radio', { name: 'Face group 1 · 2 faces' }).closest('label')?.querySelector('img'),
    ).toHaveAttribute('src', 'https://example.test/face-a.jpg');
    expect(screen.queryByRole('button', { name: /Use face from media/i })).not.toBeInTheDocument();
    expect(screen.getByText('Choose a face group to pick the face that keeps it')).toBeVisible();
    expect(screen.getByRole('radio', { name: 'Face group 1 · 2 faces' })).not.toBeChecked();
    fireEvent.click(screen.getByRole('radio', { name: 'Face group 2 · 3 faces' }));
    expect(screen.getByRole('radio', { name: 'Face group 2 · 3 faces' })).toBeChecked();
    expect(screen.queryByText('Choose a face group to pick the face that keeps it')).not.toBeInTheDocument();
    expect(screen.getAllByRole('button', { name: /Use face from media/i })).toHaveLength(3);
    expect(screen.queryByRole('button', { name: /Use face from media #1/i })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /Use face from media #3/i }));
    expect(splitMock).toHaveBeenCalledWith('cluster-b', 2, 'id-3');
  });

  it('describes an unlabeled split without promising to keep a label', () => {
    const cluster = personSpanningCluster();
    cluster.label = null;
    renderItem(cluster);
    fireEvent.click(screen.getByRole('button', { name: /split group/i }));
    expect(screen.getByRole('heading', { name: 'Split a face group' })).toBeVisible();
    expect(
      screen.getByText('The chosen face stays in this face group; other faces move to a new face group.'),
    ).toBeVisible();
  });

  it('offers Split when only a secondary face group has two members', () => {
    const cluster = personSpanningCluster();
    cluster.identityClusterIds = { 'id-1': 'cluster-a', 'id-2': 'cluster-b', 'id-3': 'cluster-b' };
    cluster.members[1] = member({ identity_id: 'id-2', media_id: 2, cluster_id: 'cluster-b' });
    renderItem(cluster);

    expect(screen.getByRole('button', { name: /split group/i })).toBeVisible();
  });

  it('withholds Split when all mapped face groups are singletons', () => {
    const cluster = personSpanningCluster();
    cluster.identityClusterIds = { 'id-1': 'cluster-a', 'id-3': 'cluster-b' };
    cluster.members.splice(1, 1);
    renderItem(cluster);

    expect(screen.queryByRole('button', { name: /split group/i })).not.toBeInTheDocument();
  });

  it('withholds Split for a single face', () => {
    renderItem(bobCluster());
    expect(screen.queryByRole('button', { name: /split group/i })).not.toBeInTheDocument();
  });
});

describe('IdentityClusterItem face-group badge', () => {
  afterEach(cleanup);

  it('keeps face-group topology off the daily card and under Not the same person?', () => {
    renderItem({
      ...bobCluster(),
      clusterIds: ['first', 'second'],
      identityClusterIds: { 'id-1': 'first', 'id-2': 'first', 'id-3': 'second' },
      members: [
        member({ identity_id: 'id-1', media_id: 1 }),
        member({ identity_id: 'id-2', media_id: 2, representative_id: 'rep-2' }),
        member({ identity_id: 'id-3', media_id: 3, representative_id: 'rep-3' }),
      ],
    });
    expect(screen.queryByRole('img', { name: /face groups?/ })).not.toBeInTheDocument();
    expect(screen.queryByText(/^\+\d+$/)).not.toBeInTheDocument();
    expect(screen.getByText('Not the same person?')).toBeVisible();
    expect(screen.getByRole('button', { name: /split group/i })).toBeVisible();
  });

  it.each([undefined, [], ['first']])('omits the badge unless multiple groups are supplied', (clusterIds) => {
    renderItem({ ...bobCluster(), clusterIds });
    expect(screen.queryByRole('img', { name: /face groups?/ })).not.toBeInTheDocument();
    expect(screen.queryByText(/^\+\d+$/)).not.toBeInTheDocument();
  });
});

describe('groupIdentitiesByClusters same-face dedup (GPUFLOW-3 R1)', () => {
  it('keeps one row when the same media box overlaps above 0.5 IOU', () => {
    const identities = [
      member({ identity_id: 'id-1', media_id: 10, bbox: { x: 0, y: 0, width: 50, height: 50 } }),
      member({
        identity_id: 'id-2',
        representative_id: 'rep-2',
        media_id: 10,
        bbox: { x: 10, y: 0, width: 50, height: 50 },
      }),
    ];
    const [group] = groupIdentitiesByClusters(identities);
    expect(group.members.map((row) => row.identity_id)).toEqual(['id-1']);
  });

  it('keeps distinct faces on the same media when IOU is not above 0.5', () => {
    const identities = [
      member({ identity_id: 'id-1', media_id: 10, bbox: { x: 0, y: 0, width: 40, height: 40 } }),
      member({
        identity_id: 'id-2',
        representative_id: 'rep-2',
        media_id: 10,
        bbox: { x: 60, y: 60, width: 40, height: 40 },
      }),
    ];
    const [group] = groupIdentitiesByClusters(identities);
    expect(group.members.map((row) => row.identity_id)).toEqual(['id-1', 'id-2']);
  });

  it('abstains when boxes are 1px stubs without a usable face region', () => {
    const identities = [
      member({ identity_id: 'id-1', media_id: 10, bbox: { x: 0, y: 0, width: 1, height: 1 } }),
      member({
        identity_id: 'id-2',
        representative_id: 'rep-2',
        media_id: 10,
        bbox: { x: 0, y: 0, width: 1, height: 1 },
      }),
    ];
    const [group] = groupIdentitiesByClusters(identities);
    expect(group.members.map((row) => row.identity_id)).toEqual(['id-1', 'id-2']);
  });

  it('does not merge different people by similarity (GRPH-18)', () => {
    const identities = [
      member({
        identity_id: 'id-1',
        person_id: '1',
        media_id: 10,
        similarity: 1,
        bbox: { x: 0, y: 0, width: 50, height: 50 },
      }),
      member({
        identity_id: 'id-2',
        representative_id: 'rep-2',
        person_id: '2',
        media_id: 11,
        similarity: 1,
        bbox: { x: 0, y: 0, width: 50, height: 50 },
      }),
    ];
    const groups = groupIdentitiesByClusters(identities);
    expect(groups.map((group) => group.key)).toEqual(['person:1', 'person:2']);
    expect(groups.map((group) => group.members.map((row) => row.identity_id))).toEqual([['id-1'], ['id-2']]);
  });
});

const evidenceView = (groups = 2, loaded = groups, skipped = 0): RepeatedRegionEvidenceView => {
  const observations = Array.from({ length: groups }, (_, i) => ({
    identityId: `face-${String.fromCharCode(97 + i)}`, mediaId: 10,
    bbox: { x: 12, y: 20, width: 40, height: 48 }, groupKey: `person:${i + 1}`,
    personId: String(i + 1), clusterId: `c-${i + 1}`,
  }));
  return { groupKey: 'person:1', groupLabels: new Map(),
    pool: { loadedObservationCount: loaded, eligibleObservationCount: groups,
      abstainedIdentityIds: Array.from({ length: skipped }, (_, i) => `skip-${i}`) },
    regions: [{ regionKey: '10|12|20|40|48', mediaId: 10,
      bbox: observations[0].bbox, groupKeys: observations.map((o) => o.groupKey), observations }],
  };
};
const renderEvidence = (view = evidenceView(), cluster = bobCluster()) => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>
    <IdentityClusterItem cluster={cluster} canLabel canMutate repeatedRegionEvidence={view} />
  </QueryClientProvider>);
};

describe('UXREC-1 repeated region disclosure', () => {
  let originalLang: string | null;
  let restoreNumberFormat: (() => void) | undefined;
  beforeEach(() => {
    originalLang = document.documentElement.getAttribute('lang');
    document.documentElement.lang = 'en-US';
    vi.mocked(i18n._n).mockImplementation((one, many, n) => i18n.sprintf('%s', n === 1 ? one : many));
    vi.mocked(i18n._n).mockClear();
  });
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    restoreNumberFormat?.();
    restoreNumberFormat = undefined;
    if (originalLang === null) document.documentElement.removeAttribute('lang');
    else document.documentElement.lang = originalLang;
  });
  it('is collapsed, discloses exact evidence in place, and keeps naming primary', () => {
    renderEvidence();
    const summary = screen.getByText('Same photo region is also listed in 1 other group');
    const details = summary.closest('details');
    expect(details).not.toHaveAttribute('open');
    const label = screen.getByRole('button', { name: 'bob' });
    expect(label.compareDocumentPosition(summary) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    // user-event's installed focus selector omits summary. Verify native focus
    // without adding a synthetic tabindex; a browser keyboard walk is still required.
    summary.focus();
    expect(summary).toHaveFocus();
    fireEvent.click(summary);
    expect(details).toHaveAttribute('open');
    if (!(details instanceof HTMLDetailsElement)) throw new Error('native details missing');
    const body = within(details);
    expect(body.getByText('Photo 10 — box x 12, y 20, width 40, height 48')).toBeVisible();
    const items = body.getAllByRole('listitem');
    expect(items.some((li) => li.textContent === 'Person 1 — face record face-a')).toBe(true);
    expect(items.some((li) => li.textContent === 'Person 2 — face record face-b')).toBe(true);
    expect(body.getByText('Matching uses exact box coordinates in the face records loaded for this photo. It does not show that these faces are the same person, and nothing is merged or moved.')).toBeVisible();
    expect(body.getByText('Checked 2 of 2 loaded face records with usable box coordinates.')).toBeVisible();
    expect(details?.querySelector('img, button, a')).toBeNull();
    expect(summary.querySelector('code')).toBeNull();
    fireEvent.click(summary);
    expect(details).not.toHaveAttribute('open');
    fireEvent.click(label);
    expect(screen.getByPlaceholderText(/enter a name/i)).toHaveValue('bob');
    expect(screen.queryByTestId('acx-repeated-region-evidence')).not.toBeInTheDocument();
  });
  it('uses human labels only alongside inspectable canonical references', () => {
    const view = evidenceView();
    view.groupLabels = new Map([['person:1', 'bob']]);
    renderEvidence(view);
    fireEvent.click(screen.getByText(/Same photo region/));
    expect(screen.getAllByRole('listitem').some((li) => li.textContent === 'bob (person 1) — face record face-a')).toBe(true);
    expect(screen.getByTestId('acx-repeated-region-evidence').querySelectorAll('code')).toHaveLength(4);
  });
  it('renders outside the processing guard and adds nothing when no evidence is supplied', () => {
    const result = renderItem();
    expect(screen.queryByTestId('acx-repeated-region-evidence')).not.toBeInTheDocument();
    result.unmount();
    renderEvidence(evidenceView(), { ...bobCluster(), clusteringPending: true });
    expect(screen.getByText(/Same photo region/)).toBeInTheDocument();
  });
  it.each(['en-US', 'ar-EG'])('formats human counts with explicit %s but leaves coordinates and IDs raw', (lang) => {
    expect(Intl.NumberFormat.supportedLocalesOf([lang])).toContain(lang);
    const format = new Intl.NumberFormat(lang, { maximumFractionDigits: 0 });
    if (lang === 'ar-EG') expect(format.format(2)).not.toBe('2');
    document.documentElement.lang = lang;
    renderEvidence(evidenceView(3, 1234, 2));
    expect(screen.getByText(`Same photo region is also listed in ${format.format(2)} other groups`)).toBeInTheDocument();
    fireEvent.click(screen.getByText(/Same photo region/));
    expect(screen.getByText(`Checked ${format.format(3)} of ${format.format(1234)} loaded face records with usable box coordinates.`)).toBeVisible();
    expect(screen.getByText(`${format.format(2)} face records were skipped because their loaded copies disagree.`)).toBeVisible();
    expect(screen.getByText('Photo 10 — box x 12, y 20, width 40, height 48')).toBeVisible();
    expect(screen.getAllByRole('listitem').some((li) => li.textContent === 'Person 1 — face record face-a')).toBe(true);
  });
  it.each([null, '', '   ', 'en_US', 'not_a_locale'])('uses neutral raw counts for missing/malformed host lang %s', (lang) => {
    vi.spyOn(navigator, 'language', 'get').mockReturnValue('ar-EG');
    if (lang === null) document.documentElement.removeAttribute('lang');
    else document.documentElement.lang = lang;
    const ctor = vi.spyOn(Intl, 'NumberFormat');
    renderEvidence(evidenceView(3, 1234, 2));
    expect(screen.getByText('Same photo region is also listed in 2 other groups')).toBeInTheDocument();
    fireEvent.click(screen.getByText(/Same photo region/));
    expect(screen.getByText('Checked 3 of 1234 loaded face records with usable box coordinates.')).toBeVisible();
    expect(ctor).not.toHaveBeenCalled();
  });
  it('falls back for a valid unsupported tag without constructing a formatter', () => {
    document.documentElement.lang = 'zz-ZZ';
    const supported = vi.spyOn(Intl.NumberFormat, 'supportedLocalesOf').mockReturnValue([]);
    const ctor = vi.spyOn(Intl, 'NumberFormat');
    renderEvidence(evidenceView(3, 1234));
    expect(screen.getByText('Same photo region is also listed in 2 other groups')).toBeInTheDocument();
    expect(supported).toHaveBeenCalledWith(['zz-ZZ'], { localeMatcher: 'lookup' });
    expect(ctor).not.toHaveBeenCalled();
  });
  it.each(['canonical', 'support', 'constructor', 'format', 'missing Intl', 'missing NumberFormat', 'missing support', 'missing canonical'])('falls back without throwing when Intl %s is unavailable', (failure) => {
    const NativeNumberFormat = Intl.NumberFormat;
    if (failure === 'canonical') vi.spyOn(Intl, 'getCanonicalLocales').mockImplementation(() => { throw new Error('unavailable'); });
    if (failure === 'support') vi.spyOn(Intl.NumberFormat, 'supportedLocalesOf').mockImplementation(() => { throw new Error('unavailable'); });
    if (failure === 'constructor') {
      const ctor = vi.spyOn(Intl, 'NumberFormat').mockImplementation(function () { throw new Error('unavailable'); });
      Object.defineProperty(ctor, 'supportedLocalesOf', { value: NativeNumberFormat.supportedLocalesOf.bind(NativeNumberFormat) });
    }
    if (failure === 'format') {
      const prototype = NativeNumberFormat.prototype;
      const descriptor = Object.getOwnPropertyDescriptor(prototype, 'format');
      if (!descriptor) throw new Error('native format getter missing');
      Object.defineProperty(prototype, 'format', { configurable: true, get: () => () => { throw new Error('unavailable'); } });
      restoreNumberFormat = () => Object.defineProperty(prototype, 'format', descriptor);
    }
    if (failure === 'missing Intl') vi.stubGlobal('Intl', undefined);
    if (failure === 'missing NumberFormat') vi.stubGlobal('Intl', { getCanonicalLocales: Intl.getCanonicalLocales, NumberFormat: undefined });
    if (failure === 'missing support') vi.stubGlobal('Intl', { getCanonicalLocales: Intl.getCanonicalLocales, NumberFormat: {} });
    if (failure === 'missing canonical') vi.stubGlobal('Intl', { NumberFormat: NativeNumberFormat });
    renderEvidence(evidenceView(3, 1234));
    expect(screen.getByText('Same photo region is also listed in 2 other groups')).toBeInTheDocument();
    fireEvent.click(screen.getByText(/Same photo region/));
    expect(screen.getByText('Checked 3 of 1234 loaded face records with usable box coordinates.')).toBeVisible();
  });
  it.each([1, 2, 22, 5, 11])('passes raw plural selectors %i to a multi-form catalog, including loaded rather than eligible', (n) => {
    const catalog = (one: string, many: string, count: number) => {
      const slot = count === 1 ? 'one' : [2, 22].includes(count) ? 'few' : 'many';
      return i18n.sprintf('%s', `${slot}: ${count === 1 ? one : many}`);
    };
    vi.mocked(i18n._n).mockImplementation(catalog);
    const view = evidenceView(n + 1, n + 3, n);
    renderEvidence(view);
    expect(screen.getByText(`${n === 1 ? 'one' : [2, 22].includes(n) ? 'few' : 'many'}: Same photo region is also listed in ${n} other group${n === 1 ? '' : 's'}`)).toBeInTheDocument();
    const calls = vi.mocked(i18n._n).mock.calls;
    const summary = calls.find(([one]) => one.startsWith('Same photo region'));
    const pool = calls.find(([one]) => one.startsWith('Checked'));
    const skipped = calls.find(([one]) => one.startsWith('%s face record was'));
    expect(summary).toEqual(['Same photo region is also listed in %s other group', 'Same photo region is also listed in %s other groups', n, 'alt-context']);
    expect(pool).toEqual(['Checked %1$s of %2$s loaded face record with usable box coordinates.', 'Checked %1$s of %2$s loaded face records with usable box coordinates.', n + 3, 'alt-context']);
    expect(skipped).toEqual(['%s face record was skipped because its loaded copies disagree.', '%s face records were skipped because their loaded copies disagree.', n, 'alt-context']);
    if (!pool) throw new Error('actual pool catalog call absent');
    // Exercise the captured real singular catalog message without fabricating a one-record region.
    expect(catalog(pool[0], pool[1], 1)).toBe(`one: ${pool[0]}`);
    for (const count of [1, 2, 22, 5, 11]) {
      expect(catalog(pool[0], pool[1], count)).toMatch(new RegExp(`^${count === 1 ? 'one' : [2, 22].includes(count) ? 'few' : 'many'}:`));
    }
  });
  it.each([2, 22, 5, 11])('uses loaded pool N=%i independently of eligible M in a Polish catalog', (loaded) => {
    const slot = [2, 22].includes(loaded) ? 'few' : 'many';
    vi.mocked(i18n._n).mockImplementation((one, many, n) =>
      i18n.sprintf('%s', `${n === 1 ? 'one' : [2, 22].includes(n) ? 'few' : 'many'}: ${n === 1 ? one : many}`));
    renderEvidence(evidenceView(2, loaded));
    fireEvent.click(screen.getByText(/Same photo region/));
    expect(screen.getByText(`${slot}: Checked 2 of ${loaded} loaded face records with usable box coordinates.`)).toBeVisible();
    expect(vi.mocked(i18n._n).mock.calls.find(([one]) => one.startsWith('Checked'))?.slice(2))
      .toEqual([loaded, 'alt-context']);
  });
  it('uses canonical trimmed host lang explicitly and survives a failed host-locale read', () => {
    document.documentElement.lang = ' ar-eg ';
    const original = Intl.NumberFormat;
    const calls = vi.fn(function (tag: string, options?: Intl.NumberFormatOptions) { return new original(tag, options); });
    Object.defineProperty(calls, 'supportedLocalesOf', { value: original.supportedLocalesOf.bind(original) });
    vi.stubGlobal('Intl', { getCanonicalLocales: Intl.getCanonicalLocales, NumberFormat: calls });
    const result = renderEvidence(evidenceView(3, 1234));
    expect(screen.getByText(`Same photo region is also listed in ${new original('ar-EG').format(2)} other groups`)).toBeInTheDocument();
    expect(calls).toHaveBeenCalledWith('ar-EG', { style: 'decimal', maximumFractionDigits: 0 });
    expect(calls.mock.calls.every(([tag]) => tag === 'ar-EG')).toBe(true);
    result.unmount();
    vi.unstubAllGlobals();
    vi.spyOn(document.documentElement, 'lang', 'get').mockImplementation(() => { throw new Error('read failed'); });
    renderEvidence(evidenceView(3, 1234));
    expect(screen.getByText('Same photo region is also listed in 2 other groups')).toBeInTheDocument();
  });

});
