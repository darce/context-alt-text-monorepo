/**
 * Phase → presentation strategy map (sr-007, [REF-02]).
 *
 * Single owner of every phase-derived user-facing string. Two phase domains,
 * one record per union:
 *   - `JOB_PHASE_PRESENTATION` keyed on the generated `JobProgress['phase']`
 *     union (backend-reported phases; contract in
 *     `js/admin/api/generated/recognition-job.ts` — never edited here).
 *   - `PIPELINE_PHASE_PRESENTATION` keyed on the client state machine's
 *     `PipelinePhase` union.
 * `satisfies Record<Union, PresentationEntry>` compile-checks exhaustiveness
 * on both. The overlapping `'clustering'` member references the shared
 * `SYNC_VOCABULARY` constants so both domains speak one vocabulary.
 *
 * Dynamic counts arrive only through builder params — call sites decide which
 * signal wins (precedence is behavior), the map decides what the string says.
 */
import { __, sprintf } from '@wordpress/i18n';

import type { JobProgress } from '../../api/recognition/types/scan';
import type { PipelinePhase } from '../../hooks/jobStateMachineUtils';
import { SYNC_VOCABULARY } from './syncVocabulary';

export type JobPhase = NonNullable<JobProgress['phase']>;

/** Count-bearing live status copy; dynamic values arrive only via params. */
export type PhaseStatusBuilder = (p: { completed: number; total: number; facesFound?: number }) => string;

/** 'Processed …' progress line; call sites pass raw signals, the builder decides the copy. */
export type ProcessedStatusBuilder = (p: {
  completed: number;
  total: number;
  imagesProcessed?: number;
  facesFound?: number;
}) => string;

/** Milestone label variants for a pipeline phase (JobTimeline). */
export interface MilestoneLabels {
  active: string;
  complete: string;
  failed?: string;
}

export interface PresentationEntry {
  /** Static phase label (badges, `formatSyncJobPhase`). */
  label: string;
  /** Live status line with counts. */
  status?: PhaseStatusBuilder;
  /** Status copy when no progress counts are available. */
  statusFallback?: string;
  /** Milestone label variants (pipeline record only). */
  milestone?: MilestoneLabels;
  /** 'Processed …' progress line (job record only). */
  processed?: ProcessedStatusBuilder;
  /** aria-label for the `<progress>` element (job record only). */
  progressAriaLabel?: string;
}

// Shared per-family builders/labels — defined once, referenced by every entry
// in the family so the two variants cannot drift apart.
const PROCESSED_IDENTITIES: ProcessedStatusBuilder = (p) =>
  sprintf(__('Processed %d/%d identities', 'alt-context'), p.completed, p.total);

const PROCESSED_IMAGES: ProcessedStatusBuilder = (p) =>
  sprintf(__('Processed %d/%d images', 'alt-context'), p.imagesProcessed ?? p.completed, p.total) +
  (typeof p.facesFound === 'number' ? sprintf(__(' · %d faces found', 'alt-context'), p.facesFound) : '');

const CLUSTERING_PROGRESS_ARIA_LABEL = __('Clustering progress', 'alt-context');
const SCAN_PROGRESS_ARIA_LABEL = __('Scan progress', 'alt-context');

export const JOB_PHASE_PRESENTATION = {
  queued: {
    label: SYNC_VOCABULARY.phaseQueued,
    status: (p) => sprintf(__('Queued %d items…', 'alt-context'), p.total),
    processed: PROCESSED_IMAGES,
    progressAriaLabel: SCAN_PROGRESS_ARIA_LABEL,
  },
  detecting: {
    label: SYNC_VOCABULARY.phaseDetecting,
    status: (p) =>
      typeof p.facesFound === 'number'
        ? sprintf(
            __('Detecting faces… %d/%d processed · %d faces found', 'alt-context'),
            p.completed,
            p.total,
            p.facesFound,
          )
        : sprintf(__('Detecting faces… %d/%d processed', 'alt-context'), p.completed, p.total),
    processed: PROCESSED_IMAGES,
    progressAriaLabel: SCAN_PROGRESS_ARIA_LABEL,
  },
  clustering: {
    label: SYNC_VOCABULARY.phaseClustering,
    status: (p) => sprintf(__('Clustering %d/%d identities…', 'alt-context'), p.completed, p.total),
    statusFallback: __('Clustering faces…', 'alt-context'),
    processed: PROCESSED_IDENTITIES,
    progressAriaLabel: CLUSTERING_PROGRESS_ARIA_LABEL,
  },
  retrying: {
    label: SYNC_VOCABULARY.phaseRetrying,
    processed: PROCESSED_IDENTITIES,
    progressAriaLabel: CLUSTERING_PROGRESS_ARIA_LABEL,
  },
  awaiting_projection: {
    label: SYNC_VOCABULARY.phaseSyncingResults,
    statusFallback: __('Syncing projected results…', 'alt-context'),
    processed: PROCESSED_IMAGES,
    progressAriaLabel: SCAN_PROGRESS_ARIA_LABEL,
  },
  failed: {
    label: SYNC_VOCABULARY.phaseFailed,
    processed: PROCESSED_IMAGES,
    progressAriaLabel: SCAN_PROGRESS_ARIA_LABEL,
  },
  complete: {
    label: SYNC_VOCABULARY.phaseComplete,
    processed: PROCESSED_IMAGES,
    progressAriaLabel: SCAN_PROGRESS_ARIA_LABEL,
  },
} satisfies Record<JobPhase, PresentationEntry>;

export const PIPELINE_PHASE_PRESENTATION = {
  // 'idle' renders no phase copy anywhere; entry exists for exhaustiveness.
  idle: {
    label: '',
  },
  scanning: {
    label: SYNC_VOCABULARY.scanningHeadline,
    milestone: {
      active: SYNC_VOCABULARY.scanningHeadline,
      complete: SYNC_VOCABULARY.scanComplete,
    },
  },
  clustering: {
    label: SYNC_VOCABULARY.clusteringHeadline,
    milestone: {
      active: SYNC_VOCABULARY.clusteringHeadline,
      complete: SYNC_VOCABULARY.clusteringComplete,
      failed: SYNC_VOCABULARY.clusteringFailed,
    },
  },
  projecting: {
    label: SYNC_VOCABULARY.resultsSyncingHeadline,
    milestone: {
      active: SYNC_VOCABULARY.resultsSyncingHeadline,
      complete: SYNC_VOCABULARY.resultsSynced,
      failed: SYNC_VOCABULARY.resultsSyncFailed,
    },
  },
} satisfies Record<PipelinePhase, PresentationEntry>;
