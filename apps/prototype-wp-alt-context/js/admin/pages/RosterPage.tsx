import React from 'react';
import { __, sprintf } from '@wordpress/i18n';
import { useSearchParams } from 'react-router-dom';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '../../components/ui/tabs';
import type { ClusterIdentity, ClusterSummary } from '../api/recognition';
import type { RosterEntry } from '../api/rosterApi';
import { useRecognitionCluster, useRecognitionClusters } from '../hooks/useRecognitionHooks';
import { useRosterEntries } from '../hooks/useRosterHooks';
import { useClusterSelection } from '../hooks/useClusterSelection';
import { useClusterMediaMap } from './roster/hooks/useClusterMediaMap';
import { useClusterDragDrop } from './roster/hooks/useClusterDragDrop';
import { useClusterActions } from './roster/hooks/useClusterActions';
import { ClusterGrid } from './roster/ClusterGrid';
import { BulkActionBar } from './roster/BulkActionBar';
import { ClusterDrawerPanel } from './roster/ClusterDrawerPanel';
import { RosterEntriesSection } from './roster/RosterEntriesSection';
import { Checkbox } from '../../components/ui/checkbox';
import { ConfirmDialog } from './roster/ConfirmDialog';

const ROSTER_TABS = {
  entries: { id: 'entries' as const, label: __('Entries', 'alt-context') },
  clusters: { id: 'clusters' as const, label: __('Clusters', 'alt-context') },
} as const;

type RosterTab = (typeof ROSTER_TABS)[keyof typeof ROSTER_TABS]['id'];

const ROSTER_ROUTE_PARAM_KEYS = ['person', 'queue', 'face', 'cluster'] as const;

interface ParsedRosterRoute {
  activeTab: RosterTab;
  selectedClusterId: string | null;
  requiresProjectionGateNotice: boolean;
}

type ProjectionStatus = RosterEntry['projection_status'];

const PROJECTION_STATUSES = new Set<ProjectionStatus>(['current', 'refreshing', 'stale', 'failed']);

const getRouteParam = (searchParams: URLSearchParams, key: string): string | null => {
  const value = searchParams.get(key)?.trim();
  if (!value) {
    return null;
  }

  return value;
};

// Tolerate fixtures and legacy callers that omit the canonical RCL-004 fields by treating
// missing/non-string values as 'no projection'. Strict typecheck handles new code paths.
const getEntryProjectionStatus = (entry: RosterEntry): ProjectionStatus | null => {
  const raw: unknown = entry.projection_status;
  if (typeof raw !== 'string') {
    return null;
  }
  return PROJECTION_STATUSES.has(raw as ProjectionStatus) ? (raw as ProjectionStatus) : null;
};

const getEntryPersonUuid = (entry: RosterEntry): string | null => {
  const raw: unknown = entry.person_uuid;
  return typeof raw === 'string' && raw.length > 0 ? raw : null;
};

const getLegacyTab = (searchParams: URLSearchParams): RosterTab => {
  const rawTab = getRouteParam(searchParams, 'tab');
  return rawTab === ROSTER_TABS.clusters.id ? ROSTER_TABS.clusters.id : ROSTER_TABS.entries.id;
};

const parseRosterRoute = (searchParams: URLSearchParams): ParsedRosterRoute => {
  if (getRouteParam(searchParams, 'person')) {
    return {
      activeTab: ROSTER_TABS.entries.id,
      selectedClusterId: null,
      requiresProjectionGateNotice: true,
    };
  }

  if (getRouteParam(searchParams, 'queue')) {
    return {
      activeTab: ROSTER_TABS.entries.id,
      selectedClusterId: null,
      requiresProjectionGateNotice: true,
    };
  }

  const clusterId = getRouteParam(searchParams, 'cluster');
  if (clusterId) {
    return {
      activeTab: ROSTER_TABS.clusters.id,
      selectedClusterId: clusterId,
      requiresProjectionGateNotice: false,
    };
  }

  return {
    activeTab: getLegacyTab(searchParams),
    selectedClusterId: null,
    requiresProjectionGateNotice: false,
  };
};

