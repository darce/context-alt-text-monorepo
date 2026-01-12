/**
 * Prompt to guide users to curate top unlabeled clusters.
 *
 * This helps "bootstrap" identity suggestions by encouraging users
 * to provide initial labels for high-member clusters.
 */

import React from 'react';
import { useQuery } from '@tanstack/react-query';
import { __, _n, sprintf } from '@wordpress/i18n';

import { fetchApi } from '../../../utils/http';
import { getEndpoint, getConfig } from '../../../api/config';
import { queryKeys } from '../../../api/queryKeys';
import type { ClusterSummary } from '../../../api/recognition/types';

interface CurateTopClustersPromptProps {
  /** Tenant ID for API scoping */
  tenantId: string;
}

/**
 * Displays a prompt to curated top unlabeled clusters if suggestions are lacking.
 */
export const CurateTopClustersPrompt = ({ tenantId }: CurateTopClustersPromptProps): React.JSX.Element | null => {
  const { data: topClusters, isLoading } = useQuery<ClusterSummary[]>({
    queryKey: queryKeys.clusters.topUnlabeled(tenantId),
    queryFn: async () => {
      const base = getEndpoint('recognitionClusters');
      const url = `${base}/top-unlabeled?limit=3&tenant_id=${tenantId}`;
      return fetchApi<ClusterSummary[]>(url, {
        restNonce: getConfig().nonce,
      });
    },
    staleTime: 60000,
  });

  if (isLoading || !topClusters || topClusters.length === 0) {
    return null;
  }

  return (
    <div className="acx-identity-curation-prompt">
      <div className="acx-identity-curation-prompt__content">
        <h4 className="acx-identity-curation-prompt__title">{__('Help improve suggestions', 'alt-context')}</h4>
        <p className="acx-identity-curation-prompt__description">
          {__(
            'Labeling these large clusters first will help the system suggest names for other people automatically.',
            'alt-context',
          )}
        </p>
        <ul className="acx-identity-curation-prompt__list">
          {topClusters.map((cluster) => (
            <li key={cluster.id} className="acx-identity-curation-prompt__item">
              <strong>{cluster.label}</strong>
              <span className="acx-identity-curation-prompt__meta">
                {sprintf(
                  _n('%d face', '%d faces', cluster.identity_count || 0, 'alt-context'),
                  cluster.identity_count || 0,
                )}
              </span>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
};
