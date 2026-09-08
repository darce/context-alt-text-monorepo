import React from 'react';
import { __, _n, sprintf } from '@wordpress/i18n';
import { useSearchParams } from 'react-router-dom';
import type { ClusterIdentity, ClusterSummary } from '../api/recognition';
import { useRecognitionCluster } from '../hooks/useRecognitionHooks';
import { useRosterEntries } from '../hooks/useRosterHooks';

import { useClusterMediaMap } from './roster/hooks/useClusterMediaMap';
import { useClusterDragDrop } from './roster/hooks/useClusterDragDrop';
import { useClusterActions } from './roster/hooks/useClusterActions';
import { useTopUnlabeledTotal } from './roster/hooks/useTopUnlabeledTotal';
import { ClusterDrawerPanel, ROSTER_ASSIGN_STATUS } from './roster/ClusterDrawerPanel';
import { RosterEntriesSection } from './roster/RosterEntriesSection';
import { PersonWorkspacePanel } from './roster/PersonWorkspacePanel';
import {
  ROSTER_SURFACE,
  ROSTER_ROUTE_PARAM_KEYS,
  parseRosterRoute,
  getRouteParam,
  getEntryPersonUuid,
  hasCanonicalProjectionShape,
  aggregateProjectionStatus,
  selectDeterministicDefaultWorkspaceEntry,
  workbenchReviewQueueUrl,
  PERSON_WORKSPACE_GATE_NOTICE,
  PROJECTION_REFRESHING_NOTICE,
  PROJECTION_STALE_NOTICE,
  PROJECTION_FAILED_NOTICE,
  PERSON_ROUTE_UNMATCHED_NOTICE,
  REASSIGN_UNAVAILABLE_REASON,
} from './roster/rosterRoute';

export const RosterPage = (): React.JSX.Element => {
  const [searchParams, setSearchParams] = useSearchParams();

  const parsedRoute = React.useMemo(() => parseRosterRoute(searchParams), [searchParams]);
  const selectedClusterId = parsedRoute.selectedClusterId;

  // UXW2-4: the needs-assignment rail is retired (NAV-05 — the workbench queue is
  // the single home for unnamed faces). The drawer survives only as a `?cluster=`
  // deep-link shim (E21-10), fed by the detail query alone.
  const clusterDetailQuery = useRecognitionCluster(selectedClusterId, Boolean(selectedClusterId));
  const drawerCluster = clusterDetailQuery.data ?? null;
  const drawerIdentities = React.useMemo(
    () => clusterDetailQuery.data?.sample_identities ?? [],
    [clusterDetailQuery.data],
  );
  const drawerMediaIds = React.useMemo(
    () => Array.from(new Set(drawerIdentities.map((identity) => identity.media_id))),
    [drawerIdentities],
  );
  const drawerClusters = React.useMemo(() => (drawerCluster ? [drawerCluster] : []), [drawerCluster]);
  const mediaMap = useClusterMediaMap(drawerClusters, drawerMediaIds);
  const entriesQuery = useRosterEntries();
  const rosterEntries = React.useMemo(() => entriesQuery.data ?? [], [entriesQuery.data]);
  const topUnlabeledTotal = useTopUnlabeledTotal();
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
  });

  const reassignUnavailableReason =
    selectedClusterId === null
      ? null
      : REASSIGN_UNAVAILABLE_REASON;

  const handleDropFace = (targetClusterId: string | null): void => {
    const payload = dragDrop.dragPayload;
    if (!payload) {
      return;
    }
    if (reassignUnavailableReason) {
      dragDrop.handleFaceDragEnd();
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

  return (
    <section className="acx-roster" aria-labelledby="acx-roster-title">
      <header className="acx-roster__hero">
        <p className="acx-roster__eyebrow">{__('Alt Context', 'alt-context')}</p>
        <h1 id="acx-roster-title" className="acx-roster__title">
          {__('People', 'alt-context')}
        </h1>
        <p className="acx-roster__subtitle">
          {__(
            'People are the faces you have named. Unnamed face groups are reviewed in the Review Queue.',
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

        <section
          className="acx-roster__review-cta"
          aria-labelledby="acx-roster-review-cta-title"
          data-testid="roster-review-cta"
        >
          <h2 id="acx-roster-review-cta-title">
            {topUnlabeledTotal === null
              ? __('Unnamed faces', 'alt-context')
              : topUnlabeledTotal === 0
                ? __('No unnamed face groups right now', 'alt-context')
                : __('Unnamed faces waiting', 'alt-context')}
          </h2>
          <p role="status">
            {topUnlabeledTotal === null
              ? ''
              : topUnlabeledTotal === 0
                ? __('Nothing waiting in the review queue.', 'alt-context')
                : sprintf(
                    // translators: %d: server-reported count of unnamed face groups
                    _n('%d face group waiting', '%d face groups waiting', topUnlabeledTotal, 'alt-context'),
                    topUnlabeledTotal,
                  )}
          </p>
          {topUnlabeledTotal === null ? (
            <p>{__('Unnamed faces are reviewed in the Review Queue.', 'alt-context')}</p>
          ) : null}
          <a className="acx-button acx-button--secondary" href={workbenchReviewQueueUrl()}>
            {__('Open Review Queue', 'alt-context')}
          </a>
        </section>
      </div>

      <ClusterDrawerPanel
        cluster={selectedClusterId === null ? null : drawerCluster}
        requestedClusterId={selectedClusterId}
        reassignUnavailableReason={reassignUnavailableReason}
        identities={drawerIdentities}
        isDetailLoading={clusterDetailQuery.isLoading}
        detailError={
          clusterDetailQuery.isError
            ? (clusterDetailQuery.error?.message ?? __('Unable to load face group details.', 'alt-context'))
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
        rosterStatus={
          entriesQuery.isError
            ? ROSTER_ASSIGN_STATUS.error
            : entriesQuery.isPending
              ? ROSTER_ASSIGN_STATUS.loading
              : ROSTER_ASSIGN_STATUS.ready
        }
        onRetryRoster={() => {
          void entriesQuery.refetch();
        }}
        onFaceDragStart={dragDrop.handleFaceDragStart}
        onFaceDragEnd={dragDrop.handleFaceDragEnd}
        onDropTargetChange={dragDrop.handleDropTargetChange}
        dropTarget={dragDrop.dropTarget}
        isDragging={dragDrop.isDragging}
        onDiscardDrop={() => handleDropFace(null)}
        // UXW2-4-R1-16: picker boarded up on the cluster= shim (no scoped
        // reassignTargets query). Follow-up: restore via a scoped query (REF-25).
        isReassigning={actions.reassignMutation.isPending}
        reassignErrorMessage={actions.reassignMutation.error?.message ?? null}
      />
    </section>
  );
};