const hasCanonicalProjectionShape = (entries: readonly RosterEntry[]): boolean =>
  entries.some((entry) => getEntryPersonUuid(entry) !== null && getEntryProjectionStatus(entry) !== null);

const PROJECTION_PRIORITY: Record<ProjectionStatus, number> = {
  failed: 3,
  stale: 2,
  refreshing: 1,
  current: 0,
};

const aggregateProjectionStatus = (entries: readonly RosterEntry[]): ProjectionStatus | null => {
  let aggregate: ProjectionStatus | null = null;
  for (const entry of entries) {
    const status = getEntryProjectionStatus(entry);
    if (status === null) {
      continue;
    }
    if (aggregate === null || PROJECTION_PRIORITY[status] > PROJECTION_PRIORITY[aggregate]) {
      aggregate = status;
    }
  }
  return aggregate;
};

const PERSON_WORKSPACE_GATE_NOTICE = __(
  'This route is recognized, but the person workspace stays on the legacy Entries view until enriched roster projection data lands.',
  'alt-context',
);

const PROJECTION_REFRESHING_NOTICE = __(
  'Roster projection is refreshing. Retry once the refresh completes.',
  'alt-context',
);

const PROJECTION_STALE_NOTICE = __(
  'Roster projection is stale. Person workspace will resume after the next refresh.',
  'alt-context',
);

const PROJECTION_FAILED_NOTICE = __(
  'Roster projection failed to refresh. Person workspace is unavailable until the projection recovers.',
  'alt-context',
);

const PERSON_ROUTE_UNMATCHED_NOTICE = __(
  'No roster entry matches this person route yet. The workspace will appear once a matching projection row is available.',
  'alt-context',
);

