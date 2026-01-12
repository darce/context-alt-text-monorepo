import { renderHook } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach, type Mock } from 'vitest';
import { useJobStateMachine } from '../useJobStateMachine';
import { useJobPersistence } from '../useJobPersistence';
import { useQueryClient } from '@tanstack/react-query';

// Mocks
vi.mock('../useJobPersistence');
vi.mock('@tanstack/react-query', () => ({
  useQueryClient: vi.fn(),
}));
vi.mock('../useJobProgressStream', () => ({
  useJobProgressStream: vi.fn(() => ({
    progress: null,
    status: 'pending',
    isOnline: true,
    etaSeconds: null,
    isPrimary: true,
  })),
}));
vi.mock('../useRecognitionHooks', () => ({
  useScanIdentities: vi.fn(() => ({ mutate: vi.fn() })),
  useClusterIdentities: vi.fn(() => ({ mutate: vi.fn() })),
  useCancelScanJobs: vi.fn(() => ({ mutate: vi.fn() })),
  useCombinedScanStatus: vi.fn(() => ({ scanStatusQuery: { data: null } })),
}));

describe('useJobStateMachine', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    (useJobPersistence as Mock).mockReturnValue({
      activeJobs: [],
      addJob: vi.fn(),
      removeJob: vi.fn(),
    });
    (useQueryClient as Mock).mockReturnValue({
      invalidateQueries: vi.fn(),
    });
  });

  it('initializes with idle phase', () => {
    const { result } = renderHook(() => useJobStateMachine());
    expect(result.current.currentPhase).toBe('idle');
    expect(result.current.isScanRunning).toBe(false);
  });

  it('reports scanning phase when scan job exists', () => {
    (useJobPersistence as Mock).mockReturnValue({
      activeJobs: [{ id: 'job-1', type: 'scan' }],
      addJob: vi.fn(),
      removeJob: vi.fn(),
    });
    const { result } = renderHook(() => useJobStateMachine());
    expect(result.current.currentPhase).toBe('scanning');
    expect(result.current.latestJobId).toBe('job-1');
  });

  it('reports clustering phase when clustering job exists', () => {
    (useJobPersistence as Mock).mockReturnValue({
      activeJobs: [
        { id: 'job-1', type: 'scan' },
        { id: 'job-2', type: 'clustering' },
      ],
      addJob: vi.fn(),
      removeJob: vi.fn(),
    });
    const { result } = renderHook(() => useJobStateMachine());
    expect(result.current.currentPhase).toBe('clustering');
    expect(result.current.latestJobId).toBe('job-2');
  });
});
