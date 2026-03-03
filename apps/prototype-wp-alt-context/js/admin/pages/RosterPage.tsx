import React from 'react';
import { __ } from '@wordpress/i18n';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '../../components/ui/tabs';
import type { ClusterIdentity, ClusterSummary } from '../api/recognition';
import { useRecognitionCluster, useRecognitionClusters } from '../hooks/useRecognitionHooks';
import { useRosterEntries } from '../hooks/useRosterHooks';
import { useClusterMediaMap } from './roster/hooks/useClusterMediaMap';
import { useClusterDragDrop } from './roster/hooks/useClusterDragDrop';
import { useClusterActions } from './roster/hooks/useClusterActions';
import { ClusterGrid } from './roster/ClusterGrid';
import { ClusterDrawerPanel } from './roster/ClusterDrawerPanel';
import { RosterEntriesSection } from './roster/RosterEntriesSection';
import { useTabParam } from '../hooks/useTabParam';
const ROSTER_TABS = {
  entries: { id: 'entries' as const, label: __('Entries', 'alt-context') },
  clusters: { id: 'clusters' as const, label: __('Clusters', 'alt-context') },
} as const;

type RosterTab = (typeof ROSTER_TABS)[keyof typeof ROSTER_TABS]['id'];

export const RosterPage = (): React.JSX.Element => {
  const [activeTab, setActiveTab] = useTabParam<RosterTab>('tab', ROSTER_TABS.entries.id, [
    ROSTER_TABS.entries.id,
    ROSTER_TABS.clusters.id,
  ]);
  const [selectedClusterId, setSelectedClusterId] = React.useState<string | null>(null);

  const clustersQuery = useRecognitionClusters({ limit: 20 });
  const clusters = React.useMemo(() => clustersQuery.data ?? [], [clustersQuery.data]);
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
  const rosterEntries = entriesQuery.data ?? [];

  const dragDrop = useClusterDragDrop();

  const actions = useClusterActions({
    onReassignSettled: dragDrop.resetDragState,
    onCommitSettled: dragDrop.resetDragState,
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
  };

  const handleSelectCluster = (cluster: ClusterSummary): void => {
    setSelectedClusterId(cluster.id);
    setActiveTab(ROSTER_TABS.clusters.id);
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
            'Review roster entries and fine-tune identity clusters to keep recognition accurate across batches.',
            'alt-context',
          )}
        </p>
      </header>

      <Tabs value={activeTab} onValueChange={(value) => setActiveTab(value as RosterTab)}>
        <TabsList className="acx-roster__tabs" aria-label={__('Roster sections', 'alt-context')}>
          {Object.values(ROSTER_TABS).map((tab) => (
            <TabsTrigger key={tab.id} value={tab.id}>
              {tab.label}
            </TabsTrigger>
          ))}
        </TabsList>

        <TabsContent value={ROSTER_TABS.entries.id} className="acx-roster__panel">
          <h2>{ROSTER_TABS.entries.label}</h2>
          <RosterEntriesSection query={entriesQuery} />
        </TabsContent>

        <TabsContent value={ROSTER_TABS.clusters.id} className="acx-roster__panel">
          <h2>{ROSTER_TABS.clusters.label}</h2>
          <ClusterGrid
            clusters={clusters}
            isLoading={clustersQuery.isLoading}
            isError={clustersQuery.isError}
            onRetry={() => void clustersQuery.refetch()}
            mediaMap={mediaMap}
            onSelectCluster={handleSelectCluster}
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
        statusMessage={actions.statusMessage}
        errorMessage={actions.errorMessage}
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
