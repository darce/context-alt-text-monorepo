import React from 'react';
import { __ } from '@wordpress/i18n';
import { useSearchParams } from 'react-router-dom';
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
import { NeedsAssignmentSection } from './roster/NeedsAssignmentSection';
import {
  ROSTER_SURFACE,
  ROSTER_ROUTE_PARAM_KEYS,
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
  const selectAllSelection = selection.selectAll;

  const clustersQuery = useRecognitionClusters({ limit: 20 });
  const clusterList = clustersQuery.data;
  const clusters = React.useMemo(() => clusterList?.clusters ?? [], [clusterList]);
  const clusterIds = React.useMemo(() => clusters.map((cluster) => cluster.id), [clusters]);
  const parsedRoute = React.useMemo(() => parseRosterRoute(searchParams), [searchParams]);

  React.useEffect(() => {
    if (clustersQuery.data === undefined) {
      return;
    }
    retainVisibleSelection(clusterIds);
  }, [clusterIds, clustersQuery.data, retainVisibleSelection]);

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
      parsedRoute.selectedClusterId === null &&
      !parsedRoute.requiresProjectionGateNotice &&
      !hasEntriesFilter,
    [hasEntriesFilter, parsedRoute.requiresProjectionGateNotice, parsedRoute.selectedClusterId],
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
    onBulkMergeSettled: clearSelection,
    onBulkMergeFailure: selectAllSelection,
    onBulkDismissSettled: clearSelection,
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

  const reassignTargets = React.useMemo(
    () =>
      clusters
        .filter((candidate) => candidate.id !== selectedClusterId)
        .map((candidate) => ({
          id: candidate.id,
          label: candidate.label ?? '',
        })),
    [clusters, selectedClusterId],
  );

  const handleReassignFace = React.useCallback(
    (faceId: string, targetClusterId: string): void => {
      actions.reassignMutation.mutate({ faceId, targetClusterId });
    },
    [actions.reassignMutation],
  );

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
          next.delete('tab');
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

  const handleSelectCluster = (cluster: ClusterSummary): void => {
    setSelectedClusterId(cluster.id);
    setSearchParams(
      (previous) => {
        const next = new URLSearchParams(previous);
        next.delete('tab');
        next.set('cluster', cluster.id);
        return next;
      },
      { replace: true },
    );
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
            'People are known identities you curate. Unassigned face groups stay reachable below for bulk merge or workbench review.',
            'alt-context',
          )}
        </p>
      </header>

      <div className="acx-roster__panel">
        <h2>{ROSTER_SURFACE.label}</h2>
        {resolvedWorkspaceEntry !== null && (
          <PersonWorkspacePanel entry={resolvedWorkspaceEntry} onOpenQueue={handleOpenPersonWorkspace} />
        )}
        <RosterEntriesSection query={entriesQuery} routeNotice={routeGateNotice} />

        <NeedsAssignmentSection
          clusters={clusters}
          selection={selection}
          actions={actions}
          isLoading={clustersQuery.isLoading}
          isError={clustersQuery.isError}
          onRetry={() => void clustersQuery.refetch()}
          onOpenCluster={handleSelectCluster}
          truncated={clusterList?.truncated}
          listTotal={clusterList?.total}
        />
      </div>

      <ClusterDrawerPanel
        cluster={selectedCluster === null ? null : (clusterDetailQuery.data ?? selectedCluster)}
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
        reassignTargets={reassignTargets}
        onReassignFace={handleReassignFace}
        isReassigning={actions.reassignMutation.isPending}
        reassignErrorMessage={actions.reassignMutation.error?.message ?? null}
      />
    </section>
  );
};
