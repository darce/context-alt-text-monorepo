import { useState, useEffect } from 'react';

import { createLogger } from '../utils/logger';

/**
 * Job type discriminator for scan vs clustering jobs.
 */
export type JobType = 'scan' | 'clustering';

/**
 * Persisted job metadata for storage in localStorage.
 */
export interface PersistedJob {
  /** The UUID of the job. */
  id: string;
  /** The type of job (scan or clustering). */
  type: JobType;
  /** Unix timestamp (ms) when the job was first tracked. */
  startedAt: number;
  /** Total number of items in the batch. */
  totalItems: number;
  /** Client-generated batch run id shared by sibling scan jobs. */
  batchRunId?: string;
}

/**
 * Hook return type definition.
 */
export interface JobPersistence {
  /** Array of active job metadata. */
  activeJobs: PersistedJob[];
  /** Track a new job with its type. */
  addJob: (id: string, type: JobType, totalItems: number, batchRunId?: string) => void;
  /** Remove a job from tracking. */
  removeJob: (id: string) => void;
}

const log = createLogger('jobPersistence');
const STORAGE_KEY = 'acx_active_jobs';
const ACTIVE_MAX_AGE_MS = 24 * 60 * 60 * 1000; // 24 hours
const TERMINAL_MAX_AGE_MS = 60 * 60 * 1000; // 1 hour
const TERMINAL_STATUSES = new Set(['complete', 'completed', 'failed', 'cancelled', 'canceled']);

const isTerminalStatus = (status: unknown): boolean =>
  typeof status === 'string' && TERMINAL_STATUSES.has(status.toLowerCase());

const isFreshPersistedJob = (job: PersistedJob, now: number): boolean => {
  if (typeof job.type !== 'string' || !Number.isFinite(job.startedAt)) {
    return false;
  }

  const ageMs = now - job.startedAt;
  if (!Number.isFinite(ageMs) || ageMs < 0) {
    return false;
  }

  const legacyStatus = (job as PersistedJob & { status?: unknown }).status;
  const maxAgeMs = isTerminalStatus(legacyStatus) ? TERMINAL_MAX_AGE_MS : ACTIVE_MAX_AGE_MS;
  return ageMs < maxAgeMs;
};

/**
 * Hook to manage active job IDs in localStorage to survive page reloads.
 *
 * @returns {JobPersistence} Functions to manage persisted jobs.
 */
export const useJobPersistence = (): JobPersistence => {
  const [activeJobs, setActiveJobs] = useState<PersistedJob[]>(() => {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (!stored) {
      return [];
    }

    try {
      const jobs = JSON.parse(stored) as PersistedJob[];
      const now = Date.now();

      // Keep active jobs for a longer recovery window; purge terminal/invalid entries.
      const freshJobs = jobs.filter((job) => isFreshPersistedJob(job, now));

      // If we purged some, update storage immediately
      if (freshJobs.length !== jobs.length) {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(freshJobs));
      }

      return freshJobs;
    } catch (error) {
      log.error('Failed to parse persisted jobs', { error });
      return [];
    }
  });

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(activeJobs));
  }, [activeJobs]);

  const addJob = (id: string, type: JobType, totalItems: number, batchRunId?: string) => {
    setActiveJobs((prev) => {
      // Don't add duplicate jobs
      if (prev.some((job) => job.id === id)) {
        return prev;
      }
      return [...prev, { id, type, startedAt: Date.now(), totalItems, batchRunId }];
    });
  };

  const removeJob = (id: string) => {
    setActiveJobs((prev) => prev.filter((job) => job.id !== id));
  };

  return { activeJobs, addJob, removeJob };
};