export const RosterPage = (): React.JSX.Element => {
  const [searchParams, setSearchParams] = useSearchParams();
  const [selectedClusterId, setSelectedClusterId] = React.useState<string | null>(null);
  const [confirmAction, setConfirmAction] = React.useState<'merge' | 'dismiss' | null>(null);

  const selection = useClusterSelection();
  const clearSelection = selection.clear;
  const retainVisibleSelection = selection.retainVisible;
  const isClusterSelected = selection.isSelected;
  const areAllVisibleClustersSelected = selection.isAllSelected;

  const clustersQuery = useRecognitionClusters({ limit: 20 });
  const clusterList = clustersQuery.data;
  const clusters = React.useMemo(() => clusterList?.clusters ?? [], [clusterList]);
  const clusterIds = React.useMemo(() => clusters.map((cluster) => cluster.id), [clusters]);
  const parsedRoute = React.useMemo(() => parseRosterRoute(searchParams), [searchParams]);
  const activeTab = parsedRoute.activeTab;

  // Clear selection when switching tabs to avoid stale state
  React.useEffect(() => {
    clearSelection();
  }, [activeTab, clearSelection]);

  React.useEffect(() => {
    if (activeTab !== ROSTER_TABS.clusters.id || clustersQuery.data === undefined) {
      return;
    }

    retainVisibleSelection(clusterIds);
  }, [activeTab, clusterIds, clustersQuery.data, retainVisibleSelection]);

  React.useEffect(() => {
    setSelectedClusterId(parsedRoute.selectedClusterId);
  }, [parsedRoute.selectedClusterId]);

  const selectedCluster = React.useMemo(
    () => clusters.find((cluster) => cluster.id === selectedClusterId) ?? null,
    [clusters, selectedClusterId],
  );
  const clusterDetailQuery = useRecognitionCluster(selectedClusterId, Boolean(selectedClusterId));
  const drawerIdentities = React.useMemo(
    () => clusterDetailQuery.data?.sample_identities ?? selectedCluster?.sample_identities ?? [],
    [clusterDetailQuery.data, selectedCluster],
  );
  const drawerMediaIds = React.useMemo(
    () => Array.from(new Set(drawerIdentities.map((identity) => identity.media_id))),
    [drawerIdentities],
  );
  const mediaMap = useClusterMediaMap(clusters, drawerMediaIds);
  const entriesQuery = useRosterEntries();
  const rosterEntries = React.useMemo(() => entriesQuery.data ?? [], [entriesQuery.data]);
  const personRouteUuid = React.useMemo(() => getRouteParam(searchParams, 'person'), [searchParams]);
  const projectionShapeAvailable = React.useMemo(
    () => hasCanonicalProjectionShape(rosterEntries),
    [rosterEntries],
  );
  const projectionStatus = React.useMemo(
    () => aggregateProjectionStatus(rosterEntries),
    [rosterEntries],
  );
  const personWorkspaceEntry = React.useMemo(() => {
    if (!personRouteUuid || !projectionShapeAvailable || projectionStatus !== 'current') {
      return null;
    }
    return (
      rosterEntries.find((entry) => getEntryPersonUuid(entry) === personRouteUuid) ?? null
    );
  }, [personRouteUuid, projectionShapeAvailable, projectionStatus, rosterEntries]);
  const projectionStateNotice = React.useMemo(() => {
    if (!parsedRoute.requiresProjectionGateNotice) {
      return null;
    }
    if (!projectionShapeAvailable) {
      return PERSON_WORKSPACE_GATE_NOTICE;
    }
    if (projectionStatus === 'refreshing') {
      return PROJECTION_REFRESHING_NOTICE;
    }
    if (projectionStatus === 'stale') {
      return PROJECTION_STALE_NOTICE;
    }
    if (projectionStatus === 'failed') {
      return PROJECTION_FAILED_NOTICE;
    }
    if (personRouteUuid && projectionStatus === 'current' && personWorkspaceEntry === null) {
      return PERSON_ROUTE_UNMATCHED_NOTICE;
    }
    return null;
  }, [
    parsedRoute.requiresProjectionGateNotice,
    projectionShapeAvailable,
    projectionStatus,
    personRouteUuid,
    personWorkspaceEntry,
  ]);
  const routeGateNotice = personWorkspaceEntry === null ? projectionStateNotice : null;

  const dragDrop = useClusterDragDrop();

  const actions = useClusterActions({
    onReassignSettled: dragDrop.resetDragState,
    onCommitSettled: dragDrop.resetDragState,
    onBulkMergeSettled: selection.clear,
    onBulkDismissSettled: selection.clear,
  });

  const handleDropFace = (targetClusterId: string | null): void => {
    const payload = dragDrop.dragPayload;
    if (!payload) {
      return;
    }
    if (targetClusterId && targetClusterId === payload.fromClusterId) {
      dragDrop.handleFaceDragEnd();
      return;
    }
    actions.reassignMutation.mutate({ faceId: payload.faceId, targetClusterId });
  };

  const handleRescanCluster = (cluster: ClusterSummary, identities: ClusterIdentity[]): void => {
    const sourceIdentities = identities.length > 0 ? identities : cluster.sample_identities;
    const mediaIds = Array.from(new Set(sourceIdentities.map((identity) => identity.media_id)));
    if (mediaIds.length === 0) {
      return;
    }

    actions.rescanMutation.mutate({ cluster, mediaIds });
  };

  const handleCommitCluster = (
    cluster: ClusterSummary,
    assignment: { rosterEntryId?: number; newEntryName?: string },
  ) => {
    actions.commitMutation.mutate({ clusterId: cluster.id, ...assignment });
  };

  const handleCloseDrawer = (): void => {
    setSelectedClusterId(null);
    dragDrop.resetDragState();
    actions.resetAll();
    setSearchParams(
      (previous) => {
        const next = new URLSearchParams(previous);
        next.delete('cluster');
        return next;
      },
      { replace: true },
    );
  };

  const handleTabChange = React.useCallback(
    (value: RosterTab) => {
      setSearchParams(
        (previous) => {
          const next = new URLSearchParams(previous);
          next.set('tab', value);
          for (const key of ROSTER_ROUTE_PARAM_KEYS) {
            next.delete(key);
          }
          return next;
        },
        { replace: true },
      );
    },
    [setSearchParams],
  );

  const handleSelectCluster = (cluster: ClusterSummary): void => {
    setSelectedClusterId(cluster.id);
    handleTabChange(ROSTER_TABS.clusters.id);
  };

  const handleBulkMerge = () => {
    const ids = Array.from(selection.selectedIds);
    if (ids.length < 2) {
      return;
    }
    setConfirmAction('merge');
  };

  const handleBulkDismiss = () => {
    const ids = Array.from(selection.selectedIds);
    if (ids.length === 0) {
      return;
    }
    setConfirmAction('dismiss');
  };

  const handleConfirm = React.useCallback(() => {
    const ids = Array.from(selection.selectedIds);
    void (async () => {
      let shouldClose = false;
      try {
        if (confirmAction === 'merge') {
          await actions.bulkMergeMutation.mutateAsync({ clusterIds: ids });
          shouldClose = true;
        } else if (confirmAction === 'dismiss') {
          await actions.bulkDismissMutation.mutateAsync({ clusterIds: ids });
          shouldClose = true;
        }
      } catch {
        // Mutation-level error handlers already surface feedback.
      } finally {
        if (shouldClose) {
          setConfirmAction(null);
        }
      }
    })();
  }, [actions.bulkDismissMutation, actions.bulkMergeMutation, confirmAction, selection.selectedIds]);

  const handleConfirmOpenChange = React.useCallback(
    (open: boolean) => {
      if (!open) {
        setConfirmAction(null);
      }
    },
    [setConfirmAction],
  );

  const selectedVisibleCount = React.useMemo(
    () => clusterIds.reduce((count, id) => (isClusterSelected(id) ? count + 1 : count), 0),
    [clusterIds, isClusterSelected],
  );
  const selectAllState = areAllVisibleClustersSelected(clusterIds)
    ? true
    : selectedVisibleCount > 0
      ? 'indeterminate'
      : false;
  const handleSelectAllClusters = React.useCallback(() => {
    if (areAllVisibleClustersSelected(clusterIds)) {
      selection.clear();
      return;
    }
    selection.selectAll(clusterIds);
  }, [areAllVisibleClustersSelected, clusterIds, selection]);

  const confirmDialogCopy =
    confirmAction === 'merge'
      ? {
          title: __('Confirm merge', 'alt-context'),
          description: sprintf(
            // translators: %d: number of clusters to merge
            __('Are you sure you want to merge %d clusters? This action cannot be undone.', 'alt-context'),
            selection.count,
          ),
          confirmLabel: __('Merge', 'alt-context'),
        }
      : confirmAction === 'dismiss'
        ? {
            title: __('Confirm dismiss', 'alt-context'),
            description: sprintf(
              // translators: %d: number of clusters to dismiss
              __('Are you sure you want to dismiss %d clusters?', 'alt-context'),
              selection.count,
            ),
            confirmLabel: __('Dismiss', 'alt-context'),
          }
        : null;

  return (
    <section className="acx-roster" aria-labelledby="acx-roster-title">
      <header className="acx-roster__hero">
        <p className="acx-roster__eyebrow">{__('Alt Context', 'alt-context')}</p>
        <h1 id="acx-roster-title" className="acx-roster__title">
          {__('Roster Management', 'alt-context')}
        </h1>
        <p className="acx-roster__subtitle">
          {__(
            'People are known identities you curate. Clusters are detected face groups you review and assign.',
            'alt-context',
          )}
        </p>
      </header>

      <Tabs value={activeTab} onValueChange={(value) => handleTabChange(value as RosterTab)}>
        <TabsList className="acx-roster__tabs" aria-label={__('Roster sections', 'alt-context')}>
          {Object.values(ROSTER_TABS).map((tab) => (
            <TabsTrigger key={tab.id} value={tab.id}>
              {tab.label}
            </TabsTrigger>
          ))}
        </TabsList>

        <TabsContent value={ROSTER_TABS.entries.id} className="acx-roster__panel">
          <h2>{ROSTER_TABS.entries.label}</h2>
          {personWorkspaceEntry !== null && (
            <section
              className="acx-roster__person-workspace"
              role="region"
              aria-label={sprintf(
                // translators: %s: person display name
                __('Person workspace: %s', 'alt-context'),
                personWorkspaceEntry.name,
              )}
            >
              <header className="acx-roster__person-workspace-header">
                <h3>{personWorkspaceEntry.name}</h3>
                <p className="acx-roster__person-workspace-meta">
                  {sprintf(
                    // translators: %d: cluster count assigned to this person
                    __('%d clusters assigned', 'alt-context'),
                    personWorkspaceEntry.cluster_count,
                  )}
                </p>
              </header>
            </section>
          )}
          <RosterEntriesSection query={entriesQuery} routeNotice={routeGateNotice} />
        </TabsContent>

        <TabsContent value={ROSTER_TABS.clusters.id} className="acx-roster__panel">
          <div className="acx-roster-help-card">
            <p>
              {__(
                'Clusters are groups of similar face identities detected across your media library. When you label a cluster, all associated images are automatically updated with the correct alt text.',
                'alt-context',
              )}
            </p>
          </div>
          <div className="acx-roster__tab-header">
            <div className="acx-roster__tab-header-main">
              <Checkbox
                checked={selectAllState}
                onCheckedChange={handleSelectAllClusters}
                ariaLabel={__('Select all clusters', 'alt-context')}
              />
              <h2>{ROSTER_TABS.clusters.label}</h2>
            </div>
            {selection.count > 0 && (
              <BulkActionBar
                count={selection.count}
                onMerge={handleBulkMerge}
                onDismiss={handleBulkDismiss}
                onClear={selection.clear}
                isMerging={actions.bulkMergeMutation.isPending}
                isDismissing={actions.bulkDismissMutation.isPending}
                mergeProgress={actions.bulkMergeProgress}
              />
            )}
          </div>
          {clusterList?.truncated && (
            <p className="acx-roster-help-card" role="status">
              {sprintf(
                __('Showing %d of %d clusters. Refine the list to review the remaining matches.', 'alt-context'),
                clusters.length,
                clusterList.total,
              )}
            </p>
          )}
          <ClusterGrid
            clusters={clusters}
            isLoading={clustersQuery.isLoading}
            isError={clustersQuery.isError}
            onRetry={() => void clustersQuery.refetch()}
            mediaMap={mediaMap}
            onSelectCluster={handleSelectCluster}
            selection={selection}
            onIdentityDragStart={dragDrop.handleFaceDragStart}
            onFaceDragEnd={dragDrop.handleFaceDragEnd}
            onDropTargetChange={dragDrop.handleDropTargetChange}
            onDropFace={handleDropFace}
            dropTarget={dragDrop.dropTarget}
            isDragging={dragDrop.isDragging}
          />
        </TabsContent>
      </Tabs>

      <ClusterDrawerPanel
        cluster={selectedCluster}
        identities={drawerIdentities}
        isDetailLoading={clusterDetailQuery.isLoading}
        detailError={
          clusterDetailQuery.isError
            ? (clusterDetailQuery.error?.message ?? __('Unable to load cluster details.', 'alt-context'))
            : null
        }
        mediaMap={mediaMap}
        onClose={handleCloseDrawer}
        onRescanCluster={handleRescanCluster}
        isRescanning={actions.rescanMutation.isPending}
        onCommitCluster={handleCommitCluster}
        isCommitting={actions.commitMutation.isPending}
        rosterEntries={rosterEntries}
        onFaceDragStart={dragDrop.handleFaceDragStart}
        onFaceDragEnd={dragDrop.handleFaceDragEnd}
        onDropTargetChange={dragDrop.handleDropTargetChange}
        dropTarget={dragDrop.dropTarget}
        isDragging={dragDrop.isDragging}
        onDiscardDrop={() => handleDropFace(null)}
      />
      {confirmDialogCopy && (
        <ConfirmDialog
          open={confirmAction !== null}
          onOpenChange={handleConfirmOpenChange}
          onConfirm={handleConfirm}
          onCancel={() => setConfirmAction(null)}
          title={confirmDialogCopy.title}
          description={confirmDialogCopy.description}
          confirmLabel={confirmDialogCopy.confirmLabel}
          isPending={actions.bulkMergeMutation.isPending || actions.bulkDismissMutation.isPending}
        />
      )}
    </section>
  );
};
