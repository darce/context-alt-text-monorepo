import React from 'react';
import { __, sprintf } from '@wordpress/i18n';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import {
  fetchClusterLabels,
  fetchIdentitySuggestions,
  mergeCluster,
  revertMergeCluster,
  updateClusterLabel,
  reassignClusterIdentity,
  splitCluster,
  type ClusterSuggestion,
  type DetectedIdentity,
  type IdentitySuggestionsResponse,
  type MediaIdentitiesResponse,
  type MergeClusterResponse,
} from '../../api/recognitionApi';
import { Combobox, type ComboboxOption } from '../../../components/ui/combobox';

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

const formatClusterLabel = (clusterId: string | null, rawLabel: string | null, isAutoLabel: boolean): string | null => {
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
  const [lastMerge, setLastMerge] = React.useState<MergeClusterResponse | null>(null);

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
      queryClient.setQueriesData<MediaIdentitiesResponse>({ queryKey: ['media-identities'] }, (current) => {
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
      });
    },
    [queryClient],
  );

  const { data: existingLabels } = useQuery({
    queryKey: ['cluster-labels'],
    queryFn: fetchClusterLabels,
    staleTime: 30000, // 30 seconds
  });

  const anchorIdentityId = cluster.members[0]?.id;
  const { data: identitySuggestions, isLoading: suggestionsLoading } = useQuery<IdentitySuggestionsResponse>({
    queryKey: ['identity-suggestions', anchorIdentityId],
    queryFn: () => fetchIdentitySuggestions(anchorIdentityId as string, 5), // Limit to top 5
    enabled: Boolean(anchorIdentityId && isEditing),
    staleTime: 30000,
  });

  const comboboxOptions = React.useMemo<ComboboxOption[]>(() => {
    const options: ComboboxOption[] = [];
    const seen = new Set<string>();

    // Sort suggestions by similarity (descending)
    const sortedSuggestions = (identitySuggestions?.matches ?? []).sort((a, b) => b.similarity - a.similarity);

    sortedSuggestions.forEach((match: ClusterSuggestion) => {
      const normalizedLabel = match.label?.trim() ?? '';
      if (!normalizedLabel) {
        return;
      }
      const key = normalizedLabel.toLowerCase();
      if (seen.has(key)) {
        return;
      }
      seen.add(key);
      options.push({
        value: match.cluster_id,
        label: normalizedLabel,
        group: 'Suggested',
        similarity: match.similarity,
        identityCount: match.identity_count,
      });
    });

    (existingLabels ?? []).forEach((label) => {
      if (!label) {
        return;
      }
      const key = label.toLowerCase();
      if (seen.has(key)) {
        return;
      }
      seen.add(key);
      options.push({ value: label, label, group: 'All Labels' });
    });

    return options;
  }, [existingLabels, identitySuggestions]);

  const renameMutation = useMutation({
    mutationFn: (label: string) => updateClusterLabel(clusterEditableId as string, label),
    onSuccess: (_data, updatedLabel) => {
      if (clusterEditableId) {
        updateCachedClusterLabel(clusterEditableId, updatedLabel);
      }
      invalidateIdentities();
      queryClient.invalidateQueries({ queryKey: ['cluster-labels'] });
      setIsEditing(false);
      setError(null);
      setLastMerge(null);
    },
    onError: (err: Error) => {
      // Fallback for 409 Conflict if autocomplete wasn't used
      if (err.message.includes('409')) {
        setError(__('Label already exists. Use the dropdown to merge.', 'alt-context'));
      } else {
        setError(err.message);
      }
    },
  });

  const mergeMutation = useMutation({
    mutationFn: (label: string) => mergeCluster(clusterEditableId as string, label),
    onSuccess: (result) => {
      if (clusterEditableId) {
        updateCachedClusterLabel(clusterEditableId, result.target_label ?? labelInput);
      }
      setLastMerge(result);
      invalidateIdentities();
      queryClient.invalidateQueries({ queryKey: ['cluster-labels'] });
      setIsEditing(false);
      setError(null);
    },
    onError: (err: Error) => {
      setError(err.message);
    },
  });

  const revertMergeMutation = useMutation({
    mutationFn: (payload: MergeClusterResponse) =>
      revertMergeCluster({
        targetClusterId: payload.target_id,
        movedIdentityIds: payload.moved_identity_ids,
        sourceLabel: payload.source_label ?? cluster.label ?? derivedLabel ?? null,
      }),
    onSuccess: () => {
      setLastMerge(null);
      invalidateIdentities();
      queryClient.invalidateQueries({ queryKey: ['cluster-labels'] });
      setError(null);
    },
    onError: (err: Error) => {
      setError(err.message);
    },
  });

  const reassignMutation = useMutation({
    mutationFn: async (identityIds: string[]) => {
      for (const id of identityIds) {
        await reassignClusterIdentity({ identityId: id, targetClusterId: null });
      }
    },
    onSuccess: () => {
      invalidateIdentities();
      queryClient.invalidateQueries({ queryKey: ['cluster-labels'] });
      setError(null);
    },
    onError: (err: Error) => {
      setError(err.message);
    },
  });

  const splitMutation = useMutation({
    mutationFn: (clusterId: string) => splitCluster(clusterId),
    onSuccess: (data) => {
      invalidateIdentities();
      queryClient.invalidateQueries({ queryKey: ['cluster-labels'] });
      setError(null);
    },
    onError: (err: Error) => {
      setError(err.message);
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
    setLastMerge(null);
  };

  const handleSave = async () => {
    if (!canEdit) {
      return;
    }
    const trimmed = labelInput.trim();
    if (!trimmed) {
      setError(__('Provide a label before saving.', 'alt-context'));
      return;
    }

    const suggestionLabels =
      (identitySuggestions?.matches ?? [])
        .map((match) => match.label)
        .filter((label): label is string => Boolean(label)) ?? [];

    // Ensure we have the latest labels before deciding to merge
    let labels: string[] = existingLabels ?? [];
    if (!existingLabels) {
      try {
        labels = await queryClient.fetchQuery({
          queryKey: ['cluster-labels'],
          queryFn: fetchClusterLabels,
        });
      } catch {
        labels = [];
      }
    }

    const combinedLabels = Array.from(new Set([...labels, ...suggestionLabels]));

    // Check if label exists (case-insensitive) to trigger merge
    const targetLabel = combinedLabels.find((l) => l.toLowerCase() === trimmed.toLowerCase());

    if (targetLabel) {
      // If label exists, merge into it
      if (targetLabel !== cluster.label) {
        if (confirm(__('Merge this cluster into existing "' + targetLabel + '"?', 'alt-context'))) {
          mergeMutation.mutate(targetLabel);
        }
      } else {
        setIsEditing(false); // No change
      }
    } else {
      // Otherwise rename
      if (cluster.isAutoLabel) {
        // Renaming an auto-label is effectively a "merge into new label" or just a rename
        // But since the label doesn't exist, it's a rename.
        renameMutation.mutate(trimmed);
      } else {
        renameMutation.mutate(trimmed);
      }
    }
  };

  const isReverting = revertMergeMutation.isPending;
  const isPending =
    renameMutation.isPending ||
    mergeMutation.isPending ||
    isReverting ||
    reassignMutation.isPending ||
    splitMutation.isPending;

  const renderOption = (option: ComboboxOption) => {
    const similarity = option.similarity as number | undefined;
    const count = option.identityCount as number | undefined;

    return (
      <div style={{ display: 'flex', alignItems: 'center', width: '100%' }}>
        <span>{option.label}</span>
        {(similarity !== undefined || count !== undefined) && (
          <div className="acx-identity-cluster__suggestion-meta">
            {similarity !== undefined && (
              <span
                className={`acx-identity-cluster__match-score ${
                  similarity > 0.8
                    ? 'acx-identity-cluster__match-score--high'
                    : 'acx-identity-cluster__match-score--medium'
                }`}
              >
                {Math.round(similarity * 100)}%
              </span>
            )}
            {count !== undefined && (
              <span className="acx-identity-cluster__member-count">
                ({count} {count === 1 ? __('item', 'alt-context') : __('items', 'alt-context')})
              </span>
            )}
          </div>
        )}
      </div>
    );
  };

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
              <>
                <button type="button" className="acx-identity-cluster__action" onClick={startEditing}>
                  {!cluster.label || cluster.isAutoLabel
                    ? __('Name this person', 'alt-context')
                    : __('Edit label', 'alt-context')}
                </button>
                <button
                  type="button"
                  className="acx-identity-cluster__action"
                  onClick={() => {
                    // eslint-disable-next-line no-alert
                    if (
                      window.confirm(
                        __(
                          'Are you sure this is not the correct person? This will remove these items from the cluster.',
                          'alt-context',
                        ),
                      )
                    ) {
                      reassignMutation.mutate(cluster.members.map((m) => m.id));
                    }
                  }}
                  disabled={isPending}
                >
                  {__('Wrong person', 'alt-context')}
                </button>
                {cluster.clusterId && (
                  <button
                    type="button"
                    className="acx-identity-cluster__action"
                    onClick={() => {
                      // eslint-disable-next-line no-alert
                      if (
                        window.confirm(
                          __(
                            'Attempt to split this cluster into two groups based on visual similarity?',
                            'alt-context',
                          ),
                        )
                      ) {
                        splitMutation.mutate(cluster.clusterId as string);
                      }
                    }}
                    disabled={isPending}
                  >
                    {__('Split cluster', 'alt-context')}
                  </button>
                )}
              </>
            )}
          </>
        ) : (
          <div className="acx-identity-cluster__edit">
            <Combobox
              value={labelInput}
              onValueChange={(nextValue) => {
                setLabelInput(nextValue);
                setError(null);
              }}
              options={comboboxOptions}
              placeholder={__('Enter a name…', 'alt-context')}
              emptyMessage={__('No matching labels. Press Enter to keep your new name.', 'alt-context')}
              ariaLabel={__('Cluster label', 'alt-context')}
              disabled={isPending}
              isLoading={suggestionsLoading}
              renderOption={renderOption}
            />
            <button type="button" className="acx-identity-cluster__save" onClick={handleSave} disabled={isPending}>
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
      {lastMerge ? (
        <div className="acx-identity-cluster__undo">
          <span>
            {sprintf(
              /* translators: %s: target cluster label */
              __('Merged into "%s".', 'alt-context'),
              lastMerge.target_label ?? __('existing cluster', 'alt-context'),
            )}
          </span>
          <button
            type="button"
            onClick={() => revertMergeMutation.mutate(lastMerge)}
            disabled={revertMergeMutation.isPending}
          >
            {revertMergeMutation.isPending ? __('Reverting…', 'alt-context') : __('Undo merge', 'alt-context')}
          </button>
        </div>
      ) : null}
      {error && <p className="acx-identity-cluster__error">{error}</p>}
    </div>
  );
};
