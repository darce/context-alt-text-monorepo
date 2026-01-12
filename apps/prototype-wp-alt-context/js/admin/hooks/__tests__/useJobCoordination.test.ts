import { renderHook, act } from '@testing-library/react';
import { useJobCoordination } from '../useJobCoordination';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

// Mock BroadcastChannel
class MockBroadcastChannel {
  name: string;
  onmessage: ((ev: MessageEvent) => void) | null = null;
  postMessage = vi.fn();
  close = vi.fn();
  addEventListener = vi.fn();
  removeEventListener = vi.fn();

  constructor(name: string) {
    this.name = name;
  }
}

global.BroadcastChannel = MockBroadcastChannel as unknown as typeof BroadcastChannel;

describe('useJobCoordination', () => {
  const jobId = 'test-job-uuid';

  beforeEach(() => {
    vi.clearAllMocks();
    vi.useFakeTimers();
    vi.spyOn(Math, 'random').mockReturnValue(0);
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it('elects primary after randomized backoff when no primary responds', () => {
    const { result } = renderHook(() => useJobCoordination(jobId));
    expect(result.current.isPrimary).toBe(false);

    act(() => {
      vi.runOnlyPendingTimers();
    });

    expect(result.current.isPrimary).toBe(true);
  });

  it('stays observer if another tab responds as primary', () => {
    const { result } = renderHook(() => useJobCoordination(jobId));

    // Simulate someone else responding to PING_PRIMARY
    act(() => {
      const channel = result.current.channel as unknown as MockBroadcastChannel;
      if (channel.onmessage) {
        channel.onmessage({
          data: { type: 'PONG_PRIMARY', payload: { tabId: 'other-tab' } },
        } as MessageEvent);
      }
    });

    act(() => {
      vi.runOnlyPendingTimers();
    });

    expect(result.current.isPrimary).toBe(false);
  });

  it('becomes primary after a handoff when the primary closes', () => {
    const { result } = renderHook(() => useJobCoordination(jobId));

    // Simulate becoming an observer first
    act(() => {
      const channel = result.current.channel as unknown as MockBroadcastChannel;
      if (channel.onmessage) {
        channel.onmessage({
          data: { type: 'PONG_PRIMARY', payload: { tabId: 'other-tab' } },
        } as MessageEvent);
      }
    });
    expect(result.current.isPrimary).toBe(false);

    // Simulate primary closing
    act(() => {
      const channel = result.current.channel as unknown as MockBroadcastChannel;
      if (channel.onmessage) {
        channel.onmessage({
          data: { type: 'PRIMARY_CLOSING', payload: { tabId: 'other-tab' } },
        } as MessageEvent);
      }
    });

    act(() => {
      vi.advanceTimersByTime(1500);
    });

    expect(result.current.isPrimary).toBe(true);
  });

  it('responds to PING_PRIMARY when it is the primary', () => {
    const { result } = renderHook(() => useJobCoordination(jobId));

    act(() => {
      vi.runOnlyPendingTimers();
    });

    expect(result.current.isPrimary).toBe(true);

    const channel = result.current.channel as unknown as MockBroadcastChannel;

    act(() => {
      if (channel.onmessage) {
        channel.onmessage({
          data: { type: 'PING_PRIMARY', payload: { tabId: 'other-tab' } },
        } as MessageEvent);
      }
    });

    expect(channel.postMessage).toHaveBeenCalledWith(
      expect.objectContaining({
        type: 'PONG_PRIMARY',
      }),
    );
  });
});
