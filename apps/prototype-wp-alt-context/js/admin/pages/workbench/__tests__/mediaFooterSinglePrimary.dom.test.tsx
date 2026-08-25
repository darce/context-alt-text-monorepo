import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
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
import {
  commitClusterToRosterEntry,
  listRosterEntries,
  type RosterClusterCommitResponse,
} from '../../../api/rosterApi';

const rosterCommitFixture = (
  overrides: Partial<RosterClusterCommitResponse> = {},
): RosterClusterCommitResponse => ({
  cluster_id: 'cluster-1',
  person_id: 7,
  person_uuid: 'person-uuid-7',
  person_name: 'Alex',
  updated_at: '2026-01-01T00:00:00Z',
  ...overrides,
});
import { HTTPError } from '../../../utils/http';
import type { DescribeRunProgress } from '../../../hooks/useDescribeRunProgress';
import { MergeSurvivorProvider } from '../identity-clusters/MergeSurvivorContext';
import {
  VIEW_IN_ROSTER_COPY,
} from '../identity-clusters/personCommitCopy';
import { ReviewQueue } from '../identity-clusters';
import { REVIEW_QUEUE_DRAIN_MESSAGE } from '../identity-clusters/reviewQueueDriver';
import { MediaAnalyzeCta } from '../MediaAnalyzeCta';
import { BulkDescribeCta } from '../MediaSelection';
import { ACCENT_PRIMARY_ATTR, FOOTER_ACCENT_OWNER, selectMediaFooterCtaState } from '../mediaFooterCtaState';

/** Single source of truth for the accent-primary marker selector (BR-83 — was a literal). */
const ACCENT_PRIMARY_SELECTOR = `[${ACCENT_PRIMARY_ATTR}]`;

/**
 * E21-5 Slice 8 — DOM proof of the §7 single-accent-primary invariant (BR-72 + the
 * BR-80..83 re-review round).
 *
 * The invariant: exactly ONE element carrying `data-acx-accent-primary` (and the
 * accent chrome) is present in the rendered review viewport. This test MOUNTS the real
 * reconciled viewport — the real ReviewQueue (which places the card/bulk marker and
 * reports whether the queue owns the accent) + the real footer CTAs (MediaAnalyzeCta /
 * BulkDescribeCta) — wired by the real `selectMediaFooterCtaState` reconciliation, then
 * counts `[data-acx-accent-primary]` in the DOM. It is NOT arithmetic over the
 * selector's own output: a second accent, or a dropped one, is caught (see the "guard"
 * describe below, which deliberately mis-wires the harness). The cases below cover the
 * modeled screen states — select, describe-in-flight, review-active, chip-empty,
 * loading, retired-head, person-commit succeeded (BR-81), bulk-tray open (BR-82) and
 * panel-open (BR-83) — a representative set of the §7 matrix, not literally every state.
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
  commitClusterToRosterEntry: vi.fn().mockResolvedValue({
    cluster_id: 'cluster-1',
    person_id: 7,
    person_uuid: 'person-uuid-7',
    person_name: 'Alex',
    updated_at: '2026-01-01T00:00:00Z',
  }),
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
 * Faithful copy of ScanTabContent's reconciliation, minus collapse: the SAME
 * accent-ownership signal the queue reports drives footer demotion via the real
 * `selectMediaFooterCtaState`. BR-83: ScanTabContent's `reviewSurfaceActive` is exactly
 * `cardPrimaryPresent` — modeled here by `reviewActive = cardPrimaryPresent`. `panelOpen`
 * models a label/review panel replacing the queue: a markerless panel with the queue
 * UNMOUNTED, so `cardPrimaryPresent` falls to false (its layout-effect cleanup) and the
 * footer re-owns the accent. `forceReviewActive` exists only for the guard tests that
 * deliberately break the reconciliation to prove the DOM count discriminates.
 */
