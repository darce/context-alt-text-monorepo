import type { ClusterSuggestion, PendingSuggestion } from '../../../../api/recognition';

import { PROJECTION_TOP_K, SUGGESTION_RESOLUTION } from '../suggestionProjection';

/**
 * Stable named fixture surface for UXP-3 matrix tests and epic E21-5.
 * Each case states expected outcomes for identity-keyed and review legs where they diverge.
 */

export const buildClusterMatch = (
  overrides: Partial<ClusterSuggestion> & Pick<ClusterSuggestion, 'cluster_id' | 'label' | 'similarity'>,
): ClusterSuggestion => ({
  identity_count: 4,
  ...overrides,
});

export const buildPendingRow = (
  overrides: Partial<PendingSuggestion> & Pick<PendingSuggestion, 'id' | 'identity_id'>,
): PendingSuggestion => ({
  suggested_cluster_id: 'cluster-1',
  representative_similarity: 0.9,
  cluster_label: 'Alice',
  cluster_identity_count: 3,
  ...overrides,
});

/** Attachment-only preview source — no thumbUrl / mediaUrl, so collectPreviews must consult attachment. */
export const ATTACHMENT_ONLY_URL = 'https://example.test/attachment-only.jpg';

export const attachmentOnlyPendingRow = buildPendingRow({
  id: 'sug-attachment-only',
  identity_id: 'identity-attachment-only',
  identity_attachment_url: ATTACHMENT_ONLY_URL,
});

const MULTI_IDENTITY_ID = 'identity-multi';
const CLUSTER_FIRST_IDENTITY_ID = 'identity-cluster-first';
const ALL_INELIGIBLE_IDENTITY_ID = 'identity-all-ineligible';
const PERSON_N_IDENTITY_ID = 'identity-person-n';
const TIED_IDENTITY_ID = 'identity-tied';
const STALE_IDENTITY_ID = 'identity-stale';

/**
 * 1. Multi-suggestion identity — several eligible rows, distinct similarities.
 * Arrival order is deliberately NOT similarity-desc (0.81, 0.92, 0.7): the identity leg
 * must preserve this server order untouched, so any client re-sort turns the test red,
 * while the review leg must re-order to similarity-desc.
 */
const multiSuggestionIdentityMatches: ClusterSuggestion[] = [
  buildClusterMatch({
    suggestion_id: 'sug-multi-b',
    cluster_id: 'cluster-alicia',
    label: 'Alicia',
    similarity: 0.81,
    identity_count: 5,
  }),
  buildClusterMatch({
    suggestion_id: 'sug-multi-a',
    cluster_id: 'cluster-alice',
    label: 'Alice',
    similarity: 0.92,
    identity_count: 12,
  }),
  buildClusterMatch({
    suggestion_id: 'sug-multi-c',
    cluster_id: 'cluster-alison',
    label: 'Alison',
    similarity: 0.7,
    identity_count: 2,
  }),
];

const multiSuggestionIdentityPending: PendingSuggestion[] = multiSuggestionIdentityMatches.map((match, index) =>
  buildPendingRow({
    id: match.suggestion_id ?? `sug-multi-${index}`,
    identity_id: MULTI_IDENTITY_ID,
    suggested_cluster_id: match.cluster_id,
    cluster_label: match.label,
    representative_similarity: match.similarity,
    cluster_identity_count: match.identity_count,
    created_at: `2026-01-0${index + 1}T12:00:00.000Z`,
  }),
);

/**
 * 2. cluster-*-first-then-human — server rank #1 is auto-label; eligible human sits deeper
 * inside the PROJECTION_TOP_K window (window-depth case).
 */
