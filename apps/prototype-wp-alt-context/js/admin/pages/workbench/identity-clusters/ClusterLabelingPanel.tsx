/**
 * ClusterLabelingPanel
 *
 * UI for labeling a cluster with a name, showing a grid of member faces for verification.
 */

import React, { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { __, sprintf } from '@wordpress/i18n';

import { fetchClusterMembers, updateClusterLabel } from '../../../api/recognition';
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
  const queryClient = useQueryClient();

  const { data: members, isLoading } = useQuery({
    queryKey: ['cluster-members', clusterId], // TODO: Add to queryKeys logic if reused
    queryFn: () => fetchClusterMembers(clusterId),
    enabled: Boolean(clusterId),
  });

  const labelMutation = useMutation({
    mutationFn: (newLabel: string) => updateClusterLabel(clusterId, newLabel),
    // Don't retry on client errors like 409 Conflict
    retry: false,
    onSuccess: () => {
      setError(null);
      void queryClient.invalidateQueries({ queryKey: queryKeys.clusters.all });
      void queryClient.invalidateQueries({ queryKey: queryKeys.suggestions.pending() });
      onLabel(labelInput);
    },
    onError: (err: Error) => {
      setError(getErrorMessage(err, labelInput));
    },
  });

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = labelInput.trim();
    if (!trimmed) {
      return;
    }
    // Clear any previous error when attempting a new save
    setError(null);
    labelMutation.mutate(trimmed);
  };

  const handleInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setLabelInput(e.target.value);
    // Clear error when user starts typing again
    if (error) {
      setError(null);
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

        <form onSubmit={handleSubmit} className="acx-cluster-labeling-panel__form">
          <label htmlFor="cluster-label-input">{__('Name', 'alt-context')}</label>
          <div className="acx-cluster-labeling-panel__input-group">
            <input
              id="cluster-label-input"
              type="text"
              value={labelInput}
              onChange={handleInputChange}
              placeholder={__('Enter name...', 'alt-context')}
              className="regular-text"
              disabled={labelMutation.isPending}
              autoFocus
            />
            <button
              type="submit"
              className="button button-primary"
              disabled={!labelInput.trim() || labelMutation.isPending}
            >
              {labelMutation.isPending ? __('Saving...', 'alt-context') : __('Save', 'alt-context')}
            </button>
          </div>
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
