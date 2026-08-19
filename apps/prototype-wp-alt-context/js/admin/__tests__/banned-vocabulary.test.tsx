/**
 * Banned-vocabulary sweep over every js/admin page surface.
 *
 * Enumerates page modules from the pages/ directory so a new page that is
 * missing from PAGE_SWEEP fails CI. Representative fixtures only — if jargon
 * is injected into a page module under those fixtures, this test fails.
 */
import { readFileSync, readdirSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, waitFor } from '@testing-library/react';
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
  .filter((name) => !name.startsWith('._') && (name.endsWith('Page.tsx') || name === 'DescribeRunApplyView.tsx'))
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

/**
 * UXW2-3: engineering vocabulary banned as whole words from the rendered
 * workbench review surfaces changed in this lane (ClusterReviewPanel headline /
 * member rows / removal dialog). Scoped here instead of BANNED_STRINGS so the
 * Roster/ops page sweeps keep passing until their owning lanes extend the ban.
 */
const BANNED_REVIEW_SURFACE_WORDS = [
  /\bclusters?\b/i,
  /\bidentities\b/i,
  /\bidentity\b/i,
  /\binstances?\b/i,
  /\binstance\b/i,
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
  isDevMode: () => false,
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

// UXW2-3: one-member fixture so the review panel paints its real member-row copy.
vi.mock('../hooks/useRosterHooks', async () => {
  const actual = await vi.importActual<typeof import('../hooks/useRosterHooks')>('../hooks/useRosterHooks');
  return {
    ...actual,
    useRosterEntries: () =>
      createMockQuery({
        data: [],
        isLoading: false,
        isError: false,
        isSuccess: true,
        refetch: vi.fn(),
      }),
  };
});

vi.mock('../api/rosterApi', async () => {
  const actual = await vi.importActual<typeof import('../api/rosterApi')>('../api/rosterApi');
  return {
    ...actual,
    listRosterEntries: vi.fn().mockResolvedValue([]),
    commitClusterToRosterEntry: vi.fn(),
  };
});

vi.mock('../api/recognition', async () => {
  const actual = await vi.importActual<typeof import('../api/recognition')>('../api/recognition');
  return {
    ...actual,
    fetchClusterMembers: vi.fn().mockResolvedValue({ members: [], limit: 1, total: 0, truncated: false }),
    listRecognitionClusters: vi.fn().mockResolvedValue({ clusters: [], limit: 10, total: 0, truncated: false }),
    fetchPendingSuggestions: vi.fn(() => new Promise(() => undefined)),
    fetchPendingMergeSuggestions: vi.fn(() => new Promise(() => undefined)),
    fetchPendingNameSuggestions: vi.fn(() => new Promise(() => undefined)),
    fetchTopUnlabeledClusters: vi.fn(() => new Promise(() => undefined)),
    updateClusterLabel: vi.fn(),
    mergeCluster: vi.fn(),
    revertMergeCluster: vi.fn(),
  };
});

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
  useShowAllClusterMembers: vi.fn(() => ({
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
  })),
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

const ACCESSIBLE_ATTRS = ['aria-label', 'title', 'alt', 'placeholder', 'aria-description'] as const;

const collectReviewSurfaceText = (root: HTMLElement = document.body): string => {
  const chunks = [root.textContent ?? ''];
  // Join per-element text so adjacent controls cannot glue "ClusterSplit" and
  // hide a whole-word hit from \\bclusters?\\b (UXW2-3-R3-09 TEST-15).
  root.querySelectorAll('button, p, h1, h2, h3, h4, span, label, li, [role]').forEach((node) => {
    chunks.push(node.textContent ?? '');
  });
  for (const attr of ACCESSIBLE_ATTRS) {
    root.querySelectorAll(`[${attr}]`).forEach((node) => {
      chunks.push(node.getAttribute(attr) ?? '');
    });
  }
  return chunks.join(' ');
};

const assertNoBannedReviewWords = (root: HTMLElement = document.body): void => {
  const text = collectReviewSurfaceText(root);
  for (const pattern of BANNED_REVIEW_SURFACE_WORDS) {
    expect(text).not.toMatch(pattern);
  }
};

/** Operator-visible UX-map fields only. Ids / url_params / code_ref / decision records are exempt. */
const UXMAP_OPERATOR_COPY_KEYS = new Set([
  'title',
  'label',
  'purpose',
  'verb',
  'goals',
  'description',
  'branch_label',
]);

const UXMAP_EXEMPT_KEYS = new Set(['id', 'url_params', 'code_ref', 'open_questions', 'not_doing']);

const UXMAP_RETIRED_WORDS = [...BANNED_REVIEW_SURFACE_WORDS, /\bembeddings?\b/i] as const;

const collectUxMapOperatorCopy = (value: unknown, key?: string): string[] => {
  if (key && UXMAP_EXEMPT_KEYS.has(key)) {
    return [];
  }
  if (typeof value === 'string') {
    return key && UXMAP_OPERATOR_COPY_KEYS.has(key) ? [value] : [];
  }
  if (Array.isArray(value)) {
    if (key && UXMAP_OPERATOR_COPY_KEYS.has(key)) {
      return value.filter((item): item is string => typeof item === 'string');
    }
    return value.flatMap((item) => collectUxMapOperatorCopy(item, key));
  }
  if (value && typeof value === 'object') {
    return Object.entries(value).flatMap(([childKey, child]) => collectUxMapOperatorCopy(child, childKey));
  }
  return [];
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
    const text = collectReviewSurfaceText(container);

    for (const banned of BANNED_STRINGS) {
      expect(text.toLowerCase()).not.toContain(banned.toLowerCase());
    }
    expect(text).not.toMatch(UUID_REGEX);
  });

  it('demonstrates failure when jargon is injected into the DOM', () => {
    const { container } = render(
      wrap(
        <div>
          <span aria-label="topology backlog leak" />
        </div>,
      ),
    );
    const text = collectReviewSurfaceText(container);
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
    const lightboxNameCopy = await import('../pages/workbench/identity-clusters/LightboxNameFace');
    const closeMatchCopy = await import('../pages/workbench/identity-clusters/CloseMatchAcceptOffer');

    const personCommitStrings = Object.values(personCommitCopy).filter(
      (value) => typeof value === 'string',
    ) as string[];
    const closeMatchStrings = Object.values(closeMatchCopy.CLOSE_MATCH_OFFER_COPY).filter(
      (value) => typeof value === 'string',
    ) as string[];
    const surface = [
      NEXT_ACTION_CHIP_LABEL[NEXT_ACTION_KIND.ASSIGNMENT],
      NEXT_ACTION_CHIP_LABEL[NEXT_ACTION_KIND.MERGE],
      // Slice 6 ④ band chip labels.
      REVIEW_QUEUE_BAND_CHIP_LABEL[REVIEW_QUEUE_BAND.STRONG],
      REVIEW_QUEUE_BAND_CHIP_LABEL[REVIEW_QUEUE_BAND.WEAKER],
      ...personCommitStrings,
      lightboxNameCopy.LIGHTBOX_NAME_SAVED_ANNOUNCE,
      ...closeMatchStrings,
      closeMatchCopy.closeMatchOfferDescription(2),
      closeMatchCopy.closeMatchAcceptedAnnouncement(2, 0),
      closeMatchCopy.closeMatchAcceptedAnnouncement(25, 3),
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
   * UXW2-3: rendered workbench review surfaces (the lane-changed ones) carry no
   * "cluster"/"identities"/"instances" wording. ClusterReviewPanel is not mounted
   * by any PAGE_SWEEP fixture (ScanTabContent is mocked), so it renders here.
   */
  it('workbench review panel renders without engineering vocabulary', async () => {
    const { ClusterReviewPanel } = await import('../pages/workbench/identity-clusters/ClusterReviewPanel');
    render(wrap(<ClusterReviewPanel clusterId="cluster-1" onClose={() => undefined} />));
    assertNoBannedReviewWords(document.body);
    expect(collectReviewSurfaceText(document.body)).toContain('Review these faces');
    expect(collectReviewSurfaceText(document.body)).not.toMatch(UUID_REGEX);
  });

  it('collects aria-label/title/alt/placeholder so a banned attribute fails the sweep (UXW2-3-R1-06)', () => {
    render(wrap(<button type="button" aria-label="Open cluster" title="cluster details" />));
    const text = collectReviewSurfaceText(document.body);
    expect(text).toMatch(/\bcluster\b/i);
  });

  it.each([
    ['ClusterLabelingPanel default', 'default'],
    ['ClusterLabelingPanel error', 'error'],
    ['NameFaceControl suggestions-open', 'suggestions-open'],
    ['ClusterEditForm default', 'edit-default'],
    ['PersonCommitControl loading', 'commit-loading'],
    ['PersonCommitControl error', 'commit-error'],
    ['PersonCommitControl pending', 'commit-pending'],
    ['SuggestionCards default', 'suggestion-default'],
    ['TopClusterCard default', 'top-default'],
    ['ReviewQueue empty', 'queue-empty'],
    ['ReviewQueue pending', 'queue-pending'],
    ['merge-undo-banner', 'merge-undo-banner'],
    ['cluster-actions', 'cluster-actions'],
    ['identity-cluster-item', 'identity-cluster-item'],
  ] as const)('%s has no banned review vocabulary', async (_label, state) => {
    const naming = await import('../pages/workbench/identity-clusters/NameFaceControl');
    const edit = await import('../pages/workbench/identity-clusters/ClusterEditForm');
    const labeling = await import('../pages/workbench/identity-clusters/ClusterLabelingPanel');
    const commit = await import('../pages/workbench/identity-clusters/PersonCommitControl');
    const cards = await import('../pages/workbench/identity-clusters/SuggestionCards');
    const top = await import('../pages/workbench/identity-clusters/TopClusterCard');
    const queue = await import('../pages/workbench/identity-clusters/ReviewQueue');
    const undo = await import('../pages/workbench/identity-clusters/MergeUndoBanner');
    const survivors = await import('../pages/workbench/identity-clusters/MergeSurvivorContext');
    const showAll = await import('../pages/workbench/identity-clusters/useShowAllClusterMembers');
    const actions = await import('../pages/workbench/identity-clusters/ClusterActions');
    const clusterItem = await import('../pages/workbench/identity-clusters/IdentityClusterItem');
    const recognition = await import('../api/recognition');
    const roster = await import('../api/rosterApi');

    if (state === 'queue-empty') {
      const emptySuggestions = {
        suggestions: [],
        limit: 10,
        offset: 0,
        data_source: DATA_SOURCE.BACKEND_PROXY,
      };
      vi.mocked(recognition.fetchPendingSuggestions).mockResolvedValue(emptySuggestions);
      vi.mocked(recognition.fetchPendingMergeSuggestions).mockResolvedValue(emptySuggestions);
      vi.mocked(recognition.fetchPendingNameSuggestions).mockResolvedValue({
        suggestions: [],
        limit: 25,
        offset: 0,
        data_source: DATA_SOURCE.BACKEND_PROXY,
      });
      vi.mocked(recognition.fetchTopUnlabeledClusters).mockResolvedValue({
        clusters: [],
        limit: 20,
        total: 0,
        truncated: false,
        singleton_count: 0,
        data_source: DATA_SOURCE.BACKEND_PROXY,
      });
    }

    if (state === 'queue-pending') {
      const hang = () => new Promise<never>(() => undefined);
      vi.mocked(recognition.fetchPendingSuggestions).mockImplementation(hang);
      vi.mocked(recognition.fetchPendingMergeSuggestions).mockImplementation(hang);
      vi.mocked(recognition.fetchPendingNameSuggestions).mockImplementation(hang);
      vi.mocked(recognition.fetchTopUnlabeledClusters).mockImplementation(hang);
    }

    if (state === 'error') {
      // Persist across remounts — mockReturnValueOnce is consumed by the first hook call.
      vi.mocked(showAll.useShowAllClusterMembers).mockReturnValue({
        members: [],
        isLoading: false,
        isError: true,
        truncated: false,
        total: 0,
        isFullyLoaded: true,
        isExpanding: false,
        expandError: null,
        showAll: vi.fn(),
        refetch: vi.fn(),
      } as unknown as ReturnType<typeof showAll.useShowAllClusterMembers>);
    }

    if (state === 'commit-loading') {
      vi.mocked(roster.listRosterEntries).mockImplementation(() => new Promise(() => undefined));
    } else {
      vi.mocked(roster.listRosterEntries).mockResolvedValue([]);
    }

    const option = { value: 'person:1', label: 'Ada', source: 'person' as const, group: 'All Labels' };

    const node =
      state === 'default' ? (
        <labeling.ClusterLabelingPanel clusterId="c1" onClose={() => undefined} onLabel={() => undefined} />
      ) : state === 'error' ? (
        <labeling.ClusterLabelingPanel clusterId="c1" onClose={() => undefined} onLabel={() => undefined} />
      ) : state === 'suggestions-open' ? (
        <naming.NameFaceControl
          options={[option, { ...option, value: 'person:2', label: 'Grace' }]}
          value="a"
          onValueChange={() => undefined}
          onCommit={() => undefined}
          commitLabel="Save name"
          ariaLabel="Name this person"
        />
      ) : state === 'edit-default' ? (
        <edit.ClusterEditForm
          labelInput="Ada"
          onLabelChange={() => undefined}
          options={[option]}
          isLoading={false}
          isPending={false}
          onSave={() => undefined}
          onCancel={() => undefined}
        />
      ) : state === 'commit-loading' ? (
        <commit.PersonCommitControl
          clusterId="c1"
          phase="idle"
          errorMessage={null}
          onCommit={() => undefined}
          onRetry={() => undefined}
        />
      ) : state === 'commit-error' ? (
        <commit.PersonCommitControl
          clusterId="c1"
          phase="failed"
          errorMessage="Could not save the name. Retry to try again."
          onCommit={() => undefined}
          onRetry={() => undefined}
        />
      ) : state === 'commit-pending' ? (
        <commit.PersonCommitControl
          clusterId="c1"
          phase="committing"
          errorMessage={null}
          onCommit={() => undefined}
          onRetry={() => undefined}
        />
      ) : state === 'queue-empty' || state === 'queue-pending' ? (
        <survivors.MergeSurvivorProvider>
          <queue.ReviewQueue
            index={0}
            onClampIndex={() => undefined}
            onStepIndex={() => undefined}
            kind="all"
            onKindChange={() => undefined}
            band="all"
            onBandChange={() => undefined}
            onClearFilters={() => undefined}
            selectedIds={new Set()}
            onSelectedIdsChange={() => undefined}
          />
        </survivors.MergeSurvivorProvider>
      ) : state === 'merge-undo-banner' ? (
        <undo.MergeUndoBanner
          mergeResult={{
            source_id: 's1',
            source_label: null,
            target_id: 't1',
            target_label: null,
            identities_moved: 1,
            moved_identity_ids: ['i1'],
            target_identity_count: 2,
          }}
          isReverting={false}
          onUndo={() => undefined}
        />
      ) : state === 'cluster-actions' ? (
        <actions.ClusterActions
          canEdit
          canSearchForMatch={false}
          hasLabel
          isAutoLabel={false}
          canSplit
          isPending={false}
          onEdit={() => undefined}
          onWrongPerson={() => undefined}
          onSplit={() => undefined}
        />
      ) : state === 'identity-cluster-item' ? (
        <>
          <clusterItem.IdentityClusterItem
            cluster={{
              key: 'singleton',
              clusterId: null,
              label: null,
              isAutoLabel: false,
              clusteringPending: false,
              members: [
                {
                  identity_id: 'id-unlabeled',
                  representative_id: 'rep-unlabeled',
                  media_id: 1,
                  cluster_id: null,
                  cluster_label: null,
                  is_auto_label: false,
                  is_pinned: false,
                  bbox: { x: 0, y: 0, width: 1, height: 1 },
                  confidence: 1,
                  similarity: 1,
                  detected_at: '',
                },
              ],
            }}
            canLabel
            canMutate
          />
          <clusterItem.IdentityClusterItem
            cluster={{
              key: 'editable',
              clusterId: 'editable',
              label: 'bob',
              isAutoLabel: false,
              clusteringPending: false,
              members: [
                {
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
                },
              ],
            }}
            canLabel
            canMutate
          />
        </>
      ) : state === 'suggestion-default' ? (
        <cards.SuggestionCard
          suggestion={{
            suggestionId: 's1',
            identityId: 'i1',
            clusterId: 'c1',
            label: 'Ada',
            similarity: 0.9,
            identityCount: 3,
          }}
          onAccept={() => undefined}
          onReject={() => undefined}
          onReview={() => undefined}
          isPending={false}
          lowConfidenceThreshold={0.5}
        />
      ) : (
        <top.TopClusterCard
          cluster={{
            id: 'c1',
            tenant_id: 't1',
            label: null,
            is_labeled: false,
            is_auto_label: false,
            identity_count: 3,
            user_confirmed: false,
            suggested_label: null,
            suggested_label_source: null,
            suggested_label_confidence: null,
            suggested_target_cluster_id: null,
            representatives: [],
          }}
          onLabel={() => undefined}
          onDismiss={() => undefined}
        />
      );

    const { container } = render(wrap(node));
    if (state === 'default') {
      expect(container.querySelector('[data-testid="acx-cluster-members-error"]')).toBeNull();
      expect(container.textContent).toMatch(/Name this person/i);
    }
    if (state === 'error') {
      expect(
        container.querySelector('[data-testid="acx-cluster-members-error"]'),
        'error fixture must enter the members-error state',
      ).toBeTruthy();
      expect(container.textContent).toMatch(/Unable to load these faces/i);
    }
    if (state === 'commit-loading') {
      await waitFor(() => {
        expect(container.textContent).toMatch(/Loading people/i);
      });
    }
    if (state === 'identity-cluster-item') {
      const remove = Array.from(document.body.querySelectorAll('button')).find(
        (button) => button.textContent === 'Remove from group',
      );
      expect(remove, 'identity-cluster-item fixture must render the remove control').toBeTruthy();
      fireEvent.click(remove as HTMLButtonElement);
    }
    if (state === 'queue-empty') {
      await waitFor(() => {
        expect(container.querySelector('.acx-review-queue__empty')).toBeTruthy();
        expect(container.textContent).toMatch(/no .*review/i);
      });
    }
    if (state === 'queue-pending') {
      expect(
        container.querySelector('.acx-review-queue--loading'),
        'queue-pending fixture must enter the loading branch',
      ).toBeTruthy();
      expect(container.textContent).toMatch(/Loading review queue/i);
    }
    assertNoBannedReviewWords(document.body);
  });

  it('ReviewQueue source does not say unlabeled clusters (UXW2-3-R2-06 mutant)', () => {
    const here = path.dirname(fileURLToPath(import.meta.url));
    const source = readFileSync(
      path.resolve(here, '../pages/workbench/identity-clusters/ReviewQueue.tsx'),
      'utf8',
    );
    expect(source).toContain('Unable to load unlabeled faces.');
    expect(source).not.toMatch(/Unable to load unlabeled clusters\./);
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

  it('workbench-2pane operator-visible copy has no retired vocabulary (UXW2-3-R3-23)', () => {
    const here = path.dirname(fileURLToPath(import.meta.url));
    const mapPath = path.resolve(here, '../../../docs/ux-maps/workbench-2pane.uxmap.json');
    const map = JSON.parse(readFileSync(mapPath, 'utf8')) as Record<string, unknown>;
    const copy = collectUxMapOperatorCopy(map);
    expect(copy.length).toBeGreaterThan(0);

    for (const text of copy) {
      for (const pattern of UXMAP_RETIRED_WORDS) {
        expect(text, text).not.toMatch(pattern);
      }
    }

    const openQuestions = map.open_questions;
    const notDoing = map.not_doing;
    expect(Array.isArray(openQuestions) ? openQuestions.join(' ') : '').toMatch(/\bcluster\b/i);
    expect(Array.isArray(notDoing) ? notDoing.join(' ') : '').toMatch(/\bcluster/i);
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