const clusterFirstThenHumanMatches: ClusterSuggestion[] = [
  buildClusterMatch({
    suggestion_id: 'sug-cf-1',
    cluster_id: 'cluster-auto-1',
    label: 'cluster-auto-1',
    similarity: 0.99,
  }),
  buildClusterMatch({
    suggestion_id: 'sug-cf-2',
    cluster_id: 'cluster-auto-2',
    label: 'cluster-auto-2',
    similarity: 0.95,
  }),
  buildClusterMatch({
    suggestion_id: 'sug-cf-3',
    cluster_id: 'cluster-bob',
    label: 'Bob',
    similarity: 0.88,
    identity_count: 7,
  }),
  buildClusterMatch({
    suggestion_id: 'sug-cf-4',
    cluster_id: 'cluster-bobby',
    label: 'Bobby',
    similarity: 0.6,
  }),
];

/**
 * 3. All-ineligible-window — all PROJECTION_TOP_K rows ineligible (residual: no prompt).
 */
const allIneligibleWindowMatches: ClusterSuggestion[] = [
  ...Array.from({ length: PROJECTION_TOP_K }, (_, i) =>
    buildClusterMatch({
      suggestion_id: `sug-inelig-${i}`,
      cluster_id: `cluster-auto-inelig-${i}`,
      label: i % 2 === 0 ? `cluster-${1000 + i}` : '   ',
      similarity: 0.9 - i * 0.01,
    }),
  ),
  // The plan's named residual: an eligible 6th row beyond the window still yields no prompt.
  buildClusterMatch({
    suggestion_id: 'sug-inelig-human-beyond',
    cluster_id: 'cluster-human-beyond',
    label: 'Human Beyond',
    similarity: 0.5,
  }),
];

/**
 * 4. Labeled-but-unconfirmed "Person N" — ELIGIBLE on identity-keyed surfaces
 * (human-format label, not cluster-prefixed). The D2 residual is a QUEUE-MEMBERSHIP
 * divergence: the server's stricter review SQL excludes this row, so the review leg's
 * input is empty — the row shows inline/dropdown and NOT on the review queue. The client
 * predicate accepting it is defense-in-depth, never a way back onto the queue.
 */
const labeledButUnconfirmedPersonNMatches: ClusterSuggestion[] = [
  buildClusterMatch({
    suggestion_id: 'sug-person-3',
    cluster_id: 'cluster-person-3',
    label: 'Person 3',
    similarity: 0.87,
    identity_count: 1,
  }),
];

/** What the review endpoint actually returns for this identity: nothing. */
const labeledButUnconfirmedPersonNReviewRows: PendingSuggestion[] = [];

/**
 * 5. Tied similarities — identity leg preserves arrival order; review leg uses createdAt desc.
 * Arrival: Carol (older), then Caroline (newer), same similarity.
 */
const tiedSimilarityPending: PendingSuggestion[] = [
  buildPendingRow({
    id: 'sug-tied-older',
    identity_id: TIED_IDENTITY_ID,
    suggested_cluster_id: 'cluster-carol',
    cluster_label: 'Carol',
    representative_similarity: 0.85,
    created_at: '2026-03-01T08:00:00.000Z',
  }),
  buildPendingRow({
    id: 'sug-tied-newer',
    identity_id: TIED_IDENTITY_ID,
    suggested_cluster_id: 'cluster-caroline',
    cluster_label: 'Caroline',
    representative_similarity: 0.85,
    created_at: '2026-03-10T08:00:00.000Z',
  }),
];

const tiedSimilarityMatches: ClusterSuggestion[] = [
  buildClusterMatch({
    suggestion_id: 'sug-tied-older',
    cluster_id: 'cluster-carol',
    label: 'Carol',
    similarity: 0.85,
  }),
  buildClusterMatch({
    suggestion_id: 'sug-tied-newer',
    cluster_id: 'cluster-caroline',
    label: 'Caroline',
    similarity: 0.85,
  }),
];

/**
 * 6. Stale-accepted row — review-only repair affordance; excluded from identity-keyed reads.
 */
