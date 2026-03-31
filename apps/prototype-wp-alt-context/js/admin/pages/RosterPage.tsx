import React from 'react';
import { __, sprintf } from '@wordpress/i18n';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '../../components/ui/tabs';
import type { ClusterIdentity, ClusterSummary } from '../api/recognition';
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
import { useTabParam } from '../hooks/useTabParam';
import { Checkbox } from '../../components/ui/checkbox';
import { ConfirmDialog } from './roster/ConfirmDialog';
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
  const [confirmAction, setConfirmAction] = React.useState<'merge' | 'dismiss' | null>(null);

  const selection = useClusterSelection();
  const clearSelection = selection.clear;
  const retainVisibleSelection = selection.retainVisible;
  const isClusterSelected = selection.isSelected;
  const areAllVisibleClustersSelected = selection.isAllSelected;

  const clustersQuery = useRecognitionClusters({ limit: 20 });
  const clusters = React.useMemo(() => clustersQuery.data ?? [], [clustersQuery.data]);
  const clusterIds = React.useMemo(() => clusters.map((cluster) => cluster.id), [clusters]);

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
  };

  const handleSelectCluster = (cluster: ClusterSummary): void => {
    setSelectedClusterId(cluster.id);
    setActiveTab(ROSTER_TABS.clusters.id);
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
