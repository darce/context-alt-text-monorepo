/**
 * Banned-vocabulary sweep over every js/admin page surface.
 *
 * Enumerates page modules from the pages/ directory so a new page that is
 * missing from PAGE_SWEEP fails CI. Representative fixtures only — if jargon
 * is injected into a page module under those fixtures, this test fails.
 */
import { readdirSync, readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { createMockMutation, createMockQuery } from '../test-utils/mockHooks';
// Type-only (erased at compile time, so no vi.mock hoisting hazard). Annotating the
// media stub against the real context type is what stops the next context-shape change
// from silently rotting this mock the way S1c-2 did.
import type { WorkbenchMediaContextValue } from '../pages/workbench/WorkbenchMediaContext';
import { DATA_SOURCE } from '../api/recognition/types/dataSource';

const pagesDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../pages');

/** Page modules that live directly under js/admin/pages/*.tsx */
const pageModulesOnDisk = readdirSync(pagesDir)
  .filter((name) => name.endsWith('Page.tsx') || name === 'DescribeRunApplyView.tsx')
  .map((name) => name.replace(/\.tsx$/, ''))
  .sort();

/**
 * Sweep registry: every page module must appear here. Add fixtures when a new
 * page lands — the test fails if the disk list and this map diverge.
 */
const PAGE_SWEEP = [
  'DashboardPage',
  'WorkbenchPage',
  'RosterPage',
  'DescriptionHistoryPage',
  'RetentionPage',
  'SettingsPage',
  'DescribeRunApplyView',
] as const;

type PageName = (typeof PAGE_SWEEP)[number];

const BANNED_STRINGS = [
  'topology',
  'replay',
  'projection',
  'dead-letter',
  'curation acknowledgement',
  'Source version',
  'projected instances',
  'Curriculum',
  // UXP-4 slice 2: ops dialect retired from operator-facing surfaces
  'Delta sync',
  'Machine sync',
  'Machine state',
  'Sync backlog',
  // UXP-4 slice 3: retention card jargon retired
  'Retention posture',
  // UXP-4 slice 5: roster jargon retired
  'Managed Identities',
] as const;

const UUID_REGEX = /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/i;

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

// --- Shared hook/API mocks (representative empty/healthy fixtures) ---

vi.mock('../hooks/useMediaStats', () => ({
  useMediaStats: () => ({
    stats: { total: 0, described: 0, coverage: 0 },
    isLoading: false,
  }),
}));

vi.mock('../hooks/useRecognitionJobHistory', () => ({
  useRecognitionJobHistory: () => ({
    jobHistory: [],
    jobStatuses: {},
    jobDetails: {},
    recentActivity: [],
    historySource: 'unavailable',
  }),
}));

vi.mock('../hooks/useIdentityStats', () => ({
  useIdentityStats: () =>
    createMockQuery({
      data: {
        assigned_clusters_count: 0,
        pending_clusters_count: 0,
        unassigned_persons_count: 0,
      },
    }),
}));

vi.mock('../hooks/useSyncStatus', () => ({
  useSyncStatus: () =>
    createMockQuery({
      data: {
        last_snapshot_version: 1,
        last_synced_at: '2026-02-14T12:00:00Z',
        is_stale: false,
        sync_health: 'healthy',
        last_sync_result: 'ok',
      },
    }),
}));

vi.mock('../hooks/useSyncHealth', () => ({
  useSyncHealth: () =>
    createMockQuery({
      data: {
        breaker: { state: 'closed', base_url: 'http://localhost:8000', opened_at: null },
        outbox: { pending: 0, failed: 0 },
        conflicts: { open: 0 },
        replays: { failed: null, source: 'unavailable_local' },
        last_pull: { at: '2026-06-11T12:00:00Z', ok: true },
        warnings: [],
      },
    }),
}));

vi.mock('../hooks/useSyncTrigger', () => ({
  useSyncTrigger: () => createMockMutation({}),
  useResetMirror: () => createMockMutation({}),
}));

vi.mock('../hooks/useRetentionStatus', () => ({
  useRetentionStatus: () =>
    createMockQuery({
      data: {
        available: true,
        policy: {
          retention_mode: 'retain_all',
          last_export_at: null,
          last_purge_at: null,
          retention_updated_at: null,
        },
        recent_audit_events: [],
      },
    }),
  useUpdateRetentionPolicy: () => createMockMutation({}),
  useExportTenantData: () => createMockMutation({}),
  useExportJobStatus: () => createMockQuery({ data: null }),
  useDownloadExportJobData: () => createMockMutation({}),
  usePurgeTenantData: () => createMockMutation({}),
  useImportTenantData: () => createMockMutation({}),
  useAuditEvents: () => createMockQuery({ data: { items: [], total: 0 } }),
  useApplyRetentionPreset: () => createMockMutation({}),
}));

vi.mock('../hooks/useRosterEntries', () => ({
  useRosterEntries: () =>
    createMockQuery({
      data: { data: [], total: 0, limit: 50, offset: 0 },
    }),
}));

vi.mock('../hooks/useClusters', () => ({
  useClusters: () => createMockQuery({ data: { data: [], total: 0 } }),
}));

vi.mock('../context/ToastContext', () => ({
  useToast: () => ({ success: vi.fn(), error: vi.fn(), info: vi.fn() }),
}));

vi.mock('../api/settingsApi', async () => {
  const actual = await vi.importActual<typeof import('../api/settingsApi')>('../api/settingsApi');
  return {
    ...actual,
    fetchSettings: vi.fn().mockResolvedValue({
      url: 'https://api.example.com',
      url_source: 'option',
      effective_target_url: 'https://api.example.com',
      effective_target_mode: 'service',
      recognition_source: 'service',
      recognition_source_source: 'option',
      api_key_set: true,
      api_key_last4: 'abcd',
      key_source: 'option',
      tenant_id: '',
      tenant_id_source: 'option',
      tenant_paired: false,
      description_budget: {
        max_attempts: -1,
        usage: { used: 0, remaining: null, reset_at: null },
      },
    }),
    saveSettings: vi.fn(),
    testConnection: vi.fn(),
  };
});

vi.mock('../api/describeApi', async () => {
  const actual = await vi.importActual<typeof import('../api/describeApi')>('../api/describeApi');
  return {
    ...actual,
    fetchDescriptionHistory: vi.fn().mockResolvedValue({ items: [], total: 0 }),
    fetchDescribeRunItems: vi.fn().mockResolvedValue({ run_id: 'run-1', items: [] }),
    applyDescribeRunDrafts: vi.fn(),
    correctDescriptionHistoryItem: vi.fn(),
  };
});

vi.mock('../api/config', () => ({
  getEndpoint: (key: string) => `/acx/v1/${key}`,
  getConfig: () => ({
    nonce: 'test-nonce',
    ajaxUrl: '/wp-admin/admin-ajax.php',
    endpoints: {},
  }),
  resetConfigCache: vi.fn(),
}));

// Workbench state fans out over four provider modules since E21-11 S2 — stub each
// module (hook + provider passthrough) so the sweep stays decoupled from provider wiring.
vi.mock('../pages/workbench/WorkbenchNavContext', async () => {
  const React = await import('react');
  const actual = await vi.importActual<typeof import('../pages/workbench/WorkbenchNavContext')>(
    '../pages/workbench/WorkbenchNavContext',
  );
  const stub = {
    activeSection: 'scan',
    setActiveSection: vi.fn(),
    activeOverlay: null,
    setActiveOverlay: vi.fn(),
    isAdvancedOpen: false,
    setAdvancedOpen: vi.fn(),
    recognitionSource: 'service',
    effectiveTargetUrl: 'https://api.example.com',
  };
  return {
    ...actual,
    WorkbenchNavProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
    useWorkbenchNav: () => stub,
  };
});

vi.mock('../pages/workbench/JobPipelineContext', () => {
  const stub = {
    scanRun: {
      isScanning: false,
      isCancelling: false,
      statusText: undefined,
      jobId: null,
      errorMessage: null,
      progress: null,
      batchRunStatus: null,
      stallSeconds: null,
      etaSeconds: null,
      isSynced: false,
    },
    status: {
      currentPhase: 'idle',
      projectionSyncState: 'idle',
      projectionError: null,
      isOnline: true,
      scanProgress: null,
      clusterProgress: null,
      clusterMessage: null,
    },
    history: {
      jobId: null,
      latestJobId: null,
      activeJobIds: [],
      jobHistory: [],
      jobStatuses: {},
      historySource: 'unavailable',
    },
    scan: vi.fn(),
    cancelScan: vi.fn(),
    cluster: vi.fn(),
    retryClustering: vi.fn(),
    retryProjectionSync: vi.fn(),
    retryScanStream: vi.fn(),
    handleSelectJobFromHistory: vi.fn(),
    clearHistory: vi.fn(),
  };
  return {
    JobPipelineProvider: ({ children }: { children: import('react').ReactNode }) => <>{children}</>,
    useJobPipeline: () => stub,
  };
});

vi.mock('../pages/workbench/ClusterPanelContext', () => {
  const stub = {
    clusterPanel: { mode: 'none', clusterId: null },
    dispatchClusterPanel: vi.fn(),
  };
  return {
    ClusterPanelProvider: ({ children }: { children: import('react').ReactNode }) => <>{children}</>,
    useClusterPanel: () => stub,
  };
});

// Media concern lives in its own provider since E21-11 S1 — stub it alongside the monolith.
// S1c-2 mounts MediaSelection directly (no ScanTabContent shell), so the stub must publish
// the detail/identities sub-query surfaces MediaSelection reads, and must carry a row —
// with an empty queue this page renders "No media matches your search." and sweeps nothing.
//
// WHAT THIS FIXTURE ACTUALLY SWEEPS: the idle one-row surface — the media table chrome and
// pagination, `No alt text yet`, `Suggest alt text`, `Edit alt text`, `No tags`, and the
// `No identities detected yet.` empty state.
// WHAT IT STILL DOES NOT SWEEP, so do not read green here as "media copy is locked":
//   - every mutation-driven branch of MediaAltSuggest / MediaAltInlineEditor (`Generating…`,
//     `Drafted by AI — review before saving.`, `Accept`, `Edit draft`, `Dismiss`,
//     `Save alt text`, `Cancel edit`, and both error strings) — reaching them needs a
//     driven mutation, not a fixture;
//   - the three non-default IdentityClusterList empty states (UNAVAILABLE / ENDPOINT_ERROR /
//     LOCAL_PROJECTION) — data_source selects exactly one branch per fixture;
//   - the detail-unavailable / skeleton branches, which need detailReady false.
vi.mock('../pages/workbench/WorkbenchMediaContext', () => {
  // Neutral fixture — no banned jargon, no UUID (id 11). Shape mirrors
  // MediaSelection.authExpired.test.tsx baseItem. altText: null and tags: [] are the
  // deliberate choices: they render real operator copy rather than echoing fixture text.
  const sweepMediaItem = {
    id: 11,
    title: 'Photo',
    altText: null,
    isDecorative: false,
    status: 'missing' as const,
    thumbnailUrl: null,
    mimeType: 'image/jpeg',
    editUrl: '#',
    updatedAt: '2026-01-01T00:00:00Z',
    dimensions: { width: 100, height: 100 },
    tags: [],
    identities: [],
    // Required on the detail-merged row type; no UI consumer reads it.
    xmpPersistence: null,
  };

  // Full query results via createMockQuery, then project to the published surfaces
  // (detailSurface / identitiesSurface in useWorkbenchMedia.ts) so the asymmetry is
  // preserved: detail publishes isPending, identities publishes isPlaceholderData.
  // total: 0 because detailsByMedia is empty — the detail endpoint reports rows returned,
  // not ids requested. data_source is required: fetchMediaIdentities throws on an envelope
  // without one, so an envelope lacking it is a shape production can never emit.
  const detailQuerySource = createMockQuery({
    data: { detailsByMedia: {}, limit: 100, total: 0, truncated: false },
  });
  const identitiesQuerySource = createMockQuery({
    data: { identities_by_media: {}, data_source: DATA_SOURCE.BACKEND_PROXY },
  });

  // Annotated against the real context type: the next shape change fails typecheck here
  // instead of throwing at render the way BR-21 did.
  const stub: WorkbenchMediaContextValue = {
    selection: {
      selection: {},
      selectedMedia: [],
      toggleRow: vi.fn(),
      toggleAll: vi.fn(),
      isPageFullySelected: () => false,
    },
    filters: {
      searchQuery: '',
      statusFilter: 'all',
      currentPage: 1,
      // MEDIA_PAGE_SIZE_OPTIONS is [10, 50, 100]; 20 was never a selectable value.
      perPage: 10,
      handleSearchChange: vi.fn(),
      handleStatusChange: vi.fn(),
      setCurrentPage: vi.fn(),
      setPerPage: vi.fn(),
    },
    mediaQueue: {
      mediaQuery: {
        data: { items: [sweepMediaItem], total: 1, totalPages: 1 },
        itemsWithIdentities: [sweepMediaItem],
        isPending: false,
        isFetching: false,
        isError: false,
        isSuccess: true,
        refetch: vi.fn(),
        // detailSurface: data, isPending, isLoading, isFetching, isError, error, refetch
        detailQuery: {
          data: detailQuerySource.data,
          isPending: detailQuerySource.isPending,
          isLoading: detailQuerySource.isLoading,
          isFetching: detailQuerySource.isFetching,
          isError: detailQuerySource.isError,
          error: detailQuerySource.error,
          refetch: detailQuerySource.refetch,
        },
        // identitiesSurface: data, isLoading, isError, error, isPlaceholderData, isFetching, refetch
        identitiesQuery: {
          data: identitiesQuerySource.data,
          isLoading: identitiesQuerySource.isLoading,
          isError: identitiesQuerySource.isError,
          error: identitiesQuerySource.error,
          isPlaceholderData: identitiesQuerySource.isPlaceholderData,
          isFetching: identitiesQuerySource.isFetching,
          refetch: identitiesQuerySource.refetch,
        },
      },
      // Both derived by the real provider from the queue above: one item means
      // 'Showing 1 media item.' and hasIdentities true. Leaving the empty-queue values
      // here would publish a queue that contradicts its own row.
      statusMessage: 'Showing 1 media item.',
      isStatusPending: false,
      detailTruncationNotice: null,
      hasIdentities: true,
    },
  };
  return {
    WorkbenchMediaProvider: ({ children }: { children: import('react').ReactNode }) => <>{children}</>,
    useWorkbenchMediaContext: () => stub,
  };
});

// Heavy workbench children still pull deeper hooks — keep them as plain shells so the
// page sweep covers WorkbenchPage chrome + SyncStatusIndicator status copy.
vi.mock('../pages/workbench/ScanTabContent', () => ({
  ScanTabContent: () => <div data-testid="acx-scan-tab-shell">Scan tab</div>,
}));
vi.mock('../pages/workbench/ConfirmTabContent', () => ({
  ConfirmTabContent: () => <div data-testid="acx-confirm-tab-shell">Confirm tab</div>,
}));
vi.mock('../pages/workbench/ConflictInbox', () => ({
  ConflictInbox: () => null,
}));
vi.mock('../pages/workbench/DeadLetterPanel', () => ({
  DeadLetterPanel: () => null,
}));

import { DashboardPage } from '../pages/DashboardPage';
import { DescribeRunApplyView } from '../pages/DescribeRunApplyView';
import { DescriptionHistoryPage } from '../pages/DescriptionHistoryPage';
import { RetentionPage } from '../pages/RetentionPage';
import { RosterPage } from '../pages/RosterPage';
import { SettingsPage } from '../pages/SettingsPage';
import { WorkbenchPage } from '../pages/WorkbenchPage';
import type { ClusterIdentity, ClusterSummary } from '../api/recognition';
import type { RosterEntry } from '../api/rosterApi';
import { ClusterDrawerPanel } from '../pages/roster/ClusterDrawerPanel';
import { PersonWorkspacePanel } from '../pages/roster/PersonWorkspacePanel';
import { ClusterReviewPanel } from '../pages/workbench/identity-clusters/ClusterReviewPanel';

const reviewMembersState = vi.hoisted(() => ({
  members: [
    {
      identity_id: 'face-1',
      media_id: 7,
      similarity: 0.9,
      confidence: 0.9,
      bbox: null,
      thumb_url: 'https://example.com/face-7.jpg',
      attachment_url: null,
      media_url: 'https://example.com/face-7.jpg',
    },
  ],
}));

vi.mock('../pages/workbench/identity-clusters/useShowAllClusterMembers', () => ({
  useShowAllClusterMembers: () => ({
    members: reviewMembersState.members,
    isLoading: false,
    isError: false,
    truncated: false,
    total: reviewMembersState.members.length,
    isFullyLoaded: true,
    isExpanding: false,
    expandError: null,
    showAll: vi.fn(),
    refetch: vi.fn(),
  }),
}));

const pageRenderers: Record<PageName, () => React.JSX.Element> = {
  DashboardPage: () => <DashboardPage />,
  WorkbenchPage: () => <WorkbenchPage />,
  RosterPage: () => <RosterPage />,
  DescriptionHistoryPage: () => <DescriptionHistoryPage />,
  RetentionPage: () => <RetentionPage />,
  SettingsPage: () => <SettingsPage />,
  DescribeRunApplyView: () => <DescribeRunApplyView runId="run-1" />,
};

const wrap = (node: React.JSX.Element) => {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return (
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <Routes>
          <Route path="*" element={node} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>
  );
};

const collectVisibleText = (container: HTMLElement): string => {
  const attrBits = Array.from(
    container.querySelectorAll('[alt],[aria-label],[aria-description],[title],[placeholder]'),
  )
    .map((el) =>
      [
        el.getAttribute('alt'),
        el.getAttribute('aria-label'),
        el.getAttribute('aria-description'),
        el.getAttribute('title'),
        el.getAttribute('placeholder'),
      ]
        .filter((value): value is string => Boolean(value))
        .join(' '),
    )
    .join(' ');
  return `${container.textContent ?? ''} ${attrBits}`;
};

describe('banned vocabulary across js/admin pages', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('fails when a pages/ module is missing from the sweep registry', () => {
    expect([...PAGE_SWEEP].sort()).toEqual(pageModulesOnDisk);
  });

  it.each(PAGE_SWEEP)('renders %s without banned jargon', (pageName) => {
    const { container } = render(wrap(pageRenderers[pageName]()));
    const text = collectVisibleText(container);

    for (const banned of BANNED_STRINGS) {
      expect(text.toLowerCase()).not.toContain(banned.toLowerCase());
    }
    expect(text).not.toMatch(UUID_REGEX);
  });

  it('demonstrates failure when jargon is injected into the DOM', () => {
    const { container } = render(
      wrap(
        <div>
          <span>topology backlog leak</span>
        </div>,
      ),
    );
    const text = collectVisibleText(container);
    expect(text.toLowerCase()).toContain('topology');
  });

  /**
   * Slice 3: WorkbenchPage mocks ScanTabContent, so chip + HAI-05 + person-commit
   * copy are swept here as constants that render on the review-queue surface.
   */
  it('review-queue chip + person-commit + HAI-05 copy are free of banned jargon', async () => {
    const {
      NEXT_ACTION_CHIP_LABEL,
      NEXT_ACTION_KIND,
      REVIEW_QUEUE_BAND,
      REVIEW_QUEUE_BAND_CHIP_LABEL,
    } = await import('../pages/workbench/identity-clusters/reviewQueueDriver');
    // BR-33: sweep every exported person-commit copy constant (import *).
    const personCommitCopy = await import('../pages/workbench/identity-clusters/personCommitCopy');
    // Slice 5: bulk commit / hold / PR-38 labels.
    const bulkCopy = await import('../pages/workbench/identity-clusters/useBulkReviewCommit');

    const personCommitStrings = Object.values(personCommitCopy).filter(
      (value): value is string => typeof value === 'string',
    );
    const surface = [
      NEXT_ACTION_CHIP_LABEL[NEXT_ACTION_KIND.ASSIGNMENT],
      NEXT_ACTION_CHIP_LABEL[NEXT_ACTION_KIND.MERGE],
      // Slice 6 ④ band chip labels.
      REVIEW_QUEUE_BAND_CHIP_LABEL[REVIEW_QUEUE_BAND.STRONG],
      REVIEW_QUEUE_BAND_CHIP_LABEL[REVIEW_QUEUE_BAND.WEAKER],
      ...personCommitStrings,
      bulkCopy.bulkCommitLabel(4, 'Maria'),
      bulkCopy.bulkCommitLabel(3, null),
      bulkCopy.bulkHoldStatusCopy(5),
    ].join(' ');

    for (const banned of BANNED_STRINGS) {
      expect(surface.toLowerCase()).not.toContain(banned.toLowerCase());
    }
    expect(surface).toContain(personCommitCopy.MODEL_OUTPUT_DISCLOSURE);
    expect(surface).toContain(personCommitCopy.PERSON_COMMIT_SUCCESS_COPY);
    expect(surface).toContain(personCommitCopy.PERSON_COMMIT_COMBOBOX_ARIA);
    expect(surface).toContain(personCommitCopy.PERSON_COMMIT_PLACEHOLDER);
    expect(surface).toContain(personCommitCopy.PERSON_COMMIT_COMMITTING_COPY);
    expect(surface).toContain('Accept 4 for Maria');
    expect(surface).toContain('Accept 3 selected');
    expect(surface).toContain('Saving 5… — Undo');
    expect(surface).not.toMatch(UUID_REGEX);
  });

  /**
   * UXP-4 slice 3: retention card copy is conditional on DashboardPage, so
   * constants are swept via import * (personCommitCopy pattern).
   */
  it('retention card copy constants are free of banned jargon', async () => {
    const retentionCardCopy = await import('../pages/dashboard/retentionCardCopy');
    const retentionStrings = Object.values(retentionCardCopy).filter(
      (value) => typeof value === 'string',
    ) as string[];
    const surface = retentionStrings.join(' ');

    for (const banned of BANNED_STRINGS) {
      expect(surface.toLowerCase()).not.toContain(banned.toLowerCase());
    }
    expect(surface).toContain(retentionCardCopy.RETENTION_CARD_HEADING);
    expect(surface).toContain(retentionCardCopy.RETENTION_CARD_ERROR_BODY);
    expect(surface).toContain(retentionCardCopy.RETENTION_CARD_LINK_HREF);
    expect(surface).not.toMatch(UUID_REGEX);
  });

  /**
   * UXP-4 slice 4: ConfirmTabContent is mocked in the WorkbenchPage sweep, so
   * clustering disclosure + no-job zero-state constants are swept via import *.
   */
  it('confirm tab copy constants are free of banned jargon', async () => {
    const confirmTabCopy = await import('../pages/workbench/confirmTabCopy');
    const confirmStrings = Object.values(confirmTabCopy).filter((value) => typeof value === 'string') as string[];
    const surface = confirmStrings.join(' ');

    for (const banned of BANNED_STRINGS) {
      expect(surface.toLowerCase()).not.toContain(banned.toLowerCase());
    }
    expect(surface).toContain(confirmTabCopy.CLUSTERING_DISCLOSURE_SUMMARY);
    expect(surface).toContain(confirmTabCopy.CLUSTERING_DISCLOSURE_BODY);
    expect(surface).toContain(confirmTabCopy.CONFIRM_PANEL_INTRO);
    expect(surface).toContain(confirmTabCopy.CONFIRM_NO_JOB_ZERO_STATE);
    expect(surface.toLowerCase()).not.toContain('embeddings');
    expect(surface).not.toMatch(UUID_REGEX);
  });

  /**
   * UXW2-4: Roster surfaces say "faces" / "face group" / "person" — never
   * cluster / identities / projected instances (NAV-13 controlled vocabulary).
   * The RosterPage empty-fixture sweep cannot reach the drawer (`?cluster=`
   * deep-link shim) or the person workspace (`?person=`), so both panels are
   * rendered directly here with representative fixtures.
   */
  it('roster surfaces render without cluster/identity jargon', () => {
    const ROSTER_BANNED = ['cluster', 'identity', 'identities', 'member', 'projected instances'] as const;
    const SURFACE_BANNED = [...BANNED_STRINGS, ...ROSTER_BANNED];

    const drawerCluster: ClusterSummary = {
      id: 'drawer-fixture-1',
      label: null,
      identity_count: 2,
      member_ids: ['face-1', 'face-2'],
      representative_identity: { media_id: 7, bbox: { x: 0, y: 0, width: 100, height: 100 } },
      sample_identities: [],
    };
    const drawerFaces: ClusterIdentity[] = [
      { identity_id: 'face-1', media_id: 7, similarity: 0.9, confidence: 0.9, bbox: null },
    ];
    const { container: drawerContainer } = render(
      wrap(
        <ClusterDrawerPanel
          cluster={drawerCluster}
          identities={drawerFaces}
          mediaMap={{}}
          onClose={vi.fn()}
          onRescanCluster={vi.fn()}
          isRescanning={false}
          onCommitCluster={vi.fn()}
          onOpenPersonWorkspace={vi.fn()}
          isCommitting={false}
          rosterEntries={[]}
          isDetailLoading={false}
          onFaceDragStart={vi.fn()}
          onFaceDragEnd={vi.fn()}
          onDropTargetChange={vi.fn()}
          dropTarget={null}
          isDragging={false}
          onDiscardDrop={vi.fn()}
        />,
      ),
    );

    const rosterEntry: RosterEntry = {
      id: 1,
      person_uuid: 'person-fixture-1',
      name: 'Alice',
      tags: [],
      cluster_count: 1,
      clusters: [
        {
          cluster_id: 'drawer-fixture-1',
          identity_count: 1,
          representative_identity: {
            identity_id: 'face-1',
            media_id: 7,
            media_url: 'https://example.com/face-7.jpg',
            bbox: { x: 10, y: 20, width: 30, height: 40 },
            similarity: 0.95,
            similarity_threshold: 0.8,
          },
          instances: [
            {
              identity_id: 'face-1',
              media_id: 7,
              media_url: 'https://example.com/face-7.jpg',
              bbox: { x: 10, y: 20, width: 30, height: 40 },
              similarity: 0.95,
              similarity_threshold: 0.8,
            },
          ],
        },
      ],
      queue_memberships: [],
      updated_at: '2026-05-07T12:00:00Z',
      source_version: 11,
      projection_status: 'current',
      projection_refreshed_at: '2026-05-07T12:00:00Z',
    };
    const { container: workspaceContainer } = render(
      wrap(<PersonWorkspacePanel entry={rosterEntry} onOpenQueue={vi.fn()} />),
    );

    const { container: pageContainer } = render(wrap(<RosterPage />));

    const { container: reviewContainer } = render(
      wrap(<ClusterReviewPanel clusterId="review-fixture-1" onClose={vi.fn()} />),
    );

    const drawerText = collectVisibleText(drawerContainer).toLowerCase();
    expect(drawerText).toContain('unnamed face group');
    const workspaceText = collectVisibleText(workspaceContainer).toLowerCase();
    expect(workspaceText).toContain('alice');
    expect(workspaceText).toContain('data status');
    const pageText = collectVisibleText(pageContainer).toLowerCase();
    expect(pageText).toMatch(/unnamed faces|face groups waiting|reviewed in the workbench/);
    const reviewText = collectVisibleText(reviewContainer).toLowerCase();
    expect(reviewText).toContain('review these faces');

    for (const [label, text] of [
      ['drawer', drawerText],
      ['workspace', workspaceText],
      ['page', pageText],
      ['review', reviewText],
    ] as const) {
      for (const banned of SURFACE_BANNED) {
        expect(text, `${label} leaked "${banned}"`).not.toContain(banned.toLowerCase());
      }
      expect(text).not.toMatch(UUID_REGEX);
    }
  });

  /**
   * UXP-4 BR-02: PurgeDialog options are not mounted by the RetentionPage
   * empty fixture (dialog closed), so scope-option constants are swept via
   * import * (retentionCardCopy pattern).
   */
  it('retention purge-dialog copy constants are free of banned jargon', async () => {
    const retentionDialogCopy = await import('../pages/retention/retentionDialogCopy');
    const purgeStrings = Object.values(retentionDialogCopy).filter((value) => typeof value === 'string') as string[];
    const surface = purgeStrings.join(' ');

    for (const banned of BANNED_STRINGS) {
      expect(surface.toLowerCase()).not.toContain(banned.toLowerCase());
    }
    expect(surface).toContain(retentionDialogCopy.PURGE_DIALOG_DESCRIPTION);
    expect(surface).toContain(retentionDialogCopy.PURGE_SCOPE_ALL_DESCRIPTION);
    expect(surface.toLowerCase()).not.toContain('machine state');
    expect(surface.toLowerCase()).not.toContain('machine-derived');
    expect(surface.toLowerCase()).not.toContain('disposed state');
    expect(surface).not.toMatch(UUID_REGEX);
  });

  it('js/admin production source has no cluster-jargon toasts or bulk merge/dismiss', () => {
    const adminDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
    const files: string[] = [];
    const walk = (dir: string): void => {
      for (const entry of readdirSync(dir, { withFileTypes: true })) {
        const full = path.join(dir, entry.name);
        if (entry.isDirectory()) {
          if (entry.name === '__tests__' || entry.name === 'node_modules') {
            continue;
          }
          walk(full);
          continue;
        }
        if (/\.(ts|tsx)$/.test(entry.name)) {
          files.push(full);
        }
      }
    };
    walk(adminDir);
    const joined = files.map((file) => readFileSync(file, 'utf8')).join('\n');
    expect(joined).not.toMatch(/for cluster %s/);
    expect(joined).not.toMatch(/bulkMergeMutation|bulkDismissMutation/);
    expect(joined).not.toMatch(/Clusters merged successfully|Clusters dismissed/);
  });
});
