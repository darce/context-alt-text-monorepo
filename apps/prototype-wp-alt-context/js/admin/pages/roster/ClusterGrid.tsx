import React from 'react';
import { __, _n, sprintf } from '@wordpress/i18n';

import type { ClusterIdentity, ClusterSummary } from '../../api/recognitionApi';
import type { MediaMap } from './hooks/useClusterMediaMap';
import { IdentityThumbnail } from './IdentityThumbnail';

type Props = {
  clusters: ClusterSummary[];
  isLoading: boolean;
  isError: boolean;
  onRetry: () => void;
  mediaMap: MediaMap;
  onSelectCluster: (cluster: ClusterSummary) => void;
  onIdentityDragStart: (clusterId: string, identityId: string) => void;
  onFaceDragEnd: () => void;
  onDropTargetChange: (target: string | 'discard' | null) => void;
  onDropFace: (clusterId: string | null) => void;
  dropTarget: string | 'discard' | null;
  isDragging: boolean;
};

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
}: Props): React.JSX.Element => {
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
      <p>{__('No clusters have been created yet. Run a scan from the workbench to get started.', 'alt-context')}</p>
    );
  }

  return (
    <div className="acx-cluster-grid">
      {clusters.map((cluster) => (
        <article
          key={cluster.id}
          className={`acx-cluster-card${dropTarget === cluster.id ? ' is-drop-target' : ''}`}
          onClick={() => onSelectCluster(cluster)}
          onKeyDown={(event) => {
            if (event.key === 'Enter' || event.key === ' ') {
              event.preventDefault();
              onSelectCluster(cluster);
            }
          }}
          onDragOver={(event) => {
            if (!isDragging) {
              return;
            }
            event.preventDefault();
            onDropTargetChange(cluster.id);
          }}
          onDragLeave={() => {
            if (dropTarget === cluster.id) {
              onDropTargetChange(null);
            }
          }}
          onDrop={(event) => {
            if (!isDragging) {
              return;
            }
            event.preventDefault();
            onDropFace(cluster.id);
          }}
          role="button"
          tabIndex={0}
        >
          <header className="acx-cluster-card__header">
            <h3>{cluster.label || sprintf(__('Cluster %s', 'alt-context'), cluster.id.slice(0, 8))}</h3>
          <p>{sprintf(_n('%d identity', '%d identities', cluster.identity_count, 'alt-context'), cluster.identity_count)}</p>
          </header>
          <div className="acx-cluster-card__faces">
            {cluster.sample_identities.length === 0 ? (
              <p>{__('No sample identities yet.', 'alt-context')}</p>
            ) : (
              cluster.sample_identities.slice(0, 4).map((identity) => (
                <figure
                  key={identity.id}
                  className="acx-cluster-card__face"
                  draggable
                  aria-label={sprintf(__('Move identity from media %d', 'alt-context'), identity.media_id)}
                  onDragStart={(event) => {
                    event.dataTransfer?.setData('text/plain', identity.id);
                    event.dataTransfer?.setDragImage(event.currentTarget, 0, 0);
                    onIdentityDragStart(cluster.id, identity.id);
                  }}
                  onDragEnd={onFaceDragEnd}
                >
                  <IdentityThumbnail identity={identity} mediaMeta={mediaMap[identity.media_id]} />
                </figure>
              ))
            )}
          </div>
        </article>
      ))}
    </div>
  );
};
