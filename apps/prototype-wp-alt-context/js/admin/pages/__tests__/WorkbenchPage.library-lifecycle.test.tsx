import React from 'react';
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, useLocation } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { WorkbenchPage } from '../WorkbenchPage';
import type { UseActivityStatusParams, UseActivityStatusResult } from '../../hooks/useActivityStatus';

/**
 * UXREC-1 WB_CONTROL gate 1 regressions (findings 19874 / 19876).
 *
 * Real WorkbenchPage, ScanTabContent, ScanActionPanel, ActivityStatusStrip,
 * FaceGroupScatter, WorkbenchTwoPaneLayout and usePanesParam. Only data hooks and
 * unrelated review subtrees are stubbed. MediaSelection is replaced by a stub of the
 * frozen ACTION_PROGRESS slot contract (optional `activityStatus` node rendered once
 * inside the Library action group); the real joined slot is proven in the browser runner.
 */

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
  _n: (single: string, plural: string, count: number) => (count === 1 ? single : plural),
  sprintf: (format: string, ...args: (string | number)[]) => {
    let index = 0;
    return format.replace(/%(\d+\$)?[sd]/g, () => String(args[index++]));
  },
}));

const { pipeline, activity, findings } = vi.hoisted(() => ({
  pipeline: {
    scanRun: {
      isScanning: false,
      isSynced: false,
      statusText: undefined as string | undefined,
      errorMessage: null as string | null,
      jobId: null as string | null,
      progress: undefined as { completed: number; total: number; clusters_created?: number } | undefined,
      batchRunStatus: null,
    },
    status: {
      isOnline: true,
      projectionSyncState: 'idle',
      projectionError: null as string | null,
      currentPhase: 'idle',
      scanProgress: null,
      clusterProgress: null,
    },
    history: { activeJobIds: [] as string[], jobId: null as string | null },
    cancelScan: vi.fn(),
    retryScanStream: vi.fn(),
    retryProjectionSync: vi.fn(),
  },
  activity: {
    current: null as unknown as UseActivityStatusResult,
    params: [] as UseActivityStatusParams[],
  },
  findings: { hasFindings: false },
}));

vi.mock('../workbench/WorkbenchContext', () => ({
  WorkbenchProvider: ({ children }: { children: React.ReactNode }) => children,
}));

vi.mock('../workbench/WorkbenchNavContext', () => ({
  useWorkbenchNav: () => ({
    activeSection: 'scan',
    recognitionSource: 'hosted',
    effectiveTargetUrl: '',
    activeOverlay: null,
    setActiveOverlay: vi.fn(),
    isAdvancedOpen: false,
    setAdvancedOpen: vi.fn(),
  }),
}));

vi.mock('../workbench/ClusterPanelContext', () => ({
  useClusterPanel: () => ({ clusterPanel: { mode: 'none', clusterId: null }, dispatchClusterPanel: vi.fn() }),
}));

vi.mock('../workbench/JobPipelineContext', () => ({
  useJobPipeline: () => pipeline,
}));

vi.mock('../workbench/WorkbenchMediaContext', () => ({
  useWorkbenchMediaContext: () => ({ mediaQueue: { detailTruncationNotice: null, hasIdentities: true } }),
}));

vi.mock('../workbench/ReviewSurfaceContext', () => ({
  useReviewSurface: () => ({ cardPrimaryPresent: false, setCardPrimaryPresent: vi.fn() }),
}));

// Frozen ACTION_PROGRESS contract: MediaSelection renders the supplied node once in its action group.
vi.mock('../workbench/MediaSelection', () => ({
  MediaSelection: ({ activityStatus }: { activityStatus?: React.ReactNode }) => (
    <div className="acx-media-selection" data-testid="media-selection-contract">
      <input id="acx-media-search" type="search" aria-label="Search media" />
      <section aria-label="Selected media actions">{activityStatus}</section>
    </div>
  ),
}));

vi.mock('../../hooks/useActivityStatus', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../hooks/useActivityStatus')>()),
  useActivityStatus: (params: UseActivityStatusParams) => {
    activity.params.push(params);
    return activity.current;
  },
}));

