import { useState, useEffect } from 'react';

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
}

/**
 * Hook return type definition.
 */
export interface JobPersistence {
  /** Array of active job metadata. */
  activeJobs: PersistedJob[];
  /** Track a new job with its type. */
  addJob: (id: string, type: JobType, totalItems: number) => void;
  /** Remove a job from tracking. */
  removeJob: (id: string) => void;
}

const STORAGE_KEY = 'acx_active_jobs';
const MAX_AGE_MS = 3600000; // 1 hour

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

      // Purge stale jobs (>1 hour old) AND jobs without type field (old schema)
      const freshJobs = jobs.filter((job) => now - job.startedAt < MAX_AGE_MS && typeof job.type === 'string');

      // If we purged some, update storage immediately
      if (freshJobs.length !== jobs.length) {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(freshJobs));
      }

      return freshJobs;
    } catch (e) {
      console.error('Failed to parse persisted jobs', e);
      return [];
    }
  });

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(activeJobs));
  }, [activeJobs]);

  const addJob = (id: string, type: JobType, totalItems: number) => {
    setActiveJobs((prev) => {
      // Don't add duplicate jobs
      if (prev.some((job) => job.id === id)) {
        return prev;
      }
      return [...prev, { id, type, startedAt: Date.now(), totalItems }];
    });
  };

  const removeJob = (id: string) => {
    setActiveJobs((prev) => prev.filter((job) => job.id !== id));
  };

  return { activeJobs, addJob, removeJob };
};
