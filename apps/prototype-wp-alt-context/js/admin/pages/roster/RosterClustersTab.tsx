import React from 'react';
import { __, sprintf } from '@wordpress/i18n';

import type { ClusterSummary } from '../../api/recognition';
import { useClusterSelection } from '../../hooks/useClusterSelection';
import { Checkbox } from '../../../components/ui/checkbox';
import { BulkActionBar } from './BulkActionBar';
import { ClusterGrid } from './ClusterGrid';
import { ConfirmDialog } from './ConfirmDialog';
import { useClusterActions } from './hooks/useClusterActions';
import type { MediaMap } from './hooks/useClusterMediaMap';
import { useClusterDragDrop } from './hooks/useClusterDragDrop';
import { useRosterBulkConfirmation } from './useRosterBulkConfirmation';

interface ClusterListData {
  truncated?: boolean;
  total: number;
}

interface RosterClustersTabProps {
  clusterList: ClusterListData | undefined;
  clusters: ClusterSummary[];
  clusterIds: string[];
  selection: ReturnType<typeof useClusterSelection>;
  actions: ReturnType<typeof useClusterActions>;
  mediaMap: MediaMap;
  dragDrop: ReturnType<typeof useClusterDragDrop>;
  isLoading: boolean;
  isError: boolean;
  onRetry: () => void;
  onSelectCluster: (cluster: ClusterSummary) => void;
  onDropFace: (targetClusterId: string | null) => void;
}

export const RosterClustersTab = ({
  clusterList,
  clusters,
  clusterIds,
  selection,
  actions,
  mediaMap,
  dragDrop,
  isLoading,
  isError,
  onRetry,
  onSelectCluster,
  onDropFace,
}: RosterClustersTabProps): React.JSX.Element => {
  const {
    confirmAction,
    setConfirmAction,
    handleBulkMerge,
    handleBulkDismiss,
    handleConfirm,
    handleConfirmOpenChange,
    confirmDialogCopy,
  } = useRosterBulkConfirmation({
    selection,
    bulkMergeMutation: actions.bulkMergeMutation,
    bulkDismissMutation: actions.bulkDismissMutation,
  });

  const selectedVisibleCount = React.useMemo(
    () => clusterIds.reduce((count, id) => (selection.isSelected(id) ? count + 1 : count), 0),
    [clusterIds, selection],
  );

  const selectAllState = selection.isAllSelected(clusterIds)
    ? true
    : selectedVisibleCount > 0
      ? 'indeterminate'
      : false;

  const handleSelectAllClusters = React.useCallback(() => {
    if (selection.isAllSelected(clusterIds)) {
      selection.clear();
      return;
    }
    selection.selectAll(clusterIds);
  }, [clusterIds, selection]);

  return (
    <>
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
          <h2>{__('Clusters', 'alt-context')}</h2>
        </div>
        {selection.count > 0 ? (
          <BulkActionBar
            count={selection.count}
            onMerge={handleBulkMerge}
            onDismiss={handleBulkDismiss}
            onClear={selection.clear}
            isMerging={actions.bulkMergeMutation.isPending}
            isDismissing={actions.bulkDismissMutation.isPending}
            mergeProgress={actions.bulkMergeProgress}
          />
        ) : null}
      </div>
      {clusterList?.truncated ? (
        <p className="acx-roster-help-card" role="status">
          {sprintf(
            __('Showing %d of %d clusters. Refine the list to review the remaining matches.', 'alt-context'),
            clusters.length,
            clusterList.total,
          )}
        </p>
      ) : null}
      <ClusterGrid
        clusters={clusters}
        isLoading={isLoading}
        isError={isError}
        onRetry={onRetry}
        mediaMap={mediaMap}
        onSelectCluster={onSelectCluster}
        selection={selection}
        onIdentityDragStart={dragDrop.handleFaceDragStart}
        onFaceDragEnd={dragDrop.handleFaceDragEnd}
        onDropTargetChange={dragDrop.handleDropTargetChange}
        onDropFace={onDropFace}
        dropTarget={dragDrop.dropTarget}
        isDragging={dragDrop.isDragging}
      />
      {confirmDialogCopy ? (
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
      ) : null}
    </>
  );
};