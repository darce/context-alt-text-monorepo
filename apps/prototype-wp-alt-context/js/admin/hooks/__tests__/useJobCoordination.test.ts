import { renderHook, act } from '@testing-library/react';
import { useJobCoordination } from '../useJobCoordination';
import { describe, it, expect, vi, beforeEach } from 'vitest';

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
  });

  it('should start as primary if no one else is around', () => {
    const { result } = renderHook(() => useJobCoordination(jobId));
    expect(result.current.isPrimary).toBe(true);
  });

  it('should yield primary status if PONG_PRIMARY received from another tab', () => {
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

    expect(result.current.isPrimary).toBe(false);
  });

  it('should become primary if existing primary is closing', () => {
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

    expect(result.current.isPrimary).toBe(true);
  });

  it('should respond to PING_PRIMARY if it is primary', () => {
    const { result } = renderHook(() => useJobCoordination(jobId));
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