vi.mock('../workbench/RecognitionPolicyControl', () => ({
  RecognitionPolicyControl: () => <fieldset aria-label="Facial recognition" />,
}));
vi.mock('../workbench/AdvancedDrawer', () => ({ AdvancedDrawer: () => null }));
vi.mock('../workbench/ConflictInbox', () => ({ ConflictInbox: () => null }));
vi.mock('../workbench/DeadLetterPanel', () => ({ DeadLetterPanel: () => null }));
vi.mock('../workbench/SyncStatusIndicator', () => ({ SyncStatusIndicator: () => null }));
vi.mock('../workbench/JobTimeline', () => ({
  JobTimeline: ({ compact }: { compact?: boolean }) => (
    <div data-testid={compact ? 'job-timeline-compact' : 'job-timeline'} />
  ),
}));
vi.mock('../../hooks/useScrollRestoration', () => ({ useScrollRestoration: () => undefined }));
vi.mock('../../hooks/useWorkbenchFilters', () => ({
  QUEUE_ACTION: {},
  useWorkbenchFilters: () => ({ queueState: { index: 0, kind: 'all', band: 'all' }, dispatchQueue: vi.fn() }),
}));
vi.mock('../workbench/identity-clusters', () => ({
  ClusterLabelingPanel: () => null,
  ClusterReviewPanel: () => null,
  ReviewQueue: React.forwardRef(function ReviewQueueStub() {
    return <h3 id="acx-workbench-queue-heading">Review Suggestions</h3>;
  }),
  WorkbenchFindingsPanel: () => <h3 id="acx-workbench-findings-heading">Recognition findings</h3>,
}));
vi.mock('../workbench/identity-clusters/useOpenReviewTargetLifecycle', () => ({
  useOpenReviewTargetLifecycle: () => ({ reviewClusterId: null }),
}));
vi.mock('../workbench/identity-clusters/useWorkbenchFindings', () => ({
  useWorkbenchFindings: () => ({
    hasFindings: findings.hasFindings,
    repairPending: false,
    isReadOnly: false,
    queueSettled: true,
    isUnavailable: false,
    isError: false,
    isAssignmentError: false,
    isTopUnlabeledError: false,
  }),
}));
vi.mock('../workbench/identity-clusters/useSuggestionReviewQueries', () => ({
  useSuggestionReviewQueries: () => ({
    assignmentQuery: { isSuccess: true },
    mergeQuery: { isSuccess: true },
    nameQuery: { isSuccess: true },
    topUnlabeledQuery: { isSuccess: true },
  }),
}));

const RUN_ID = 'bbbbbbbb-cccc-4ddd-8eee-ffffffffffff';

type Kind = 'idle' | 'scanning' | 'warming' | 'describing' | 'done' | 'failed';

const activityFor = (
  kind: Kind,
  overrides: Partial<UseActivityStatusResult['actions']> = {},
  reason: string | null = null,
): UseActivityStatusResult => ({
  status: {
    kind,
    progress: kind === 'describing' ? 0.4 : null,
    etaSeconds: null,
    reason,
    canCancel: overrides.onCancel != null,
    runId: kind === 'idle' ? null : RUN_ID,
    gpuState: 'ready',
    retryable: overrides.onRetry != null,
    draftCount: kind === 'done' ? 10 : 0,
  },
  actions: { onCancel: null, onRetry: null, reviewDraftsHref: null, backToRunHref: null, ...overrides },
  isCancelling: false,
});

const resetPipeline = (): void => {
  pipeline.scanRun.isScanning = false;
  pipeline.scanRun.isSynced = false;
  pipeline.scanRun.statusText = undefined;
  pipeline.scanRun.errorMessage = null;
  pipeline.scanRun.jobId = null;
  pipeline.scanRun.progress = undefined;
  pipeline.status.isOnline = true;
  pipeline.status.projectionSyncState = 'idle';
  pipeline.status.currentPhase = 'idle';
  pipeline.history.activeJobIds = [];
  pipeline.history.jobId = null;
  pipeline.cancelScan.mockReset();
  pipeline.retryScanStream.mockReset();
  activity.params = [];
  findings.hasFindings = false;
};

const LocationProbe = (): React.JSX.Element => {
  const location = useLocation();
  return <output data-testid="location-search">{location.search}</output>;
};

const renderWorkbench = (entry = '/workbench') =>
  render(
    <MemoryRouter initialEntries={[entry]}>
      <WorkbenchPage />
      <LocationProbe />
    </MemoryRouter>,
  );

const library = (): HTMLElement => screen.getByTestId('workbench-two-pane-library');
const control = (): HTMLElement => screen.getByTestId('workbench-two-pane-control');
const strips = (): HTMLElement[] => Array.from(document.querySelectorAll<HTMLElement>('.acx-activity-status-strip'));

