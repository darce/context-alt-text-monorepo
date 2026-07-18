import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import React from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
  fetchClusterMembers,
  fetchPendingMergeSuggestions,
  fetchPendingNameSuggestions,
  fetchPendingSuggestions,
  fetchTopUnlabeledClusters,
} from '../../../api/recognition';
import { DATA_SOURCE } from '../../../api/recognition/types';
import { resetConfigCache } from '../../../api/config';
import { commitClusterToRosterEntry, listRosterEntries } from '../../../api/rosterApi';
import { HTTPError } from '../../../utils/http';
import type { DescribeRunProgress } from '../../../hooks/useDescribeRunProgress';
import { MergeSurvivorProvider } from '../identity-clusters/MergeSurvivorContext';
import { ReviewQueue } from '../identity-clusters';
import { REVIEW_QUEUE_DRAIN_MESSAGE } from '../identity-clusters/reviewQueueDriver';
import { MediaAnalyzeCta } from '../MediaAnalyzeCta';
import { BulkDescribeCta } from '../MediaSelection';
import { selectMediaFooterCtaState } from '../mediaFooterCtaState';

/**
 * E21-5 Slice 8 — DOM proof of the §7 single-accent-primary invariant (BR-72).
 *
 * The invariant: exactly ONE element carrying `data-acx-accent-primary` (and the
 * accent chrome) is present in the rendered review viewport in EVERY screen state.
 * This test MOUNTS the real reconciled viewport — the real ReviewQueue (which
 * places the card marker and reports card-primary presence) + the real footer CTAs
 * (MediaAnalyzeCta / BulkDescribeCta) — wired by the real `selectMediaFooterCtaState`
 * reconciliation, then counts `[data-acx-accent-primary]` in the DOM. It is NOT
 * arithmetic over the selector's own output: a second accent, or a dropped one, is
 * caught (see the "guard" describe below, which deliberately mis-wires the harness).
 * `--acx-color-accent-soft` selection/focus tints carry no marker and are exempt.
 */

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
  _n: (single: string, plural: string, count: number) => (count === 1 ? single : plural),
  sprintf: (format: string, ...args: (string | number)[]) => {
    let i = 0;
    return format.replace(/%(\d+)\$[sd]|%[sd]/g, () => String(args[i++]));
  },
}));

vi.mock('../../../api/recognition', async () => {
  const actual = await vi.importActual<typeof import('../../../api/recognition')>('../../../api/recognition');
  return {
    ...actual,
    fetchPendingSuggestions: vi.fn(),
    fetchPendingMergeSuggestions: vi.fn(),
    fetchPendingNameSuggestions: vi.fn(),
    fetchTopUnlabeledClusters: vi.fn(),
    fetchClusterMembers: vi.fn(),
  };
});

vi.mock('../../../api/rosterApi', () => ({
  commitClusterToRosterEntry: vi.fn().mockResolvedValue(undefined),
  listRosterEntries: vi.fn().mockResolvedValue([]),
}));

// Footer CTA leaf hooks (MediaAnalyzeCta). ReviewQueue's tree does NOT use these,
// so mocking them cannot perturb the queue (ReviewQueue.test mounts the real queue
// with only QueryClient + MergeSurvivor providers).
vi.mock('../JobPipelineContext', () => ({
  useJobPipeline: () => ({ scanRun: { isScanning: false, progress: null }, scan: vi.fn() }),
}));
vi.mock('../WorkbenchMediaContext', () => ({
  useWorkbenchMediaContext: () => ({ selection: { selectedMedia: [] } }),
}));
vi.mock('../../../hooks/useSyncOffline', () => ({
  useSyncOffline: () => false,
}));
vi.mock('../Panels', () => ({
  isClusteringActive: () => false,
}));

vi.mock('../BulkDescribeReviewLink', () => ({
  BulkDescribeReviewLink: () => null,
}));

