import React from 'react';
import { __ } from '@wordpress/i18n';
import { useSearchParams } from 'react-router-dom';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '../../components/ui/tabs';
import type { ClusterIdentity, ClusterSummary } from '../api/recognition';
import { useRecognitionCluster, useRecognitionClusters } from '../hooks/useRecognitionHooks';
import { useRosterEntries } from '../hooks/useRosterHooks';
import { useClusterSelection } from '../hooks/useClusterSelection';
import { useClusterMediaMap } from './roster/hooks/useClusterMediaMap';
import { useClusterDragDrop } from './roster/hooks/useClusterDragDrop';
import { useClusterActions } from './roster/hooks/useClusterActions';
import { ClusterDrawerPanel } from './roster/ClusterDrawerPanel';
import { RosterEntriesSection } from './roster/RosterEntriesSection';
import { PersonWorkspacePanel } from './roster/PersonWorkspacePanel';
import { RosterClustersTab } from './roster/RosterClustersTab';
import {
  ROSTER_TABS,
  ROSTER_ROUTE_PARAM_KEYS,
  type RosterTab,
  parseRosterRoute,
  getRouteParam,
  getEntryPersonUuid,
  hasCanonicalProjectionShape,
  aggregateProjectionStatus,
  selectDeterministicDefaultWorkspaceEntry,
  PERSON_WORKSPACE_GATE_NOTICE,
  PROJECTION_REFRESHING_NOTICE,
  PROJECTION_STALE_NOTICE,
  PROJECTION_FAILED_NOTICE,
  PERSON_ROUTE_UNMATCHED_NOTICE,
} from './roster/rosterRoute';

export const RosterPage = (): React.JSX.Element => {
  const [searchParams, setSearchParams] = useSearchParams();
  const [selectedClusterId, setSelectedClusterId] = React.useState<string | null>(null);

  const selection = useClusterSelection();
  const clearSelection = selection.clear;
  const retainVisibleSelection = selection.retainVisible;

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
  const projectionShapeAvailable = React.useMemo(() => hasCanonicalProjectionShape(rosterEntries), [rosterEntries]);
  const projectionStatus = React.useMemo(() => aggregateProjectionStatus(rosterEntries), [rosterEntries]);
  const personWorkspaceEntry = React.useMemo(() => {
    if (!personRouteUuid || !projectionShapeAvailable || projectionStatus !== 'current') {
      return null;
    }
    return rosterEntries.find((entry) => getEntryPersonUuid(entry) === personRouteUuid) ?? null;
  }, [personRouteUuid, projectionShapeAvailable, projectionStatus, rosterEntries]);
  const hasEntriesFilter = searchParams.get('personFilter') !== null;
  const defaultWorkspaceRoute = React.useMemo(
    () =>
      activeTab === ROSTER_TABS.entries.id &&
      parsedRoute.selectedClusterId === null &&
      !parsedRoute.requiresProjectionGateNotice &&
      !hasEntriesFilter,
    [activeTab, hasEntriesFilter, parsedRoute.requiresProjectionGateNotice, parsedRoute.selectedClusterId],
  );
  const defaultWorkspaceEntry = React.useMemo(() => {
    if (!defaultWorkspaceRoute) {
      return null;
    }
    if (!projectionShapeAvailable || projectionStatus !== 'current') {
      return null;
    }
    return selectDeterministicDefaultWorkspaceEntry(rosterEntries);
  }, [defaultWorkspaceRoute, projectionShapeAvailable, projectionStatus, rosterEntries]);
  const resolvedWorkspaceEntry = personWorkspaceEntry ?? defaultWorkspaceEntry;
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
  const routeGateNotice = resolvedWorkspaceEntry === null ? projectionStateNotice : null;

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

  const handleOpenPersonWorkspace = React.useCallback(
    (personUuid: string, queueId?: string) => {
      setSelectedClusterId(null);
      dragDrop.resetDragState();
      actions.resetAll();
      setSearchParams(
        (previous) => {
          const next = new URLSearchParams(previous);
          next.set('tab', ROSTER_TABS.entries.id);
          for (const key of ROSTER_ROUTE_PARAM_KEYS) {
            next.delete(key);
          }
          next.set('person', personUuid);
          if (queueId) {
            next.set('queue', queueId);
          }
          return next;
        },
        { replace: true },
      );
    },
    [actions, dragDrop, setSearchParams],
  );

  const handleTabChange = React.useCallback(
    (value: RosterTab) => {
      setSearchParams(
        (previous) => {
          const next = new URLSearchParams(previous);
          if (value === ROSTER_TABS.entries.id) {
            next.delete('tab');
          } else {
            next.set('tab', value);
          }
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
          {resolvedWorkspaceEntry !== null && (
            <PersonWorkspacePanel entry={resolvedWorkspaceEntry} onOpenQueue={handleOpenPersonWorkspace} />
          )}
          <RosterEntriesSection query={entriesQuery} routeNotice={routeGateNotice} />
        </TabsContent>

        <TabsContent value={ROSTER_TABS.clusters.id} className="acx-roster__panel">
          <RosterClustersTab
            clusterList={clusterList}
            clusters={clusters}
            clusterIds={clusterIds}
            selection={selection}
            actions={actions}
            mediaMap={mediaMap}
            dragDrop={dragDrop}
            isLoading={clustersQuery.isLoading}
            isError={clustersQuery.isError}
            onRetry={() => void clustersQuery.refetch()}
            onSelectCluster={handleSelectCluster}
            onDropFace={handleDropFace}
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
        rescanDisabled={actions.rescanGate.disabled}
        rescanTitle={actions.rescanGate.title}
        rescanAriaDisabled={actions.rescanGate['aria-disabled']}
        onCommitCluster={handleCommitCluster}
        onOpenPersonWorkspace={handleOpenPersonWorkspace}
        isCommitting={actions.commitMutation.isPending}
        rosterEntries={rosterEntries}
        onFaceDragStart={dragDrop.handleFaceDragStart}
        onFaceDragEnd={dragDrop.handleFaceDragEnd}
        onDropTargetChange={dragDrop.handleDropTargetChange}
        dropTarget={dragDrop.dropTarget}
        isDragging={dragDrop.isDragging}
        onDiscardDrop={() => handleDropFace(null)}
      />
    </section>
  );
};