const expectOneLibraryStatus = (): HTMLElement => {
  expect(strips(), 'exactly one shared run status is mounted').toHaveLength(1);
  const [strip] = strips();
  expect(
    within(screen.getByTestId('media-selection-contract')).getByRole('region', { name: 'Selected media actions' }),
    'status sits in the Library action group',
  ).toContainElement(strip);
  expect(control(), 'Control no longer hosts run status').not.toContainElement(strip);
  expect(strip.closest('[hidden]'), 'status is never inside a hidden ancestor').toBeNull();
  expect(strip).toBeVisible();
  return strip;
};

/**
 * Browsers do not focus an input inside a `hidden` subtree (it is not being rendered);
 * jsdom does. Mirror the browser so focus-before-visibility-commit is observable here.
 * Shadowing only the input prototype leaves user-event's HTMLElement focus patch intact.
 */
const installRenderedFocusGuard = (): void => {
  Object.defineProperty(HTMLInputElement.prototype, 'focus', {
    configurable: true,
    writable: true,
    value(this: HTMLInputElement, options?: FocusOptions) {
      if (this.closest('[hidden]')) {
        return;
      }
      HTMLElement.prototype.focus.call(this, options);
    },
  });
};
const removeRenderedFocusGuard = (): void => {
  Reflect.deleteProperty(HTMLInputElement.prototype, 'focus');
};