const idleProgress = {
  status: null,
  run: null,
  isTerminal: false,
  isError: false,
  isPolling: false,
  etaSeconds: null,
  progressFraction: 0,
  retry: vi.fn(),
} as unknown as DescribeRunProgress;

const describeProps = {
  selectedCount: 2,
  isSubmitting: false,
  isCancelling: false,
  isRunning: false,
  runId: null as string | null,
  progress: idleProgress,
  isPanelVisible: false,
  errorMessage: null as string | null,
  onSubmit: vi.fn(),
  onCancel: vi.fn(),
  onDismiss: vi.fn(),
  onRetryPolling: vi.fn(),
};

const assignmentSuggestion = {
  id: 'sugg-1',
  identity_id: 'identity-1',
  suggested_cluster_id: 'cluster-1',
  representative_similarity: 0.9,
  avg_member_similarity: 0.85,
  cluster_label: 'Alex',
  cluster_identity_count: 3,
};

/**
 * Faithful copy of ScanTabContent's reconciliation, minus panels/collapse: the
 * SAME `cardPrimaryPresent` the queue reports drives footer demotion via the real
 * `selectMediaFooterCtaState`. `forceReviewActive` exists only for the guard tests
 * that deliberately break the reconciliation to prove the DOM count discriminates.
 */
const ReconciledViewport = ({
  describeRunning = false,
  initialKind = 'all',
  forceReviewActive,
}: {
  describeRunning?: boolean;
  initialKind?: 'all' | 'assignment' | 'merge';
  forceReviewActive?: boolean;
}): React.JSX.Element => {
  const [cardPrimaryPresent, setCardPrimaryPresent] = React.useState(false);
  const [index, setIndex] = React.useState(0);
  const [kind, setKind] = React.useState<'all' | 'assignment' | 'merge'>(initialKind);
  const [selectedIds, setSelectedIds] = React.useState<Set<string>>(() => new Set());
  const reviewActive = forceReviewActive ?? cardPrimaryPresent;
  const footerCta = selectMediaFooterCtaState({ reviewActive, describeRunning });

  return (
    <div data-testid="reconciled-viewport">
      <ReviewQueue
        index={index}
        onIndexChange={setIndex}
        kind={kind}
        onKindChange={setKind}
        band="all"
        onBandChange={vi.fn()}
        selectedIds={selectedIds}
        onSelectedIdsChange={setSelectedIds}
        onCardPrimaryPresenceChange={setCardPrimaryPresent}
      />
      <MediaAnalyzeCta accentPrimary={footerCta.accentOwner === 'analyze'} />
      <BulkDescribeCta {...describeProps} accentPrimary={footerCta.accentOwner === 'describe'} />
    </div>
  );
};

const renderViewport = (props: Parameters<typeof ReconciledViewport>[0] = {}) => {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false, retryDelay: 0 } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MergeSurvivorProvider>
        <ReconciledViewport {...props} />
      </MergeSurvivorProvider>
    </QueryClientProvider>,
  );
};

const markerCount = (container: HTMLElement): number =>
  container.querySelectorAll('[data-acx-accent-primary]').length;

const emptyQueues = (): void => {
  vi.mocked(fetchPendingSuggestions).mockResolvedValue({ suggestions: [], limit: 10, offset: 0 });
};

const oneAssignment = (): void => {
  vi.mocked(fetchPendingSuggestions).mockResolvedValue({
    suggestions: [assignmentSuggestion],
    limit: 10,
    offset: 0,
  });
};

/** A promise that never settles — used to hold a query in its loading branch. */
const pending = (): Promise<never> => new Promise<never>(() => undefined);

