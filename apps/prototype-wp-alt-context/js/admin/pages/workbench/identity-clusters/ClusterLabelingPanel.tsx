/**
 * ClusterLabelingPanel
 *
 * UI for labeling a cluster with a name, showing a grid of member faces for verification.
 */

import React, { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { __, sprintf } from '@wordpress/i18n';

import { fetchClusterMembers, listRecognitionClusters, mergeCluster, updateClusterLabel } from '../../../api/recognition';
import { queryKeys } from '../../../api/queryKeys';
import { FaceThumbnail } from '../../../../components/ui/FaceThumbnail';

interface ClusterLabelingPanelProps {
  clusterId: string;
  onClose: () => void;
  onLabel: (label: string) => void;
}

/**
 * Parse API error response to extract user-friendly message.
 */
const getErrorMessage = (error: unknown, label: string): string => {
  if (error instanceof Error) {
    // Check for 409 Conflict (duplicate label)
    if (error.message.includes('409') || error.message.toLowerCase().includes('conflict')) {
      return sprintf(
        __(
          'A person named "%s" already exists. Try a different name or merge with the existing cluster.',
          'alt-context',
        ),
        label,
      );
    }
    // Check for network errors
    if (error.message.includes('NetworkError') || error.message.includes('Failed to fetch')) {
      return __('Network error. Please check your connection and try again.', 'alt-context');
    }
    return error.message;
  }
  return __('An unexpected error occurred. Please try again.', 'alt-context');
};

export const ClusterLabelingPanel = ({ clusterId, onClose, onLabel }: ClusterLabelingPanelProps): React.JSX.Element => {
  const [labelInput, setLabelInput] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [duplicateMatch, setDuplicateMatch] = useState<{ id: string; label: string } | null>(null);
  const queryClient = useQueryClient();

  const { data: members, isLoading } = useQuery({
    queryKey: queryKeys.clusters.memberList(clusterId),
    queryFn: () => fetchClusterMembers(clusterId),
    enabled: Boolean(clusterId),
  });

  const labelMutation = useMutation({
    mutationFn: (newLabel: string) => updateClusterLabel(clusterId, newLabel),
    // Don't retry on client errors like 409 Conflict
    retry: false,
    onSuccess: () => {
      setError(null);
      setDuplicateMatch(null);
      void queryClient.invalidateQueries({ queryKey: queryKeys.clusters.all });
      void queryClient.invalidateQueries({ queryKey: queryKeys.media.identities() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.suggestions.pending() });
      onLabel(labelInput);
    },
    onError: (err: Error) => {
      setError(getErrorMessage(err, labelInput));
    },
  });

  const mergeMutation = useMutation({
    mutationFn: ({ targetClusterId, targetLabel }: { targetClusterId: string; targetLabel: string }) =>
      mergeCluster(clusterId, targetClusterId, targetLabel),
    retry: false,
    onSuccess: (_result, vars) => {
      setError(null);
      setDuplicateMatch(null);
      void queryClient.invalidateQueries({ queryKey: queryKeys.clusters.all });
      void queryClient.invalidateQueries({ queryKey: queryKeys.media.identities() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.suggestions.pending() });
      onLabel(vars.targetLabel);
    },
    onError: (err: Error) => {
      setError(getErrorMessage(err, labelInput));
    },
  });

  const findClusterByLabel = async (label: string): Promise<{ id: string; label: string } | null> => {
    const normalizedLabel = label.toLowerCase().trim();
    if (!normalizedLabel) {
      return null;
    }
    try {
      const results = await listRecognitionClusters({ search: label, limit: 10, labeled_only: true });
      const match = results.find((cluster) => cluster.id !== clusterId && cluster.label.toLowerCase() === normalizedLabel);
      if (match?.id && match.label) {
        return { id: match.id, label: match.label };
      }
    } catch {
      // Fall back to regular save path on lookup failures.
    }
    return null;
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = labelInput.trim();
    if (!trimmed) {
      return;
    }
    // Clear any previous error when attempting a new save.
    setError(null);
    setDuplicateMatch(null);

    // Avoid duplicate-label dead end by surfacing a merge suggestion first.
    const match = await findClusterByLabel(trimmed);
    if (match) {
      setDuplicateMatch(match);
      return;
    }

    labelMutation.mutate(trimmed);
  };

  const handleInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setLabelInput(e.target.value);
    // Clear error when user starts typing again
    if (error) {
      setError(null);
    }
    if (duplicateMatch) {
      setDuplicateMatch(null);
    }
  };

  return (
    <div className="acx-cluster-labeling-panel">
      <div className="acx-cluster-labeling-panel__header">
        <h2>{__('Name this person', 'alt-context')}</h2>
        <button type="button" className="acx-close-button" onClick={onClose} aria-label={__('Close', 'alt-context')}>
          ×
        </button>
      </div>

      <div className="acx-cluster-labeling-panel__content">
        <div className="acx-cluster-labeling-panel__grid">
          {isLoading ? (
            <p>{__('Loading faces...', 'alt-context')}</p>
          ) : members && members.length > 0 ? (
            members.map((member) => (
              <div key={member.identity_id} className="acx-cluster-labeling-panel__face">
                {member.thumbnail_url ? (
                  <img src={member.thumbnail_url} alt="" className="acx-face-thumbnail" />
                ) : member.media_url && member.bbox ? (
                  <FaceThumbnail mediaUrl={member.media_url} bbox={member.bbox} size="lg" />
                ) : (
                  <div className="acx-face-thumbnail acx-face-thumbnail--placeholder" />
                )}
              </div>
            ))
          ) : (
            <p>{__('No members found.', 'alt-context')}</p>
          )}
        </div>

        <form
          onSubmit={(event) => {
            void handleSubmit(event);
          }}
          className="acx-cluster-labeling-panel__form"
        >
          <label htmlFor="cluster-label-input">{__('Name', 'alt-context')}</label>
          <div className="acx-cluster-labeling-panel__input-group">
            <input
              id="cluster-label-input"
              type="text"
              value={labelInput}
              onChange={handleInputChange}
              placeholder={__('Enter name...', 'alt-context')}
              className="regular-text"
              disabled={labelMutation.isPending || mergeMutation.isPending}
              autoFocus
            />
            <button
              type="submit"
              className="button button-primary"
              disabled={!labelInput.trim() || labelMutation.isPending || mergeMutation.isPending}
            >
              {labelMutation.isPending ? __('Saving...', 'alt-context') : mergeMutation.isPending ? __('Merging...', 'alt-context') : __('Save', 'alt-context')}
            </button>
          </div>
          {duplicateMatch && (
            <div className="acx-cluster-labeling-panel__suggestion" role="status" aria-live="polite">
              <p className="acx-cluster-labeling-panel__suggestion-text">
                {sprintf(__('Is this %s?', 'alt-context'), duplicateMatch.label)}
              </p>
              <div className="acx-cluster-labeling-panel__suggestion-actions">
                <button
                  type="button"
                  className="button button-primary"
                  disabled={mergeMutation.isPending || labelMutation.isPending}
                  onClick={() =>
                    mergeMutation.mutate({
                      targetClusterId: duplicateMatch.id,
                      targetLabel: duplicateMatch.label,
                    })
                  }
                >
                  {__('Yes', 'alt-context')}
                </button>
                <button
                  type="button"
                  className="button"
                  disabled={mergeMutation.isPending || labelMutation.isPending}
                  onClick={() => setDuplicateMatch(null)}
                >
                  {__('No', 'alt-context')}
                </button>
              </div>
            </div>
          )}
          {error && (
            <p className="acx-cluster-labeling-panel__error" role="alert">
              {error}
            </p>
          )}
        </form>
      </div>
    </div>
  );
};
