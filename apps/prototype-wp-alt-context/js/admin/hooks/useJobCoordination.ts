import { useState, useEffect, useRef } from 'react';

export interface JobCoordination {
  isPrimary: boolean;
  channel: BroadcastChannel | null;
}

const COORDINATION_CHANNEL_PREFIX = 'alt-context-job-';
const ELECTION_JITTER_MS = 200;
const PRIMARY_HANDOFF_DELAY_MS = 1200;
const HEARTBEAT_INTERVAL_MS = 30_000;
const HEARTBEAT_TIMEOUT_MS = HEARTBEAT_INTERVAL_MS * 2;
const HEARTBEAT_CHECK_INTERVAL_MS = 5000;

const supportsBroadcastChannel = (): boolean => typeof BroadcastChannel === 'function';

const generateTabId = (): string => {
  if (typeof globalThis.crypto?.randomUUID === 'function') {
    return globalThis.crypto.randomUUID();
  }
  return `tab-${Date.now()}-${Math.random().toString(16).slice(2, 10)}`;
};

interface CoordinationMessage {
  type: 'PING_PRIMARY' | 'PONG_PRIMARY' | 'PRIMARY_CLAIM' | 'PRIMARY_HEARTBEAT' | 'PRIMARY_CLOSING';
  payload: { tabId: string; timestamp?: number };
}

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
  const [channel, setChannel] = useState<BroadcastChannel | null>(null);
  const channelRef = useRef<BroadcastChannel | null>(null);
  const tabId = useRef(generateTabId());

  const isPrimaryRef = useRef(false);
  const lastHeartbeatRef = useRef<number | null>(null);
  const electionTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const heartbeatIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const heartbeatCheckRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    if (!jobId) {
      setIsPrimary(false);
      isPrimaryRef.current = false;
      setChannel(null);
      return;
    }

    if (!supportsBroadcastChannel()) {
      setIsPrimary(true);
      isPrimaryRef.current = true;
      setChannel(null);
      return;
    }

    const channelName = `${COORDINATION_CHANNEL_PREFIX}${jobId}`;
    let coordinationChannel: BroadcastChannel;
    try {
      coordinationChannel = new BroadcastChannel(channelName);
    } catch {
      setIsPrimary(true);
      isPrimaryRef.current = true;
      setChannel(null);
      return;
    }
    channelRef.current = coordinationChannel;
    lastHeartbeatRef.current = null;
    setIsPrimary(false);
    isPrimaryRef.current = false;
    setChannel(coordinationChannel);

    const setPrimaryState = (val: boolean) => {
      setIsPrimary(val);
      isPrimaryRef.current = val;
    };

    const currentTabId = tabId.current;
    const shouldYieldTo = (otherTabId: string) => otherTabId < currentTabId;

    const clearElectionTimeout = () => {
      if (electionTimeoutRef.current) {
        clearTimeout(electionTimeoutRef.current);
        electionTimeoutRef.current = null;
      }
    };

    const stopHeartbeat = () => {
      if (heartbeatIntervalRef.current) {
        clearInterval(heartbeatIntervalRef.current);
        heartbeatIntervalRef.current = null;
      }
    };

    const sendHeartbeat = () => {
      coordinationChannel.postMessage({
        type: 'PRIMARY_HEARTBEAT',
        payload: { tabId: currentTabId, timestamp: Date.now() },
      });
    };

    const startHeartbeat = () => {
      sendHeartbeat();
      heartbeatIntervalRef.current = setInterval(sendHeartbeat, HEARTBEAT_INTERVAL_MS);
    };

    const becomePrimary = () => {
      clearElectionTimeout();
      setPrimaryState(true);
      lastHeartbeatRef.current = Date.now();
      coordinationChannel.postMessage({ type: 'PRIMARY_CLAIM', payload: { tabId: currentTabId } });
      startHeartbeat();
    };

    const notePrimary = (payload: { tabId: string; timestamp?: number }) => {
      if (payload.tabId === currentTabId) {
        return;
      }
      lastHeartbeatRef.current = payload.timestamp ?? Date.now();
      clearElectionTimeout();
      if (isPrimaryRef.current) {
        if (shouldYieldTo(payload.tabId)) {
          setPrimaryState(false);
          stopHeartbeat();
        } else {
          coordinationChannel.postMessage({ type: 'PRIMARY_CLAIM', payload: { tabId: currentTabId } });
        }
      } else {
        setPrimaryState(false);
      }
    };

    const scheduleElection = (reason: 'initial' | 'handoff') => {
      if (isPrimaryRef.current || electionTimeoutRef.current) {
        return;
      }
      const jitter = Math.floor(Math.random() * ELECTION_JITTER_MS);
      const delay = reason === 'handoff' ? PRIMARY_HANDOFF_DELAY_MS + jitter : jitter;
      electionTimeoutRef.current = setTimeout(() => {
        electionTimeoutRef.current = null;
        if (!isPrimaryRef.current) {
          becomePrimary();
        }
      }, delay);
    };

    const requestPrimary = (reason: 'initial' | 'handoff') => {
      coordinationChannel.postMessage({ type: 'PING_PRIMARY', payload: { tabId: currentTabId } });
      scheduleElection(reason);
    };

    coordinationChannel.onmessage = (event) => {
      const message = event.data as CoordinationMessage;
      if (!message || typeof message !== 'object') {
        return;
      }
      const { type, payload } = message;
      if (!payload?.tabId) {
        return;
      }

      if (type === 'PING_PRIMARY' && isPrimaryRef.current && payload.tabId !== currentTabId) {
        coordinationChannel.postMessage({
          type: 'PONG_PRIMARY',
          payload: { tabId: currentTabId, timestamp: Date.now() },
        });
        return;
      }

      if (type === 'PONG_PRIMARY' || type === 'PRIMARY_HEARTBEAT' || type === 'PRIMARY_CLAIM') {
        notePrimary(payload);
        return;
      }

      if (type === 'PRIMARY_CLOSING' && payload.tabId !== currentTabId) {
        requestPrimary('handoff');
      }
    };

    heartbeatCheckRef.current = setInterval(() => {
      if (isPrimaryRef.current) {
        return;
      }
      const lastHeartbeat = lastHeartbeatRef.current;
      if (!lastHeartbeat) {
        return;
      }
      if (Date.now() - lastHeartbeat > HEARTBEAT_TIMEOUT_MS) {
        requestPrimary('handoff');
      }
    }, HEARTBEAT_CHECK_INTERVAL_MS);

    requestPrimary('initial');

    return () => {
      if (isPrimaryRef.current) {
        coordinationChannel.postMessage({ type: 'PRIMARY_CLOSING', payload: { tabId: currentTabId } });
      }
      clearElectionTimeout();
      stopHeartbeat();
      if (heartbeatCheckRef.current) {
        clearInterval(heartbeatCheckRef.current);
        heartbeatCheckRef.current = null;
      }
      coordinationChannel.close();
      channelRef.current = null;
      setChannel(null);
    };
  }, [jobId]);

  return { isPrimary, channel };
};