describe('§7 single-accent-primary DOM invariant (Slice 8 / BR-72)', () => {
  beforeEach(() => {
    window.AltContextAdmin = {
      nonce: 'test-nonce',
      endpoints: {
        recognitionSuggestions: 'http://localhost/recognition/suggestions',
        recognitionMergeSuggestions: 'http://localhost/recognition/suggestions/merge',
        recognitionNameSuggestions: 'http://localhost/recognition/suggestions/name',
        recognitionClusters: 'http://localhost/recognition/clusters',
      },
      tenant_id: 'test-tenant-id',
    };
    vi.mocked(fetchPendingMergeSuggestions).mockResolvedValue({ suggestions: [], limit: 10, offset: 0 });
    vi.mocked(fetchPendingNameSuggestions).mockResolvedValue({ suggestions: [], limit: 25, offset: 0 });
    vi.mocked(fetchTopUnlabeledClusters).mockResolvedValue({
      clusters: [],
      limit: 20,
      total: 0,
      truncated: false,
      singleton_count: 0,
      data_source: DATA_SOURCE.LOCAL_PROJECTION,
    });
    vi.mocked(fetchClusterMembers).mockResolvedValue({ members: [], limit: 1, total: 0, truncated: false });
    vi.mocked(listRosterEntries).mockResolvedValue([]);
    vi.mocked(commitClusterToRosterEntry).mockResolvedValue(undefined);
    resetConfigCache();
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it('select (no findings): the footer Analyze button is the single accent primary', async () => {
    emptyQueues();
    const { container } = renderViewport();

    await screen.findByText(REVIEW_QUEUE_DRAIN_MESSAGE);

    expect(markerCount(container)).toBe(1);
    const marked = container.querySelector('[data-acx-accent-primary]');
    expect(marked).toBe(screen.getByRole('button', { name: 'Analyze selected media' }));
  });

  it('describe-in-flight: the describe submit button is the single accent primary', async () => {
    emptyQueues();
    const { container } = renderViewport({ describeRunning: true });

    await screen.findByText(REVIEW_QUEUE_DRAIN_MESSAGE);

    expect(markerCount(container)).toBe(1);
    const marked = container.querySelector('[data-acx-accent-primary]');
    expect(marked).toBe(screen.getByRole('button', { name: 'Describe selected' }));
  });

  it('review-active-with-a-card: the card accept is the single accent primary, footer demoted', async () => {
    oneAssignment();
    const { container } = renderViewport();

    const accept = await screen.findByRole('button', { name: 'Yes' });
    // The card primary is present → footer demoted → the ONE marker is on the card accept.
    await waitFor(() => expect(markerCount(container)).toBe(1));
    const marked = container.querySelector('[data-acx-accent-primary]');
    expect(marked).toBe(accept);
    expect(accept.className).toContain('acx-accent-primary-action');
    // Footer CTAs carry no marker while the card owns the accent.
    expect(screen.getByRole('button', { name: 'Analyze selected media' })).not.toHaveAttribute(
      'data-acx-accent-primary',
    );
    expect(screen.getByRole('button', { name: 'Describe selected' })).not.toHaveAttribute(
      'data-acx-accent-primary',
    );
  });

  it('chip-empty (findings exist, filter yields no card): footer Analyze is the single accent primary', async () => {
    // Assignment data present, but the MERGE filter yields an empty card view → no
    // card primary on screen → footer keeps its Analyze primary (BR-75).
    oneAssignment();
    const { container } = renderViewport({ initialKind: 'merge' });

    await waitFor(() => expect(container.querySelector('.acx-review-queue__empty')).toBeTruthy());

    expect(markerCount(container)).toBe(1);
    expect(container.querySelector('[data-acx-accent-primary]')).toBe(
      screen.getByRole('button', { name: 'Analyze selected media' }),
    );
  });

  it('loading: footer Analyze is the single accent primary while the queue is still loading', async () => {
    // All source queries stay pending → the queue renders its loading branch, no card.
    vi.mocked(fetchPendingSuggestions).mockImplementation(pending);
    vi.mocked(fetchPendingMergeSuggestions).mockImplementation(pending);
    vi.mocked(fetchPendingNameSuggestions).mockImplementation(pending);
    vi.mocked(fetchTopUnlabeledClusters).mockImplementation(pending);
    const { container } = renderViewport();

    await waitFor(() => expect(container.querySelector('.acx-review-queue--loading')).toBeTruthy());

    expect(markerCount(container)).toBe(1);
    expect(container.querySelector('[data-acx-accent-primary]')).toBe(
      screen.getByRole('button', { name: 'Analyze selected media' }),
    );
  });

  it('retired-head (open cluster 404s): suppressed card → footer Analyze is the single accent primary', async () => {
    oneAssignment();
    // The head card's cluster existence probe 404s → criterion-4 retirement suppress.
    vi.mocked(fetchClusterMembers).mockRejectedValue(
      new HTTPError({
        status: 404,
        retryAfterSeconds: undefined,
        endpoint: 'http://localhost/recognition/clusters/cluster-1/members',
        bodyPreview: 'cluster_not_found',
        message: 'cluster_not_found',
      }),
    );
    const { container } = renderViewport();

    await waitFor(() =>
      expect(container.querySelector('[data-testid="acx-review-queue-retired-head"]')).toBeTruthy(),
    );

    await waitFor(() => expect(markerCount(container)).toBe(1));
    expect(container.querySelector('[data-acx-accent-primary]')).toBe(
      screen.getByRole('button', { name: 'Analyze selected media' }),
    );
  });
});

/**
 * Guard: the DOM count genuinely discriminates — it is NOT the old tautology. When
 * the reconciliation is deliberately mis-wired, the count is 2 (a second accent
 * appears) or 0 (the accent is dropped), so the `=== 1` assertions above can fail.
 */
describe('§7 single-accent-primary DOM invariant — discrimination guard (BR-72)', () => {
  beforeEach(() => {
    window.AltContextAdmin = {
      nonce: 'test-nonce',
      endpoints: {
        recognitionSuggestions: 'http://localhost/recognition/suggestions',
        recognitionMergeSuggestions: 'http://localhost/recognition/suggestions/merge',
        recognitionNameSuggestions: 'http://localhost/recognition/suggestions/name',
        recognitionClusters: 'http://localhost/recognition/clusters',
      },
      tenant_id: 'test-tenant-id',
    };
    vi.mocked(fetchPendingMergeSuggestions).mockResolvedValue({ suggestions: [], limit: 10, offset: 0 });
    vi.mocked(fetchPendingNameSuggestions).mockResolvedValue({ suggestions: [], limit: 25, offset: 0 });
    vi.mocked(fetchTopUnlabeledClusters).mockResolvedValue({
      clusters: [],
      limit: 20,
      total: 0,
      truncated: false,
      singleton_count: 0,
      data_source: DATA_SOURCE.LOCAL_PROJECTION,
    });
    vi.mocked(fetchClusterMembers).mockResolvedValue({ members: [], limit: 1, total: 0, truncated: false });
    vi.mocked(listRosterEntries).mockResolvedValue([]);
    vi.mocked(commitClusterToRosterEntry).mockResolvedValue(undefined);
    resetConfigCache();
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it('mis-wired footer that ignores card presence → TWO accents (a second accent is detectable)', async () => {
    oneAssignment();
    // forceReviewActive=false while a card renders → footer stays Analyze-primary AND
    // the card is marked → the DOM count is 2, which `=== 1` would reject.
    const { container } = renderViewport({ forceReviewActive: false });

    await screen.findByRole('button', { name: 'Yes' });
    await waitFor(() => expect(markerCount(container)).toBe(2));
  });

  it('mis-wired footer demoted with no card on screen → ZERO accents (a dropped accent is detectable)', async () => {
    vi.mocked(fetchPendingSuggestions).mockResolvedValue({ suggestions: [], limit: 10, offset: 0 });
    // forceReviewActive=true while NO card renders → footer demoted, no card marker →
    // the DOM count is 0, which `=== 1` would reject.
    const { container } = renderViewport({ forceReviewActive: true });

    await screen.findByText(REVIEW_QUEUE_DRAIN_MESSAGE);
    expect(markerCount(container)).toBe(0);
  });
});
