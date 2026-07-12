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
  useAuditEvents: () => createMockQuery({ data: { events: [] } }),
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
      local_url: 'http://localhost:8000',
      local_url_source: 'default',
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

// Workbench pulls a large context — stub the provider surface via WorkbenchPage deps.
vi.mock('../pages/workbench/WorkbenchContext', async () => {
  const React = await import('react');
  const actual = await vi.importActual<typeof import('../pages/workbench/WorkbenchContext')>(
    '../pages/workbench/WorkbenchContext',
  );
  const stub = {
    activeTab: 'scan',
    setActiveTab: vi.fn(),
    pipelinePhase: 'idle',
    projectionSyncState: 'idle',
    projectionError: null,
    retryProjection: vi.fn(),
    scanProgress: null,
    clusterProgress: null,
    isScanning: false,
    isCancelling: false,
    statusText: null,
    jobId: null,
    errorMessage: null,
    progress: null,
    batchRunStatus: null,
    stallSeconds: null,
    etaSeconds: null,
    isSynced: false,
    onCancelScan: undefined,
    onRetryStream: undefined,
    mediaSelection: { selectedIds: [], toggle: vi.fn(), clear: vi.fn() },
    bulkDescribe: { progress: { run: null, status: null, isTerminal: true, isError: false } },
    notice: null,
    detailTruncationNotice: null,
  };
  return {
    ...actual,
    WorkbenchProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
    useWorkbench: () => stub,
  };
});

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
  DescriptionHistoryPage: () => (
    <MemoryRouter initialEntries={['/description-history']}>
      <Routes>
        <Route path="/description-history" element={<DescriptionHistoryPage />} />
      </Routes>
    </MemoryRouter>
  ),
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
      <MemoryRouter>{node}</MemoryRouter>
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
});
