/**
 * Split / remove affordance gates for the identity-cluster list (WBUX6-W3-L6-02, WBUX6-W3-L6-03).
 *
 * `IdentityClusterItem` computes `canSplit={canMutate && Boolean(cluster.clusterId)}` and
 * `canReject={canMutate && cluster.members.length === 1}`. Both gates were previously
 * unfalsifiable: every fixture in the suite carried a non-null `clusterId`, so deleting the
 * `Boolean(cluster.clusterId)` clause killed no test (TEST-15, lexicons/engineering.md:396 —
 * "a passing test that cannot fail certifies nothing").
 *
 * The gate is only observable at the item level. `groupIdentitiesByClusters`
 * (utils.ts:48) keys groups by `identity.cluster_id`, so a group with `clusterId: null`
 * necessarily holds members whose own `cluster_id` is null; `getEditableClusterId` then
 * returns null, `canEdit` is false and `ClusterActions` early-returns before Split is
 * reachable at all. The discriminating state — group `clusterId` null while a member
 * carries a `cluster_id` — is constructible only against the exported
 * `IdentityClusterItem` (index.ts:18), which is why both levels are pinned here: the list
 * case documents the reachable user-facing path, the item cases hold the gate itself.
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { resetConfigCache } from '../../../../api/config';
import * as recognitionApi from '../../../../api/recognition';
import { DATA_SOURCE } from '../../../../api/recognition/types';
import type { DetectedIdentity } from '../../../../api/recognition/types';
import { IdentityClusterItem } from '../IdentityClusterItem';
import { IdentityClusterList } from '../IdentityClusterList';
import type { ClusterGroup } from '../types';
import { unlabeledSuggestionBatchIds } from '../utils';

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
  _n: (single: string, plural: string, count: number) => (count === 1 ? single : plural),
  sprintf: (template: string, ...args: (string | number)[]) => {
    let idx = 0;
    return template.replace(/%(\d+\$)?[sd]/g, () => String(args[idx++] ?? ''));
  },
}));

vi.mock('../useClusterSuggestions', () => ({
  useClusterSuggestions: () => ({
    options: [],
    isLoading: false,
    collisionsByLabel: new Map(),
    findClusterByLabel: vi.fn(),
    atRestTotal: 0,
    atRestTruncated: false,
    isAtRestMode: false,
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
    split: vi.fn(),
    revertMerge: vi.fn(),
    rejectSuggestion: vi.fn(),
    splitGate: { disabled: false, title: undefined, 'aria-disabled': false },
  }),
}));

vi.mock('../useSuggestionReviewMutations', () => ({
  useSuggestionReviewMutations: () => ({
    scheduleAcceptMerge: vi.fn(),
    scheduleRejectMerge: vi.fn(),
    isCardActionsDisabled: () => false,
    isCommitting: false,
    mutations: {
      acceptMerge: { isPending: false },
      rejectMerge: { isPending: false },
    },
  }),
}));

// Spread the real module: an exhaustive factory blanks every export the render path
// picks up later, wiping the file for a reason unrelated to the gate under test.
vi.mock('../../../../api/recognition', async () => {
  const actual = await vi.importActual<typeof import('../../../../api/recognition')>(
    '../../../../api/recognition',
  );
  return {
    ...actual,
    fetchPendingSuggestions: vi.fn(),
    fetchPendingMergeSuggestions: vi.fn(),
    fetchPendingNameSuggestions: vi.fn(),
    fetchTopUnlabeledClusters: vi.fn(),
    fetchIdentitiesSuggestions: vi.fn(),
  };
});

const CLUSTER_ID = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee';
const SPLIT_LABEL = 'Split group';
const REMOVE_LABEL = 'Remove from group';

const identity = (overrides: Partial<DetectedIdentity> = {}): DetectedIdentity => ({
  identity_id: 'id-1',
  representative_id: 'rep-1',
  media_id: 1,
  cluster_id: CLUSTER_ID,
  cluster_label: 'Bob',
  is_auto_label: false,
  is_pinned: false,
  bbox: { x: 0, y: 0, width: 1, height: 1 },
  confidence: 1,
  similarity: 1,
  detected_at: '',
  ...overrides,
});

const clusterGroup = (overrides: Partial<ClusterGroup> = {}): ClusterGroup => ({
  key: CLUSTER_ID,
  clusterId: CLUSTER_ID,
  label: 'Bob',
  isAutoLabel: false,
  clusteringPending: false,
  members: [identity()],
  ...overrides,
});

const renderItem = (cluster: ClusterGroup, canMutate = true) => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <IdentityClusterItem cluster={cluster} canLabel canMutate={canMutate} />
    </QueryClientProvider>,
  );
};

const renderList = (identities: DetectedIdentity[]) => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <IdentityClusterList identities={identities} />
    </QueryClientProvider>,
  );
};

beforeEach(() => {
  vi.clearAllMocks();
  window.AltContextAdmin = {
    nonce: 'test-nonce',
    ajaxUrl: '/wp-admin/admin-ajax.php',
    tenant_id: 'tenant-1',
    endpoints: {
      recognitionClusters: 'http://localhost/recognition/clusters',
      recognitionSuggestions: 'http://localhost/recognition/suggestions',
    },
  };
  resetConfigCache();
  vi.mocked(recognitionApi.fetchPendingSuggestions).mockResolvedValue({
    suggestions: [],
    limit: 25,
    offset: 0,
    data_source: DATA_SOURCE.LOCAL_PROJECTION,
  });
  vi.mocked(recognitionApi.fetchPendingNameSuggestions).mockResolvedValue({
    suggestions: [],
    limit: 25,
    offset: 0,
  });
  vi.mocked(recognitionApi.fetchPendingMergeSuggestions).mockResolvedValue({
    suggestions: [],
    limit: 50,
    offset: 0,
  });
  vi.mocked(recognitionApi.fetchTopUnlabeledClusters).mockResolvedValue({
    clusters: [],
    limit: 20,
    total: 0,
    truncated: false,
    singleton_count: 0,
    data_source: DATA_SOURCE.LOCAL_PROJECTION,
  });
  vi.mocked(recognitionApi.fetchIdentitiesSuggestions).mockResolvedValue({ matches: {} });
});

afterEach(() => {
  cleanup();
});

describe('IdentityClusterList split affordance (WBUX6-W3-L6-03)', () => {
  it('renders one chip for a person spanning two clusters', async () => {
    renderList([
      identity({ person_id: '7' }),
      identity({ identity_id: 'id-2', person_id: '7', cluster_id: 'another-cluster' }),
    ]);

    await waitFor(() => {
      expect(screen.getAllByRole('button', { name: 'Edit label' })).toHaveLength(1);
    });
  });

  it('offers Split for a clustered group (positive control)', async () => {
    renderList([identity(), identity({ identity_id: 'id-2' })]);

    await waitFor(() => {
      expect(screen.getByRole('button', { name: SPLIT_LABEL })).toBeInTheDocument();
    });
  });

  it('offers Find similar / Name for an identity with no cluster (no Split)', async () => {
    renderList([identity({ cluster_id: null, cluster_label: null })]);

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: 'Not yet grouped (1)' })).toBeInTheDocument();
    });
    expect(screen.queryByRole('button', { name: SPLIT_LABEL })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Unnamed person' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Find similar / Name' })).toBeInTheDocument();
  });
});

describe('IdentityClusterList ungrouped residue (GPUFLOW-2 C5)', () => {
  const watsonFace = (identityId: string, mediaId: number): DetectedIdentity =>
    identity({
      identity_id: identityId,
      representative_id: `rep-${identityId}`,
      media_id: mediaId,
      cluster_id: null,
      cluster_label: null,
      person_id: null,
      media_url: `https://example.test/watson/${identityId}.jpg`,
    });

  it('renders one Not yet grouped section for Watson faces, never N Unnamed person cards', async () => {
    // Watson ×3 residue: two faces share media 10 so a visual dedupe would drop one.
    renderList([
      identity({
        identity_id: 'perry-1',
        cluster_label: 'Katy Perry',
        person_id: 'perry',
        media_url: 'https://example.test/perry.jpg',
      }),
      watsonFace('watson-1', 10),
      watsonFace('watson-2', 10),
      watsonFace('watson-3', 11),
    ]);

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: 'Not yet grouped (3)' })).toBeInTheDocument();
    });

    expect(screen.getAllByRole('heading', { name: /Not yet grouped/ })).toHaveLength(1);
    expect(screen.queryByText('Unnamed person')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Katy Perry' })).toBeInTheDocument();

    const residue = screen.getByRole('region', { name: 'Not yet grouped (3)' });
    expect(within(residue).getAllByRole('listitem')).toHaveLength(3);
    expect(within(residue).getAllByRole('button', { name: 'Find similar / Name' })).toHaveLength(3);
  });

  it('issues one suggestions batch for residue faces and renders an inline prompt per match', async () => {
    vi.mocked(recognitionApi.fetchIdentitiesSuggestions).mockResolvedValue({
      matches: {
        'watson-1': [{ cluster_id: 'c-1', label: 'Emma Watson', similarity: 0.9, identity_count: 2 }],
      },
    });

    renderList([watsonFace('watson-1', 10), watsonFace('watson-2', 11)]);

    await waitFor(() => {
      expect(screen.getByText('Emma Watson')).toBeInTheDocument();
    });
    expect(recognitionApi.fetchIdentitiesSuggestions).toHaveBeenCalledTimes(1);
    expect(recognitionApi.fetchIdentitiesSuggestions).toHaveBeenCalledWith(['watson-1', 'watson-2'], 5);
    expect(screen.getAllByRole('button', { name: 'Yes' })).toHaveLength(1);
  });

  it('keeps unlabeled grouped anchors and residue members in the same batch id list', () => {
    const unlabeledClustered = identity({
      identity_id: 'clustered-unlabeled',
      cluster_id: CLUSTER_ID,
      cluster_label: null,
    });
    const residue = [
      watsonFace('watson-1', 10),
      watsonFace('watson-2', 11),
    ];
    const groups = [
      clusterGroup({
        key: `cluster:${CLUSTER_ID}`,
        clusterId: CLUSTER_ID,
        label: null,
        members: [unlabeledClustered],
      }),
      clusterGroup({
        key: 'ungrouped',
        clusterId: null,
        label: null,
        members: residue,
      }),
    ];

    expect(unlabeledSuggestionBatchIds(groups)).toEqual([
      'clustered-unlabeled',
      'watson-1',
      'watson-2',
    ]);
  });
});

describe('IdentityClusterItem split gate (WBUX6-W3-L6-03)', () => {
  it('withholds Split when the group has a null clusterId even though a member is clustered', () => {
    // Discriminating fixture: getEditableClusterId falls back to the member's cluster_id, so
    // canEdit is true and ClusterActions renders its full branch. Only the
    // Boolean(cluster.clusterId) clause can suppress Split here. Dropping that clause
    // makes this assertion fail with "Split group" found in the document.
    renderItem(
      clusterGroup({
        key: 'no-cluster-id',
        clusterId: null,
        members: [identity(), identity({ identity_id: 'id-2' })],
      }),
    );

    expect(screen.getByRole('button', { name: 'Edit label' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: SPLIT_LABEL })).not.toBeInTheDocument();
  });

  it('offers Split when the group carries a clusterId', () => {
    renderItem(clusterGroup({ members: [identity(), identity({ identity_id: 'id-2' })] }));

    expect(screen.getByRole('button', { name: SPLIT_LABEL })).toBeInTheDocument();
  });

  it('withholds Split in label-only mode', () => {
    renderItem(clusterGroup({ members: [identity(), identity({ identity_id: 'id-2' })] }), false);

    expect(screen.getByRole('button', { name: 'Edit label' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: SPLIT_LABEL })).not.toBeInTheDocument();
  });
});

describe('IdentityClusterItem remove gate (WBUX6-W3-L6-02)', () => {
  it('offers Remove for a one-member group', () => {
    renderItem(clusterGroup());

    expect(screen.getByRole('button', { name: REMOVE_LABEL })).toBeInTheDocument();
  });

  it('withholds Remove for a multi-member group', () => {
    renderItem(clusterGroup({ members: [identity(), identity({ identity_id: 'id-2' })] }));

    expect(screen.queryByRole('button', { name: REMOVE_LABEL })).not.toBeInTheDocument();
  });

  it('withholds Remove in label-only mode', () => {
    renderItem(clusterGroup(), false);

    expect(screen.getByRole('button', { name: 'Edit label' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: REMOVE_LABEL })).not.toBeInTheDocument();
  });
});