const staleAcceptedPending: PendingSuggestion[] = [
  buildPendingRow({
    id: 'sug-stale-accepted',
    identity_id: STALE_IDENTITY_ID,
    suggested_cluster_id: 'cluster-dave',
    cluster_label: 'Dave',
    representative_similarity: 0.91,
    resolution: SUGGESTION_RESOLUTION.ACCEPTED,
    created_at: '2026-04-01T12:00:00.000Z',
    identity_media_url: 'https://example.test/identity.jpg',
    representative_thumb_url: 'https://example.test/rep-thumb.jpg',
    suggested_label: 'David',
    suggested_label_source: 'roster',
    suggested_label_confidence: 0.77,
  }),
  buildPendingRow({
    id: 'sug-stale-sibling-pending',
    identity_id: STALE_IDENTITY_ID,
    suggested_cluster_id: 'cluster-david',
    cluster_label: 'David',
    representative_similarity: 0.8,
    created_at: '2026-04-02T12:00:00.000Z',
  }),
];

/**
 * Exported matrix fixture — stable import surface for unit tests and E21-5.
 */
export const suggestionProjectionMatrix = {
  multiSuggestionIdentity: {
    identityId: MULTI_IDENTITY_ID,
    matches: multiSuggestionIdentityMatches,
    pendingRows: multiSuggestionIdentityPending,
    /** Identity leg: server arrival order preserved verbatim (NOT similarity-desc). */
    expectedIdentitySuggestionIds: ['sug-multi-b', 'sug-multi-a', 'sug-multi-c'],
    expectedIdentityTopSuggestionId: 'sug-multi-b',
    /** Review leg: re-sorted similarity-desc regardless of arrival. */
    expectedReviewSuggestionIdsBySimilarity: ['sug-multi-a', 'sug-multi-b', 'sug-multi-c'],
  },
  clusterFirstThenHuman: {
    identityId: CLUSTER_FIRST_IDENTITY_ID,
    matches: clusterFirstThenHumanMatches,
    /** After filtering auto-labels inside the top-K window, Bob is first eligible. */
    expectedIdentitySuggestionIds: ['sug-cf-3', 'sug-cf-4'],
    expectedIdentityTopSuggestionId: 'sug-cf-3',
  },
  allIneligibleWindow: {
    identityId: ALL_INELIGIBLE_IDENTITY_ID,
    matches: allIneligibleWindowMatches,
    expectedIdentitySuggestionIds: [] as string[],
    expectedIdentityTopSuggestionId: undefined as string | undefined,
  },
  labeledButUnconfirmedPersonN: {
    identityId: PERSON_N_IDENTITY_ID,
    matches: labeledButUnconfirmedPersonNMatches,
    reviewQueueRows: labeledButUnconfirmedPersonNReviewRows,
    /** Human-format "Person N" is eligible on identity-keyed surfaces. */
    expectedIdentitySuggestionIds: ['sug-person-3'],
    expectedIdentityTopSuggestionId: 'sug-person-3',
    /** D2 residual pinned: the server review queue never contains this row. */
    expectedReviewSuggestionIds: [] as string[],
  },
  tiedSimilarities: {
    identityId: TIED_IDENTITY_ID,
    matches: tiedSimilarityMatches,
    pendingRows: tiedSimilarityPending,
    /** Identity leg: arrival order (older Carol first). */
    expectedIdentitySuggestionIds: ['sug-tied-older', 'sug-tied-newer'],
    /** Review leg: same similarity → createdAt desc (newer Caroline first). */
    expectedReviewSuggestionIds: ['sug-tied-newer', 'sug-tied-older'],
  },
  staleAccepted: {
    identityId: STALE_IDENTITY_ID,
    pendingRows: staleAcceptedPending,
    /** Identity leg drops resolution=accepted; only the still-pending sibling remains. */
    expectedIdentitySuggestionIds: ['sug-stale-sibling-pending'],
    /** Review leg keeps accepted row (repair) plus pending sibling, sorted by similarity. */
    expectedReviewSuggestionIds: ['sug-stale-accepted', 'sug-stale-sibling-pending'],
  },
} as const;

export type SuggestionProjectionMatrix = typeof suggestionProjectionMatrix;
