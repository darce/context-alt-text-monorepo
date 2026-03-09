import React from 'react';
import { __, _n, sprintf } from '@wordpress/i18n';
import type { ClusterSummary } from '../../api/recognition';
import type { MediaMap } from './hooks/useClusterMediaMap';
import { IdentityThumbnail } from './IdentityThumbnail';
import { Checkbox } from '../../../components/ui/checkbox';
import { useClusterSelection } from '../../hooks/useClusterSelection';

interface Props {
  clusters: ClusterSummary[];
  isLoading: boolean;
  isError: boolean;
  onRetry: () => void;
  mediaMap: MediaMap;
  onSelectCluster: (cluster: ClusterSummary) => void;
  selection: ReturnType<typeof useClusterSelection>;
  onIdentityDragStart: (clusterId: string, identityId: string) => void;
  onFaceDragEnd: () => void;
  onDropTargetChange: (target: string | null) => void;
  onDropFace: (clusterId: string | null) => void;
  dropTarget: string | null;
  isDragging: boolean;
}

export const ClusterGrid = ({
  clusters,
  isLoading,
  isError,
  onRetry,
  isDragging,
  dropTarget,
  mediaMap,
  onIdentityDragStart,
  onDropFace,
  onDropTargetChange,
  onFaceDragEnd,
  onSelectCluster,
  selection,
}: Props): React.JSX.Element => {
  const [lastSelectedId, setLastSelectedId] = React.useState<string | null>(null);
  const gridRef = React.useRef<HTMLDivElement>(null);

  const clusterIds = React.useMemo(() => clusters.map((c) => c.id), [clusters]);

  const handleClusterClick = React.useCallback(
    (cluster: ClusterSummary, event: React.MouseEvent | React.KeyboardEvent) => {
      // If checkbox was clicked via mouse, don't trigger drawer
      if (event.type === 'click' && (event.target as HTMLElement).closest('.acx-checkbox')) {
        return;
      }

      if (event.shiftKey && lastSelectedId) {
        const start = clusterIds.indexOf(lastSelectedId);
        const end = clusterIds.indexOf(cluster.id);
        if (start !== -1 && end !== -1) {
          const range = clusterIds.slice(Math.min(start, end), Math.max(start, end) + 1);
          selection.selectRange(range);
          setLastSelectedId(cluster.id);
          return;
        }
      }

      // Default: select for drawer
      onSelectCluster(cluster);
    },
    [clusterIds, lastSelectedId, onSelectCluster, selection],
  );

  const handleKeyDown = React.useCallback(
    (cluster: ClusterSummary, index: number) => (event: React.KeyboardEvent<HTMLElement>) => {
      const cards = gridRef.current?.querySelectorAll<HTMLElement>('.acx-cluster-card');
      if (!cards || !gridRef.current) {
        return;
      }

      // Calculate columns from grid computed style
      const gridStyle = window.getComputedStyle(gridRef.current);
      const gridTemplateColumns = gridStyle.getPropertyValue('grid-template-columns');
      const columns = gridTemplateColumns.split(' ').length || 3;

      switch (event.key) {
        case 'Enter':
          event.preventDefault();
          onSelectCluster(cluster);
          break;
        case ' ':
          event.preventDefault();
          selection.toggle(cluster.id);
          setLastSelectedId(cluster.id);
          break;
        case 'ArrowRight':
          event.preventDefault();
          cards[Math.min(index + 1, cards.length - 1)]?.focus();
          break;
        case 'ArrowLeft':
          event.preventDefault();
          cards[Math.max(index - 1, 0)]?.focus();
          break;
        case 'ArrowDown':
          event.preventDefault();
          cards[Math.min(index + columns, cards.length - 1)]?.focus();
          break;
        case 'ArrowUp':
          event.preventDefault();
          cards[Math.max(index - columns, 0)]?.focus();
          break;
        case 'Escape':
          selection.clear();
          break;
      }
    },
    [onSelectCluster, selection],
  );

  const handleDragOver = React.useCallback(
    (clusterId: string) => (event: React.DragEvent<HTMLElement>) => {
      if (!isDragging) {
        return;
      }
      event.preventDefault();
      onDropTargetChange(clusterId);
    },
    [isDragging, onDropTargetChange],
  );

  const handleDrop = React.useCallback(
    (clusterId: string) => (event: React.DragEvent<HTMLElement>) => {
      if (!isDragging) {
        return;
      }
      event.preventDefault();
      onDropFace(clusterId);
    },
    [isDragging, onDropFace],
  );

  const handleIdentityDragStart = React.useCallback(
    (clusterId: string, identityId: string) => (event: React.DragEvent<HTMLElement>) => {
      event.dataTransfer?.setData('text/plain', identityId);
      event.dataTransfer?.setDragImage(event.currentTarget, 0, 0);
      onIdentityDragStart(clusterId, identityId);
    },
    [onIdentityDragStart],
  );

  if (isLoading) {
    return <p>{__('Loading clusters…', 'alt-context')}</p>;
  }

  if (isError) {
    return (
      <div>
        <p>{__('Unable to load clusters.', 'alt-context')}</p>
        <button type="button" onClick={onRetry}>
          {__('Retry', 'alt-context')}
        </button>
      </div>
    );
  }

  if (clusters.length === 0) {
    return (
      <div className="acx-apply-panel acx-apply-panel--empty">
        <h3>{__('No clusters yet', 'alt-context')}</h3>
        <p>
          {__(
            'Once you scan your media library and run the clustering process, groups of similar faces will appear here for you to label.',
            'alt-context',
          )}
        </p>
        <a href="#/workbench?tab=scan" className="acx-button acx-button--secondary">
          {__('Go to Scan tab', 'alt-context')}
        </a>
      </div>
    );
  }

  return (
    <div className="acx-cluster-grid" ref={gridRef} role="group" aria-label={__('Cluster cards', 'alt-context')}>
      {clusters.map((cluster, index) => {
        const isSelected = selection.isSelected(cluster.id);
        const isDropTarget = dropTarget === cluster.id;

        return (
          <article
            key={cluster.id}
            className={`acx-cluster-card${isDropTarget ? ' is-drop-target' : ''}${isSelected ? ' is-selected' : ''}`}
            onClick={(e) => handleClusterClick(cluster, e)}
            onKeyDown={handleKeyDown(cluster, index)}
            onDragOver={handleDragOver(cluster.id)}
            onDragLeave={() => {
              if (dropTarget === cluster.id) {
                onDropTargetChange(null);
              }
            }}
            onDrop={handleDrop(cluster.id)}
            role="button"
            aria-pressed={isSelected}
            tabIndex={0}
          >
            <div className="acx-cluster-card__select">
              <Checkbox
                checked={isSelected}
                onCheckedChange={() => {
                  selection.toggle(cluster.id);
                  setLastSelectedId(cluster.id);
                }}
                ariaLabel={sprintf(__('Select cluster %s', 'alt-context'), cluster.id.slice(0, 8))}
              />
            </div>
            <header className="acx-cluster-card__header">
              <h3>{cluster.label || sprintf(__('Cluster %s', 'alt-context'), cluster.id.slice(0, 8))}</h3>
              <p>
                {sprintf(
                  _n('%d identity', '%d identities', cluster.identity_count, 'alt-context'),
                  cluster.identity_count,
                )}
              </p>
            </header>
            <div className="acx-cluster-card__faces">
              {cluster.sample_identities.length === 0 ? (
                <p>{__('No sample identities yet.', 'alt-context')}</p>
              ) : (
                cluster.sample_identities.slice(0, 4).map((identity) => (
                  <figure
                    key={identity.identity_id}
                    className="acx-cluster-card__face"
                    draggable
                    aria-label={sprintf(__('Move identity from media %d', 'alt-context'), identity.media_id)}
                    onDragStart={handleIdentityDragStart(cluster.id, identity.identity_id)}
                    onDragEnd={onFaceDragEnd}
                  >
                    <IdentityThumbnail identity={identity} mediaMeta={mediaMap[identity.media_id]} />
                  </figure>
                ))
              )}
            </div>
          </article>
        );
      })}
    </div>
  );
};