describe('UXREC-1 WB_CONTROL Library lifecycle composition', () => {
  beforeEach(() => {
    resetPipeline();
    activity.current = activityFor('idle');
    installRenderedFocusGuard();
    window.matchMedia = vi.fn().mockImplementation((query: string) => ({
      matches: false,
      media: query,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    }));
  });

  afterEach(() => {
    removeRenderedFocusGuard();
    cleanup();
  });

  describe('description-only lifecycle while recognition is idle (finding 19874)', () => {
    it('keeps queued/describing status and Cancel visible once in Library', () => {
      const onCancel = vi.fn();
      activity.current = activityFor('describing', { onCancel, backToRunHref: '#/workbench' });
      renderWorkbench();

      const strip = expectOneLibraryStatus();
      const cancel = within(strip).getByRole('button', { name: 'Cancel run' });
      expect(cancel).toBeVisible();
      expect(screen.getAllByRole('button', { name: 'Cancel run' })).toHaveLength(1);
    });

    it('keeps warming status and Cancel visible once in Library', () => {
      activity.current = activityFor('warming', { onCancel: vi.fn() });
      renderWorkbench();

      const strip = expectOneLibraryStatus();
      expect(strip).toHaveAttribute('data-activity-kind', 'warming');
      expect(within(strip).getByRole('button', { name: 'Cancel run' })).toBeVisible();
    });

    it('keeps a poll error recoverable with Retry and Cancel in Library', async () => {
      const onRetry = vi.fn();
      activity.current = activityFor('failed', { onRetry, onCancel: vi.fn() }, 'describe_poll_error');
      renderWorkbench();

      const strip = expectOneLibraryStatus();
      await userEvent.click(within(strip).getByRole('button', { name: 'Retry' }));
      expect(onRetry).toHaveBeenCalledOnce();
      expect(within(strip).getByRole('button', { name: 'Cancel run' })).toBeVisible();
    });

    it('keeps the terminal Review drafts link visible in Library', () => {
      const href = `#/workbench?has_draft=1&run=${RUN_ID}`;
      activity.current = activityFor('done', { reviewDraftsHref: href });
      renderWorkbench();

      const strip = expectOneLibraryStatus();
      expect(within(strip).getByRole('link', { name: 'Review 10 drafts' })).toHaveAttribute('href', href);
    });

    it('keeps idle status in Library and still collapses idle recognition scan chrome', () => {
      renderWorkbench();

      expectOneLibraryStatus();
      const scanSection = control().querySelector('.acx-workbench-control-scan');
      expect(scanSection).not.toBeNull();
      expect(scanSection).not.toBeVisible();
    });
  });

  describe('recognition activity keeps its Control evidence (no duplicate status)', () => {
    it('moves the single active strip to Library and keeps the compact recognition timeline in Control', () => {
      pipeline.scanRun.isScanning = true;
      pipeline.scanRun.jobId = 'job-1';
      pipeline.history.activeJobIds = ['job-1'];
      pipeline.status.currentPhase = 'scanning';
      const onCancel = vi.fn();
      activity.current = activityFor('scanning', { onCancel });
      renderWorkbench();

      const strip = expectOneLibraryStatus();
      expect(within(strip).getByRole('button', { name: 'Cancel run' })).toBeVisible();
      expect(within(control()).getByTestId('active-job-strip')).toBeVisible();
      expect(within(control()).getByTestId('job-timeline-compact')).toBeVisible();
    });

    it('feeds the Library status the existing scan source and cancels the active recognition jobs', () => {
      pipeline.scanRun.isScanning = true;
      pipeline.scanRun.jobId = 'job-2';
      pipeline.history.activeJobIds = ['job-1', 'job-2'];
      pipeline.status.currentPhase = 'scanning';
      activity.current = activityFor('scanning', { onCancel: vi.fn() });
      renderWorkbench();

      expectOneLibraryStatus();
      const scan = activity.params.at(-1)?.scan;
      expect(scan).toMatchObject({ isScanning: true, jobId: 'job-2' });
      scan?.retryScan?.();
      expect(pipeline.retryScanStream).toHaveBeenCalledOnce();
      scan?.cancelScan?.();
      expect(pipeline.cancelScan).toHaveBeenCalledWith(['job-1', 'job-2']);
    });

    it('keeps a recognition failure and its alert visible in Control', () => {
      pipeline.scanRun.errorMessage = 'Recognition failed';
      activity.current = activityFor('failed', { onRetry: vi.fn() }, 'scan_failed');
      renderWorkbench();

      expectOneLibraryStatus();
      const alert = within(control()).getByRole('alert');
      expect(alert).toHaveTextContent('Recognition failed');
      expect(alert).toBeVisible();
    });

    it('keeps nonempty review evidence visible', () => {
      findings.hasFindings = true;
      renderWorkbench();

      expect(within(control()).getByRole('heading', { name: 'Review Suggestions' })).toBeVisible();
      expect(within(control()).getByRole('heading', { name: 'Recognition findings' })).toBeVisible();
    });
  });

  describe('empty next step reopens Library before focusing search (finding 19876)', () => {
    it('pointer activation opens a collapsed Library through ?panes= and focuses its real search after commit', async () => {
      renderWorkbench('/workbench?panes=library-collapsed');
      expect(library()).not.toBeVisible();

      await userEvent.click(within(control()).getByRole('link', { name: 'Go to Scan' }));

      await waitFor(() => expect(library()).toBeVisible());
      expect(screen.getByTestId('location-search').textContent).not.toContain('panes=');
      await waitFor(() => expect(screen.getByRole('searchbox', { name: 'Search media' })).toHaveFocus());
    });

    it('keyboard activation opens a collapsed Library and focuses its search', async () => {
      const user = userEvent.setup();
      renderWorkbench('/workbench?panes=library-collapsed');

      within(control()).getByRole('link', { name: 'Go to Scan' }).focus();
      await user.keyboard('{Enter}');

      await waitFor(() => expect(library()).toBeVisible());
      await waitFor(() => expect(screen.getByRole('searchbox', { name: 'Search media' })).toHaveFocus());
    });

    it('focuses the visible search directly when Library is already open', async () => {
      renderWorkbench();

      await userEvent.click(within(control()).getByRole('link', { name: 'Go to Scan' }));

      expect(screen.getByRole('searchbox', { name: 'Search media' })).toHaveFocus();
    });

    it('leaves modifier activation to the link route without touching panes', () => {
      renderWorkbench('/workbench?panes=library-collapsed');
      const link = within(control()).getByRole('link', { name: 'Go to Scan' });

      const notCancelled = fireEvent.click(link, { ctrlKey: true });

      expect(notCancelled).toBe(true);
      expect(screen.getByTestId('location-search').textContent).toContain('panes=library-collapsed');
      expect(library()).not.toBeVisible();
    });

    it('does not steal focus on a later pane change after the request completed', async () => {
      renderWorkbench('/workbench?panes=library-collapsed');
      await userEvent.click(within(control()).getByRole('link', { name: 'Go to Scan' }));
      await waitFor(() => expect(screen.getByRole('searchbox', { name: 'Search media' })).toHaveFocus());

      const splitter = screen.getByRole('separator');
      const shell = screen.getByTestId('workbench-two-pane');
      act(() => splitter.focus());
      // Collapse then reopen Library through the existing splitter (Enter cycles panes).
      for (const next of ['control-collapsed', 'library-collapsed', 'both']) {
        await userEvent.keyboard('{Enter}');
        await waitFor(() => expect(shell).toHaveAttribute('data-panes', next));
      }

      expect(library()).toBeVisible();
      expect(splitter).toHaveFocus();
    });
  });
});
