import React from 'react';
import { __ } from '@wordpress/i18n';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '../../components/ui/tabs';
import type { ClusterSummary } from '../api/recognitionApi';
import type { RosterEntry } from '../api/rosterApi';
import { useRecognitionCluster, useRecognitionClusters } from '../hooks/useRecognitionHooks';
import { useRosterEntries } from '../hooks/useRosterHooks';
import { useClusterMediaMap } from './roster/hooks/useClusterMediaMap';
import { useClusterDragDrop } from './roster/hooks/useClusterDragDrop';
import { useClusterActions } from './roster/hooks/useClusterActions';
import { ClusterGrid } from './roster/ClusterGrid';
import { ClusterDrawerPanel } from './roster/ClusterDrawerPanel';
import type { ClusterFace } from '../api/recognitionApi';

const ROSTER_TABS = {
  entries: { id: 'entries' as const, label: __('Entries', 'alt-context') },
  clusters: { id: 'clusters' as const, label: __('Clusters', 'alt-context') },
} as const;

type RosterTab = (typeof ROSTER_TABS)[keyof typeof ROSTER_TABS]['id'];

export const RosterPage = (): React.JSX.Element => {
  const [activeTab, setActiveTab] = React.useState<RosterTab>(ROSTER_TABS.entries.id);
  const [selectedClusterId, setSelectedClusterId] = React.useState<string | null>(null);

  const clustersQuery = useRecognitionClusters({ limit: 20 });
  const clusters = clustersQuery.data ?? [];
  const selectedCluster = React.useMemo(
    () => clusters.find((cluster) => cluster.id === selectedClusterId) ?? null,
    [clusters, selectedClusterId],
  );
  const clusterDetailQuery = useRecognitionCluster(selectedClusterId, Boolean(selectedClusterId));
  const drawerFaces = clusterDetailQuery.data?.sample_faces ?? selectedCluster?.sample_faces ?? [];
  const drawerMediaIds = React.useMemo(
    () => Array.from(new Set(drawerFaces.map((face) => face.media_id))),
    [drawerFaces],
  );
  const mediaMap = useClusterMediaMap(clusters, drawerMediaIds);
  const entriesQuery = useRosterEntries();
  const rosterEntries = entriesQuery.data ?? [];

  const dragDrop = useClusterDragDrop();

  const actions = useClusterActions({
    onReassignSettled: dragDrop.resetDragState,
    onCommitSettled: dragDrop.resetDragState,
  });

  React.useEffect(() => {
    const url = new URL(window.location.href);
    const tabParam = url.searchParams.get('tab');
    if (tabParam === ROSTER_TABS.clusters.id || tabParam === ROSTER_TABS.entries.id) {
      setActiveTab(tabParam as RosterTab);
    }
  }, []);

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

  const handleRescanCluster = (cluster: ClusterSummary, faces: ClusterFace[]): void => {
    const sourceFaces = faces.length > 0 ? faces : cluster.sample_faces;
    const mediaIds = Array.from(new Set(sourceFaces.map((face) => face.media_id)));
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
            'Review roster entries and fine-tune facial clusters to keep recognition accurate across batches.',
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
            onRetry={clustersQuery.refetch}
            mediaMap={mediaMap}
            onSelectCluster={handleSelectCluster}
            onFaceDragStart={dragDrop.handleFaceDragStart}
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
        faces={drawerFaces}
        isDetailLoading={clusterDetailQuery.isLoading}
        detailError={
          clusterDetailQuery.isError
            ? clusterDetailQuery.error?.message ?? __('Unable to load cluster details.', 'alt-context')
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
        onDropFace={handleDropFace}
        dropTarget={dragDrop.dropTarget}
        isDragging={dragDrop.isDragging}
        onDiscardDrop={() => handleDropFace(null)}
      />
    </section>
  );
};

const RosterEntriesSection = ({ query }: { query: ReturnType<typeof useRosterEntries> }) => {
  if (query.isLoading) {
    return <p>{__('Loading roster entries…', 'alt-context')}</p>;
  }

  if (query.isError) {
    return (
      <div>
        <p>{__('Unable to load roster entries.', 'alt-context')}</p>
        <button type="button" onClick={() => query.refetch()}>
          {__('Retry', 'alt-context')}
        </button>
      </div>
    );
  }

  return <RosterEntriesTable entries={query.data ?? []} />;
};

const RosterEntriesTable = ({ entries }: { entries: RosterEntry[] }) => {
  if (entries.length === 0) {
    return <p>{__('No roster entries found yet.', 'alt-context')}</p>;
  }

  return (
    <div className="acx-roster-entries">
      <table className="acx-roster-entries__table">
        <thead>
          <tr>
            <th>{__('Identity', 'alt-context')}</th>
            <th>{__('Tags', 'alt-context')}</th>
            <th>{__('Clusters', 'alt-context')}</th>
            <th>{__('Updated', 'alt-context')}</th>
          </tr>
        </thead>
        <tbody>
          {entries.map((entry) => (
            <tr key={entry.id}>
              <td>
                <strong>{entry.name}</strong>
              </td>
              <td>{entry.tags.length === 0 ? __('No tags', 'alt-context') : entry.tags.join(', ')}</td>
              <td>{entry.cluster_count}</td>
              <td>{new Date(entry.updated_at).toLocaleDateString()}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
};

export { ClusterGrid as ClusterGallery, ClusterDrawerPanel as ClusterDrawer };
export { RosterEntriesSection, RosterEntriesTable };
