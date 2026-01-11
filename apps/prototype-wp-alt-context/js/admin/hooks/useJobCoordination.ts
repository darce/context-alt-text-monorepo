import { useState, useEffect, useRef } from 'react';

export interface JobCoordination {
  isPrimary: boolean;
  channel: BroadcastChannel | null;
}

const COORDINATION_CHANNEL_PREFIX = 'alt-context-job-';

/**
 * Hook to coordinate job progress tracking across multiple tabs.
 *
 * Uses BroadcastChannel to:
 * 1. Elect a "Primary" tab that manages the SSE connection.
 * 2. Synchronize progress updates to "Observer" tabs.
 * 3. Handle handoff when the Primary tab is closed.
 *
 * @param jobId - The UUID of the job to coordinate.
 */
export const useJobCoordination = (jobId: string | null): JobCoordination => {
  const [isPrimary, setIsPrimary] = useState(false);
  const channelRef = useRef<BroadcastChannel | null>(null);
  const tabId = useRef(crypto.randomUUID());

  const isPrimaryRef = useRef(false);

  useEffect(() => {
    if (!jobId) {
      setIsPrimary(false);
      isPrimaryRef.current = false;
      return;
    }

    const channelName = `${COORDINATION_CHANNEL_PREFIX}${jobId}`;
    const channel = new BroadcastChannel(channelName);
    channelRef.current = channel;

    // Start by assuming we might be primary
    // In a real world scenario, you'd wait ~50ms to see if a PONG comes back
    // but for this prototype, we'll start as primary and yield if challenged.
    const setPrimaryState = (val: boolean) => {
      setIsPrimary(val);
      isPrimaryRef.current = val;
    };

    setPrimaryState(true);

    channel.onmessage = (event) => {
      const { type, payload } = event.data as { type: string; payload: { tabId: string } };

      if (type === 'PING_PRIMARY' && isPrimaryRef.current && payload.tabId !== tabId.current) {
        // Someone is asking if a primary exists, and we are primary
        channel.postMessage({ type: 'PONG_PRIMARY', payload: { tabId: tabId.current } });
      } else if (type === 'PONG_PRIMARY' && payload.tabId !== tabId.current) {
        // Someone else is already primary
        setPrimaryState(false);
      } else if (type === 'PRIMARY_CLOSING' && !isPrimaryRef.current) {
        // Primary is leaving, try to become primary
        setPrimaryState(true);
      }
    };

    // Broadcast our presence and check if someone is already primary
    const currentTabId = tabId.current;
    channel.postMessage({ type: 'PING_PRIMARY', payload: { tabId: currentTabId } });

    return () => {
      if (isPrimaryRef.current) {
        channel.postMessage({ type: 'PRIMARY_CLOSING', payload: { tabId: currentTabId } });
      }
      channel.close();
      channelRef.current = null;
    };
  }, [jobId]);

  return { isPrimary, channel: channelRef.current };
};
