import { renderHook, act } from '@testing-library/react';
import { setLogLevel, setLogSink, type LogRecord } from '../../utils/logger';
import { useJobPersistence } from '../useJobPersistence';

describe('useJobPersistence', () => {
  const STORAGE_KEY = 'acx_active_jobs';

  beforeEach(() => {
    window.localStorage.clear();
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
    setLogSink(null);
    setLogLevel(null);
  });

  const captureRecords = (): LogRecord[] => {
    const records: LogRecord[] = [];
    setLogLevel('debug');
    setLogSink((record) => {
      records.push(record);
    });
    return records;
  };

  it('hydrates empty state when nothing is in localStorage', () => {
    const { result } = renderHook(() => useJobPersistence());
    expect(result.current.activeJobs).toEqual([]);
  });

  it('adds and persists a job', () => {
    const { result } = renderHook(() => useJobPersistence());

    act(() => {
      result.current.addJob('job-1', 'scan', 10);
    });

    expect(result.current.activeJobs).toHaveLength(1);
    expect(result.current.activeJobs[0]).toMatchObject({
      id: 'job-1',
      type: 'scan',
      totalItems: 10,
    });
    expect(result.current.activeJobs[0].startedAt).toBeDefined();

    const stored = JSON.parse(window.localStorage.getItem(STORAGE_KEY) ?? '[]') as { id: string }[];
    expect(stored).toHaveLength(1);
    expect(stored[0]?.id).toBe('job-1');
  });

  it('removes a job', () => {
    const { result } = renderHook(() => useJobPersistence());

    act(() => {
      result.current.addJob('job-1', 'scan', 10);
      result.current.addJob('job-2', 'clustering', 20);
    });

    act(() => {
      result.current.removeJob('job-1');
    });

    expect(result.current.activeJobs).toHaveLength(1);
    expect(result.current.activeJobs[0].id).toBe('job-2');

    const stored = JSON.parse(window.localStorage.getItem(STORAGE_KEY) ?? '[]') as { id: string }[];
    expect(stored).toHaveLength(1);
    expect(stored[0]?.id).toBe('job-2');
  });

  it('hydrates from localStorage on mount', () => {
    const initialJobs = [{ id: 'job-1', type: 'scan', startedAt: Date.now(), totalItems: 10 }];
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(initialJobs));

    const { result } = renderHook(() => useJobPersistence());
    expect(result.current.activeJobs).toEqual(initialJobs);
  });

  it('returns empty state when localStorage contains invalid JSON', () => {
    const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => undefined);
    window.localStorage.setItem(STORAGE_KEY, '{not-json');

    const { result } = renderHook(() => useJobPersistence());

    expect(result.current.activeJobs).toEqual([]);
    expect(consoleSpy).toHaveBeenCalled();
    consoleSpy.mockRestore();
  });

  it('retains non-terminal jobs past 1 hour to preserve recovery state', () => {
    const now = Date.now();
    const staleTime = now - (3600 * 1000 + 1); // 1 hour + 1ms ago
    const freshJob = { id: 'fresh', type: 'scan', startedAt: now, totalItems: 10 };
    const staleJob = { id: 'stale', type: 'clustering', startedAt: staleTime, totalItems: 20 };

    window.localStorage.setItem(STORAGE_KEY, JSON.stringify([freshJob, staleJob]));

    const { result } = renderHook(() => useJobPersistence());

    expect(result.current.activeJobs).toHaveLength(2);
    expect(result.current.activeJobs[0].id).toBe('fresh');
    expect(result.current.activeJobs[1].id).toBe('stale');

    const stored = JSON.parse(window.localStorage.getItem(STORAGE_KEY) ?? '[]') as { id: string }[];
    expect(stored).toHaveLength(2);
    expect(stored[1]?.id).toBe('stale');
  });

  it('purges stale terminal jobs on mount', () => {
    const now = Date.now();
    const staleTime = now - (3600 * 1000 + 1); // 1 hour + 1ms ago
    const activeJob = { id: 'active', type: 'scan', startedAt: staleTime, totalItems: 10 };
    const staleTerminalJob = {
      id: 'done',
      type: 'clustering',
      startedAt: staleTime,
      totalItems: 20,
      status: 'completed',
    };

    window.localStorage.setItem(STORAGE_KEY, JSON.stringify([activeJob, staleTerminalJob]));

    const { result } = renderHook(() => useJobPersistence());

    expect(result.current.activeJobs).toHaveLength(1);
    expect(result.current.activeJobs[0].id).toBe('active');

    const stored = JSON.parse(window.localStorage.getItem(STORAGE_KEY) ?? '[]') as { id: string }[];
    expect(stored).toHaveLength(1);
    expect(stored[0]?.id).toBe('active');
  });
  describe('hydrate is one observable unit of work [FEBT-1-W1-O-02]', () => {
    it('emits a single correlated jobs.hydrate event reporting restored and purged counts', () => {
      const staleTime = Date.now() - 25 * 60 * 60 * 1000;
      window.localStorage.setItem(
        STORAGE_KEY,
        JSON.stringify([
          { id: 'active', type: 'scan', startedAt: Date.now(), totalItems: 5 },
          { id: 'stale', type: 'scan', startedAt: staleTime, totalItems: 5 },
        ]),
      );
      const records = captureRecords();

      renderHook(() => useJobPersistence());

      const hydrate = records.filter((record) => record.message === 'jobs.hydrate');
      expect(hydrate).toHaveLength(1);
      expect(hydrate[0].fields).toEqual(
        expect.objectContaining({ outcome: 'restored', stored: 2, restored: 1, purged: 1, jobIds: ['active'] }),
      );
      expect(hydrate[0].fields.requestId).toEqual(expect.any(String));
    });

    it('reports the empty hydrate rather than staying silent', () => {
      const records = captureRecords();
      renderHook(() => useJobPersistence());

      const hydrate = records.filter((record) => record.message === 'jobs.hydrate');
      expect(hydrate).toHaveLength(1);
      expect(hydrate[0].fields.outcome).toBe('empty');
    });

    it('reports a corrupt payload as parse_failed at error level', () => {
      window.localStorage.setItem(STORAGE_KEY, '{not json');
      const records = captureRecords();

      const { result } = renderHook(() => useJobPersistence());

      expect(result.current.activeJobs).toEqual([]);
      const hydrate = records.filter((record) => record.message === 'jobs.hydrate');
      expect(hydrate).toHaveLength(1);
      expect(hydrate[0].level).toBe('error');
      expect(hydrate[0].fields.outcome).toBe('parse_failed');
    });
  });
});
