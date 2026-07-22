/**
 * Banned-vocabulary sweep over every js/admin page surface.
 *
 * Enumerates page modules from the pages/ directory so a new page that is
 * missing from PAGE_SWEEP fails CI. Representative fixtures only — if jargon
 * is injected into a page module under those fixtures, this test fails.
 */
import { readdirSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { createMockMutation, createMockQuery } from '../test-utils/mockHooks';

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
vi.mock('../pages/workbench/WorkbenchMediaContext', () => {
  const stub = {
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
      perPage: 20,
      handleSearchChange: vi.fn(),
      handleStatusChange: vi.fn(),
      setCurrentPage: vi.fn(),
      setPerPage: vi.fn(),
    },
    mediaQueue: {
      mediaQuery: {
        data: { items: [], total: 0 },
        itemsWithIdentities: [],
        isPending: false,
        isError: false,
        error: null,
        refetch: vi.fn(),
      },
      statusMessage: '',
      detailTruncationNotice: null,
      hasIdentities: false,
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

const collectVisibleText = (container: HTMLElement): string => container.textContent ?? '';

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
      (value) => typeof value === 'string',
    ) as string[];
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
});
