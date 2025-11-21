import React from 'react';
import { __ } from '@wordpress/i18n';
import { useMutation, useQueryClient } from '@tanstack/react-query';

import {
  mergeCluster,
  updateClusterLabel,
  type DetectedIdentity,
  type MediaIdentitiesResponse,
} from '../../api/recognitionApi';

type Props = {
  identities: DetectedIdentity[];
  mediaId: number;
};

type ClusterGroup = {
  key: string;
  clusterId: string | null;
  label: string | null;
  isAutoLabel: boolean;
  members: DetectedIdentity[];
};

const formatClusterLabel = (
  clusterId: string | null,
  rawLabel: string | null,
  isAutoLabel: boolean,
): string | null => {
  if (!clusterId) {
    return rawLabel;
  }

  if (rawLabel && !isAutoLabel) {
    return rawLabel;
  }

  const normalizedId = clusterId.replace(/-/g, '');
  return `cluster-${normalizedId}`;
};

export const IdentityClusterList = ({ identities }: Props): React.JSX.Element => {
  const clusters = React.useMemo<ClusterGroup[]>(() => {
    const groups = new Map<string, ClusterGroup>();
    identities.forEach((identity) => {
      const clusterKey = identity.cluster_id ?? `identity-${identity.id}`;
      if (!groups.has(clusterKey)) {
        groups.set(clusterKey, {
          key: clusterKey,
          clusterId: identity.cluster_id ?? null,
          label: identity.cluster_label ?? null,
          isAutoLabel: Boolean(identity.is_auto_label),
          members: [],
        });
      }
      groups.get(clusterKey)!.members.push(identity);
    });
    return Array.from(groups.values());
  }, [identities]);

  if (clusters.length === 0) {
    return <p className="acx-identity-clusters__empty">{__('No identities detected yet.', 'alt-context')}</p>;
  }

  return (
    <div className="acx-identity-clusters">
      {clusters.map((cluster) => (
        <IdentityClusterItem key={cluster.key} cluster={cluster} />
      ))}
    </div>
  );
};

type ClusterItemProps = {
  cluster: ClusterGroup;
};

