/**
 * React hook for subscribing to cluster SSE events.
 */

import { useEffect } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { getEndpoint, getConfig } from '../api/config';
import { stripTrailingSlash } from '../utils/http';

/**
 * Subscribe to real-time cluster events via SSE.
 *
 * @param tenantId - Tenant ID for scoping
 * @param enabled - Whether to connect
 */
export function useClusterEvents(tenantId: string, enabled = true): void {
  const queryClient = useQueryClient();

  useEffect(() => {
    if (!enabled || !tenantId) {
      return;
    }

    let base: string;
    try {
      base = getEndpoint('workbenchRecognitionClusters');
    } catch {
      return;
    }

    const config = getConfig();
    const url = new URL(`${stripTrailingSlash(base)}/events`, window.location.origin);
    url.searchParams.set('tenant_id', tenantId);

    // Add nonce for authentication since EventSource doesn't support headers
    if (config.nonce) {
      url.searchParams.set('_wpnonce', config.nonce);
    }

    const eventSource = new EventSource(url.toString());

    const handleEvent = (event: MessageEvent) => {
      try {
        const data = JSON.parse(event.data);
        const eventType = data.event_type;

        // Invalidate relevant queries based on event type
        if (
          eventType === 'suggestions_updated' ||
          eventType === 'cluster_merged' ||
          eventType === 'cluster_split' ||
          eventType === 'cluster_updated'
        ) {
          void queryClient.invalidateQueries({ queryKey: ['identity-suggestions'] });
        }

        if (eventType === 'cluster_updated' || eventType === 'cluster_merged' || eventType === 'cluster_split' || eventType === 'suggestions_updated') {
          void queryClient.invalidateQueries({ queryKey: ['clusters'] });
          void queryClient.invalidateQueries({ queryKey: ['recognition-clusters'] });
          void queryClient.invalidateQueries({ queryKey: ['recognition-cluster'] });
        }
      } catch (err) {
        console.error('Failed to parse cluster event:', err);
      }
    };

    eventSource.onmessage = handleEvent;
    eventSource.onerror = (err) => {
      console.error('Cluster EventSource error:', err);
    };

    return () => {
      eventSource.close();
    };
  }, [tenantId, enabled, queryClient]);
}
