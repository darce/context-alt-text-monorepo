/**
 * React hook for subscribing to cluster SSE events.
 */

import { useEffect } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { getEndpoint, getConfig } from '../api/config';
import { queryKeys } from '../api/queryKeys';
import { stripTrailingSlash } from '../utils/http';

/**
 * Subscribe to real-time cluster events via SSE.
 *
 * @param tenantId - Tenant ID for scoping
 * @param enabled - Whether to connect
 */
export const useClusterEvents = (tenantId: string, enabled = true): void => {
  const queryClient = useQueryClient();

  useEffect(() => {
    if (!enabled || !tenantId) {
      return;
    }

    let base: string;
    try {
      base = getEndpoint('recognitionClustersEvents', 'recognitionClusters');
    } catch {
      return;
    }

    const config = getConfig();
    const normalizedBase = stripTrailingSlash(base);
    const streamUrl = normalizedBase.endsWith('/events') ? normalizedBase : `${normalizedBase}/events`;
    const url = new URL(streamUrl, window.location.origin);
    url.searchParams.set('tenant_id', tenantId);

    // Add nonce for authentication since EventSource doesn't support headers
    if (config.nonce) {
      url.searchParams.set('_wpnonce', config.nonce);
    }

    const eventSource = new EventSource(url.toString());
    let closedLogged = false;

    const handleEvent = (event: MessageEvent) => {
      try {
        const data = JSON.parse(event.data as string) as { event_type: string };
        const eventType = data.event_type;

        // Invalidate relevant queries based on event type
        if (
          eventType === 'suggestions_updated' ||
          eventType === 'cluster_merged' ||
          eventType === 'cluster_split' ||
          eventType === 'cluster_updated'
        ) {
          void queryClient.invalidateQueries({ queryKey: queryKeys.suggestions.identity() });
        }

        if (
          eventType === 'cluster_updated' ||
          eventType === 'cluster_merged' ||
          eventType === 'cluster_split' ||
          eventType === 'suggestions_updated'
        ) {
          void queryClient.invalidateQueries({ queryKey: queryKeys.clusters.all });
        }
      } catch (err) {
        console.error('Failed to parse cluster event:', err);
      }
    };

    eventSource.onmessage = handleEvent;
    eventSource.onerror = (err) => {
      if (eventSource.readyState === EventSource.CLOSED) {
        eventSource.close();
        if (!closedLogged) {
          closedLogged = true;
          console.warn('Cluster EventSource closed; live updates disabled until next refresh.');
        }
        return;
      }
      console.error('Cluster EventSource error:', err);
    };

    return () => {
      eventSource.close();
    };
  }, [tenantId, enabled, queryClient]);
};