const IdentityClusterItem = ({ cluster }: ClusterItemProps): React.JSX.Element => {
  const queryClient = useQueryClient();
  const [isEditing, setIsEditing] = React.useState(false);
  const derivedLabel = React.useMemo(
    () => formatClusterLabel(cluster.clusterId, cluster.label, cluster.isAutoLabel),
    [cluster.clusterId, cluster.label, cluster.isAutoLabel],
  );
  const [labelInput, setLabelInput] = React.useState(derivedLabel ?? '');
  React.useEffect(() => {
    setLabelInput(derivedLabel ?? '');
  }, [derivedLabel]);
  const [error, setError] = React.useState<string | null>(null);

  const clusterEditableId = React.useMemo(() => {
    if (cluster.clusterId) {
      return cluster.clusterId;
    }
    const memberWithCluster = cluster.members.find((member) => member.cluster_id);
    return memberWithCluster?.cluster_id ?? null;
  }, [cluster.clusterId, cluster.members]);

  const invalidateIdentities = React.useCallback(() => {
    queryClient.invalidateQueries({ queryKey: ['media-identities'] });
  }, [queryClient]);

  const updateCachedClusterLabel = React.useCallback(
    (clusterId: string, nextLabel: string) => {
      queryClient.setQueriesData<MediaIdentitiesResponse>(
        { queryKey: ['media-identities'] },
        (current) => {
          if (!current) {
            return current;
          }

          let changed = false;
          const nextMap: MediaIdentitiesResponse['identities_by_media'] = {};

          for (const [mediaKey, identities] of Object.entries(current.identities_by_media)) {
            let mediaChanged = false;
            const updatedIdentities = identities.map((identity) => {
              if (identity.cluster_id !== clusterId) {
                return identity;
              }
              mediaChanged = true;
              changed = true;
              return {
                ...identity,
                cluster_label: nextLabel,
                is_auto_label: false,
              };
            });
            nextMap[mediaKey] = mediaChanged ? updatedIdentities : identities;
          }

          if (!changed) {
            return current;
          }

          return { identities_by_media: nextMap };
        },
      );
    },
    [queryClient],
  );

  const renameMutation = useMutation({
    mutationFn: (label: string) => updateClusterLabel(clusterEditableId as string, label),
    onSuccess: (_data, updatedLabel) => {
      if (clusterEditableId) {
        updateCachedClusterLabel(clusterEditableId, updatedLabel);
      }
      invalidateIdentities();
      setIsEditing(false);
      setError(null);
    },
  });

  const mergeMutation = useMutation({
    mutationFn: (label: string) => mergeCluster(clusterEditableId as string, label),
    onSuccess: (_data, updatedLabel) => {
      if (clusterEditableId) {
        updateCachedClusterLabel(clusterEditableId, updatedLabel);
      }
      invalidateIdentities();
      setIsEditing(false);
      setError(null);
    },
  });

  const representative = cluster.members[0];
  const labelText = derivedLabel ?? __('Unlabeled identity', 'alt-context');
  const canEdit = Boolean(clusterEditableId);

  const startEditing = () => {
    if (!canEdit) {
      return;
    }
    setLabelInput(labelText);
    setIsEditing(true);
    setError(null);
  };

  const handleSave = () => {
    if (!canEdit) {
      return;
    }
    const trimmed = labelInput.trim();
    if (!trimmed) {
      setError(__('Provide a label before saving.', 'alt-context'));
      return;
    }
    if (cluster.isAutoLabel) {
      mergeMutation.mutate(trimmed);
    } else {
      renameMutation.mutate(trimmed);
    }
  };

  const isPending = renameMutation.isPending || mergeMutation.isPending;

  return (
    <div className="acx-identity-cluster">
      <div className="acx-identity-cluster__preview">
        {representative?.thumbnail_url ? (
          <img
            src={representative.thumbnail_url}
            alt={__('Detected identity thumbnail', 'alt-context')}
            className="acx-identity-cluster__thumb"
          />
        ) : (
          <span className="acx-identity-cluster__thumb acx-identity-cluster__thumb--placeholder" />
        )}
        {cluster.members.length > 1 && (
          <span className="acx-identity-cluster__count">+{cluster.members.length - 1}</span>
        )}
      </div>

      <div className="acx-identity-cluster__info">
        {!isEditing ? (
          <>
            {canEdit && !cluster.label ? (
              <button
                type="button"
                className="acx-identity-cluster__label acx-identity-cluster__label--action"
                onClick={startEditing}
              >
                {labelText}
              </button>
            ) : (
              <span className="acx-identity-cluster__label">{labelText}</span>
            )}
            {canEdit && (
              <button type="button" className="acx-identity-cluster__action" onClick={startEditing}>
                {!cluster.label || cluster.isAutoLabel
                  ? __('Name this person', 'alt-context')
                  : __('Edit label', 'alt-context')}
              </button>
            )}
          </>
        ) : (
          <div className="acx-identity-cluster__edit">
            <input
              type="text"
              className="acx-identity-cluster__input"
              value={labelInput}
              onChange={(event) => setLabelInput(event.target.value)}
              placeholder={__('Enter a name…', 'alt-context')}
            />
            <button
              type="button"
              className="acx-identity-cluster__save"
              onClick={handleSave}
              disabled={isPending}
            >
              {isPending ? __('Saving…', 'alt-context') : __('Save', 'alt-context')}
            </button>
            <button
              type="button"
              className="acx-identity-cluster__cancel"
              onClick={() => {
                setIsEditing(false);
                setError(null);
              }}
            >
              {__('Cancel', 'alt-context')}
            </button>
          </div>
        )}
      </div>
      {error && <p className="acx-identity-cluster__error">{error}</p>}
    </div>
  );
};