const ReconciledViewport = ({
  describeRunning = false,
  initialKind = 'all',
  forceReviewActive,
  panelOpen = false,
}: {
  describeRunning?: boolean;
  initialKind?: 'all' | 'assignment' | 'merge';
  forceReviewActive?: boolean;
  panelOpen?: boolean;
}): React.JSX.Element => {
  const [cardPrimaryPresent, setCardPrimaryPresent] = React.useState(false);
  const [index, setIndex] = React.useState(0);
  const [kind, setKind] = React.useState<'all' | 'assignment' | 'merge'>(initialKind);
  const [selectedIds, setSelectedIds] = React.useState<Set<string>>(() => new Set());
  const reviewActive = forceReviewActive ?? cardPrimaryPresent;
  const footerCta = selectMediaFooterCtaState({ reviewActive, describeRunning });

  return (
    <div data-testid="reconciled-viewport">
      {panelOpen ? (
        // A label/review panel: no accent marker, and the queue is unmounted.
        <div data-testid="mock-review-panel" />
      ) : (
        <ReviewQueue
          index={index}
          onClampIndex={setIndex}
          onStepIndex={(delta, length) => {
            setIndex((prev) => {
              if (length <= 0) {
                return 0;
              }
              const clamped = Math.min(Math.max(0, prev), length - 1);
              return Math.min(Math.max(0, clamped + delta), length - 1);
            });
          }}
          kind={kind}
          onKindChange={(next) => {
            setKind(next);
            setIndex(0);
          }}
          band="all"
          onBandChange={vi.fn()}
          onClearFilters={vi.fn()}
          selectedIds={selectedIds}
          onSelectedIdsChange={setSelectedIds}
          onCardPrimaryPresenceChange={setCardPrimaryPresent}
        />
      )}
      <MediaAnalyzeCta accentPrimary={footerCta.accentOwner === FOOTER_ACCENT_OWNER.ANALYZE} />
      {/*
        S6-01: couple the describe CTA's isRunning to the SAME describeRunning signal that
        drives footer accent ownership — the production-reachable config. A describe run in
        flight disables the submit button while it keeps the accent marker; wiring isRunning
        independently (false) modelled an impossible state and never exercised the disabled
        accent submit.
      */}
      <BulkDescribeCta
        {...describeProps}
        isRunning={describeRunning}
        accentPrimary={footerCta.accentOwner === FOOTER_ACCENT_OWNER.DESCRIBE}
      />
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
  container.querySelectorAll(ACCENT_PRIMARY_SELECTOR).length;

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
      ajaxUrl: '/wp-admin/admin-ajax.php',
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
    vi.mocked(commitClusterToRosterEntry).mockResolvedValue(rosterCommitFixture());
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
    const marked = container.querySelector(ACCENT_PRIMARY_SELECTOR);
    expect(marked).toBe(screen.getByRole('button', { name: 'Analyze selected media' }));
  });

  it('describe-in-flight: the disabled describe submit is the single accent primary', async () => {
    emptyQueues();
    const { container } = renderViewport({ describeRunning: true });

    await screen.findByText(REVIEW_QUEUE_DRAIN_MESSAGE);

    expect(markerCount(container)).toBe(1);
    const marked = container.querySelector(ACCENT_PRIMARY_SELECTOR);
    const describeSubmit = screen.getByRole('button', { name: 'Describe selected' });
    expect(marked).toBe(describeSubmit);
    // Real describe-run state: the submit is disabled (isRunning) yet still owns the accent.
    expect(describeSubmit).toBeDisabled();
  });

  it('review-active-with-a-card: the card accept is the single accent primary, footer demoted', async () => {
    oneAssignment();
    const { container } = renderViewport();

    const accept = await screen.findByRole('button', { name: 'Yes' });
    // BR-80: the useLayoutEffect presence report demotes the footer in the SAME frame the
    // card marker mounts, so the count settles at 1 immediately — no 2→1 waitFor masking.
    expect(markerCount(container)).toBe(1);
    const marked = container.querySelector(ACCENT_PRIMARY_SELECTOR);
    expect(marked).toBe(accept);
    expect(accept.className).toContain('acx-accent-primary-action');
    // Footer CTAs carry no marker while the card owns the accent.
    expect(screen.getByRole('button', { name: 'Analyze selected media' })).not.toHaveAttribute(
      ACCENT_PRIMARY_ATTR,
    );
    expect(screen.getByRole('button', { name: 'Describe selected' })).not.toHaveAttribute(
      ACCENT_PRIMARY_ATTR,
    );
  });

  it('chip-empty (findings exist, filter yields no card): footer Analyze is the single accent primary', async () => {
    // Assignment data present, but the MERGE filter yields an empty card view → no
    // card primary on screen → footer keeps its Analyze primary (BR-75).
    oneAssignment();
    const { container } = renderViewport({ initialKind: 'merge' });

    await waitFor(() => expect(container.querySelector('.acx-review-queue__empty')).toBeTruthy());

    expect(markerCount(container)).toBe(1);
    expect(container.querySelector(ACCENT_PRIMARY_SELECTOR)).toBe(
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
    expect(container.querySelector(ACCENT_PRIMARY_SELECTOR)).toBe(
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
    expect(container.querySelector(ACCENT_PRIMARY_SELECTOR)).toBe(
      screen.getByRole('button', { name: 'Analyze selected media' }),
    );
  });

  it('person-commit succeeded on a CLUSTER card (markerless success surface): footer re-owns the single accent primary (BR-81)', async () => {
    // A CLUSTER card is on screen; its person-commit Confirm is the accent primary and
    // is pre-enabled by the suggested label (create path).
    emptyQueues();
    vi.mocked(fetchTopUnlabeledClusters).mockResolvedValue({
      clusters: [
        {
          id: 'cluster-top-1',
          tenant_id: 'test-tenant-id',
          label: null,
          is_labeled: false,
          is_auto_label: true,
          identity_count: 4,
          user_confirmed: false,
          suggested_label: 'Alex',
          suggested_target_cluster_id: null,
          representatives: [{ id: 'rep-1', media_id: 1, is_pinned: false }],
        },
      ],
      limit: 20,
      total: 1,
      truncated: false,
      singleton_count: 0,
      data_source: DATA_SOURCE.LOCAL_PROJECTION,
    });
    const user = userEvent.setup();
    const { container } = renderViewport();

    // Before commit: the card's person-commit Confirm is the single accent primary.
    // previewCommit names the create outcome from the prefilled suggested_label.
    const confirm = await screen.findByRole('button', { name: 'Create person "Alex"' });
    await waitFor(() => expect(markerCount(container)).toBe(1));
    expect(container.querySelector(ACCENT_PRIMARY_SELECTOR)).toBe(confirm);

    // Commit succeeds → the card renders a markerless success surface. CLUSTER lingers in
    // topClustersById until the async refetch, so the footer must re-own the accent — one
    // marker, on the footer Analyze (BR-81: no card marker ⇒ presence false ⇒ footer owns).
    await user.click(confirm);
    await screen.findByRole('link', { name: VIEW_IN_ROSTER_COPY });

    await waitFor(() => expect(markerCount(container)).toBe(1));
    expect(container.querySelector(ACCENT_PRIMARY_SELECTOR)).toBe(
      screen.getByRole('button', { name: 'Analyze selected media' }),
    );
  });

  it('bulk-tray open (committable selection): the bulk commit is the single accent primary (BR-82)', async () => {
    // A card is on screen; selecting its item and opening the tray surfaces the bulk
    // commit. It — not the card — owns the accent; the card primary steps down to neutral.
    oneAssignment();
    const user = userEvent.setup();
    const { container } = renderViewport();

    await screen.findByRole('button', { name: 'Yes' });
    // HAI-17: this multi-face assignment is committable only after its stored-face
    // disclosure has rendered. Satisfy the real precondition before opening the tray.
    await user.click(screen.getByRole('button', { name: 'Review details' }));
    await screen.findByRole('list', { name: 'Stored faces for Alex' });
    await user.click(screen.getByTestId('acx-review-select'));
    await user.click(screen.getByRole('button', { name: 'Review selection' }));

    const bulkCommit = await screen.findByTestId('acx-bulk-commit');
    // Exactly one accent marker, on the bulk commit (the card accept stepped down).
    await waitFor(() => expect(markerCount(container)).toBe(1));
    expect(container.querySelector(ACCENT_PRIMARY_SELECTOR)).toBe(bulkCommit);
    expect(bulkCommit).toHaveAttribute(ACCENT_PRIMARY_ATTR);
    expect(bulkCommit.className).toContain('acx-accent-primary-action');
    // Footer stays demoted — the queue still owns the accent, now via the bulk commit.
    expect(screen.getByRole('button', { name: 'Analyze selected media' })).not.toHaveAttribute(
      ACCENT_PRIMARY_ATTR,
    );
  });

  it('bulk-tray open (stored-face gated): the card keeps the single accent and selection count', async () => {
    // Until HAI-17 review completes, the gated bulk commit stays neutral and the
    // current card remains the queue's sole accent owner. The gate must not erase the
    // selected item from the bulk label.
    oneAssignment();
    const user = userEvent.setup();
    const { container } = renderViewport();

    const accept = await screen.findByRole('button', { name: 'Yes' });
    await user.click(screen.getByTestId('acx-review-select'));
    await user.click(screen.getByRole('button', { name: 'Review selection' }));

    const bulkCommit = await screen.findByTestId('acx-bulk-commit');
    expect(bulkCommit).toHaveTextContent('Accept 1 for Alex');
    // BR-74 / DUX-W2R2-RV-02: gated bulk stays focusable; HTML-disabled would
    // drop it from tab order so the describedby reason is unreachable.
    expect(bulkCommit).not.toBeDisabled();
    expect(bulkCommit).toHaveAttribute('aria-disabled', 'true');
    const reasonId = bulkCommit.getAttribute('aria-describedby');
    expect(reasonId).toBeTruthy();
    expect(document.getElementById(reasonId ?? '')).toHaveTextContent(
      'Review the stored faces for every selected suggestion before accepting.',
    );
    bulkCommit.focus();
    expect(bulkCommit).toHaveFocus();
    await waitFor(() => expect(markerCount(container)).toBe(1));
    expect(container.querySelector(ACCENT_PRIMARY_SELECTOR)).toBe(accept);
    expect(bulkCommit).not.toHaveAttribute(ACCENT_PRIMARY_ATTR);
  });

  it('DUX-W2R2-RV-03: gate lift while tray open keeps one accent; bulk stays in tab order', async () => {
    // Pinned focus policy: do NOT move focus to the new accent owner when the
    // stored-face gate lifts. The bulk commit must remain reachable in forward
    // tab order (not HTML-disabled) so the operator can Tab to it; we do not
    // steal focus from Review details / Yes.
    oneAssignment();
    const user = userEvent.setup();
    const { container } = renderViewport();

    const accept = await screen.findByRole('button', { name: 'Yes' });
    await user.click(screen.getByTestId('acx-review-select'));
    await user.click(screen.getByRole('button', { name: 'Review selection' }));

    const bulkCommit = await screen.findByTestId('acx-bulk-commit');
    await waitFor(() => expect(markerCount(container)).toBe(1));
    expect(container.querySelector(ACCENT_PRIMARY_SELECTOR)).toBe(accept);
    expect(bulkCommit).not.toBeDisabled();
    expect(bulkCommit).toHaveAttribute('aria-disabled', 'true');

    await user.click(screen.getByRole('button', { name: 'Review details' }));
    await screen.findByRole('list', { name: 'Stored faces for Alex' });

    await waitFor(() => expect(markerCount(container)).toBe(1));
    expect(container.querySelector(ACCENT_PRIMARY_SELECTOR)).toBe(bulkCommit);
    expect(bulkCommit).toHaveAttribute(ACCENT_PRIMARY_ATTR);
    expect(bulkCommit).not.toBeDisabled();
    expect(bulkCommit).not.toHaveAttribute('aria-disabled', 'true');
    expect(bulkCommit).not.toHaveFocus();
    bulkCommit.focus();
    expect(bulkCommit).toHaveFocus();
  });

  it('panel open (queue unmounted, panels carry no marker): the footer keeps the single accent primary (BR-83)', async () => {
    // A label/review panel replaces the queue. With the queue unmounted no card/bulk
    // marker is on screen, so the footer's state-selected Analyze is the single primary.
    emptyQueues();
    const { container } = renderViewport({ panelOpen: true });

    await screen.findByTestId('mock-review-panel');

    expect(markerCount(container)).toBe(1);
    expect(container.querySelector(ACCENT_PRIMARY_SELECTOR)).toBe(
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
      ajaxUrl: '/wp-admin/admin-ajax.php',
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
    vi.mocked(commitClusterToRosterEntry).mockResolvedValue(rosterCommitFixture());
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
