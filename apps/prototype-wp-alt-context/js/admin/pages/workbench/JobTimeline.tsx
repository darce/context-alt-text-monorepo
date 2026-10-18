import React from 'react';
import { __, sprintf } from '@wordpress/i18n';

import type { JobProgress } from '../../api/recognition/types/scan';
import type { PipelinePhase } from '../../hooks/jobStateMachineUtils';
import type { ProjectionSyncState } from '../../hooks/useJobStateMachineEffects';
import { PIPELINE_PHASE_PRESENTATION } from './phasePresentation';
import { SYNC_VOCABULARY } from './syncPresentation';

export interface JobTimelineProps {
  scanProgress: JobProgress | null;
  clusterProgress: JobProgress | null;
  phase: PipelinePhase;
  projectionSyncState?: ProjectionSyncState;
  /** Dense horizontal layout for the active-job strip (E21-18 S1). */
  compact?: boolean;
}

type MilestoneStatus = 'completed' | 'active' | 'pending' | 'failed';

interface Milestone {
  id: string;
  label: string;
  status: MilestoneStatus;
  detail?: string;
}

const isScanComplete = (scanProgress: JobProgress | null): boolean => {
  if (!scanProgress) {
    return false;
  }
  return scanProgress.phase === 'complete' || scanProgress.phase === 'awaiting_projection';
};

const buildScanDetail = (scanProgress: JobProgress, scanDone: boolean): string | undefined => {
  const images = scanProgress.images_processed ?? scanProgress.completed;
  const faces = typeof scanProgress.faces_found === 'number' ? scanProgress.faces_found : null;
  if (scanDone && images > 0) {
    return faces !== null
      ? sprintf(__('%1$d images, %2$d faces found', 'alt-context'), images, faces)
      : sprintf(__('%d images', 'alt-context'), images);
  }
  if (scanProgress.total > 0) {
    return sprintf(__('%1$d / %2$d images', 'alt-context'), images, scanProgress.total);
  }
  return undefined;
};

const buildClusterDetail = (
  clusterProgress: JobProgress,
  clusterDone: boolean,
  clusterStatus: MilestoneStatus,
): string | undefined => {
  if (clusterProgress.total === 0) {
    return undefined;
  }
  if (clusterDone && typeof clusterProgress.clusters_created === 'number') {
    const count = clusterProgress.clusters_created;
    return count === 1
      ? __('1 cluster created', 'alt-context')
      : sprintf(__('%d clusters created', 'alt-context'), count);
  }
  if (clusterStatus === 'active') {
    return sprintf(__('%1$d / %2$d identities', 'alt-context'), clusterProgress.completed, clusterProgress.total);
  }
  return undefined;
};

const getRetryInfo = (
  p: JobProgress | null,
  clusterPhase: string | undefined,
): { retryCount: number; lastErrorCode: string | undefined } => {
  const fallback = clusterPhase === 'retrying' ? 1 : 0;
  // TypeScript infers an `error` type for these optional fields in files that
  // also import `@wordpress/i18n`, due to `DistributeSprintfArgs<T>` recursive
  // conditional type contamination. The `typeof` guards confirm the runtime type;
  // the `as` casts below restore the correct inferred type for the lint rule.
  return {
    retryCount: p !== null && typeof p.retry_count === 'number' ? p.retry_count : fallback,
    lastErrorCode: p !== null && typeof p.last_error_code === 'string' ? p.last_error_code : undefined,
  };
};

const buildRetryMilestones = (
  retryCount: number,
  clusterPhase: string | undefined,
  lastErrorCode: string | undefined,
): Milestone[] => {
  const result: Milestone[] = [];
  for (let i = 1; i <= retryCount; i++) {
    const isLastRetry = i === retryCount;
    result.push({
      id: `retry-${i}`,
      label: sprintf(__('Retry %d', 'alt-context'), i),
      status: isLastRetry && clusterPhase === 'retrying' ? 'active' : 'completed',
      detail: isLastRetry && lastErrorCode ? sprintf(__('Last error: %s', 'alt-context'), lastErrorCode) : undefined,
    });
  }
  return result;
};

const buildMilestones = (
  scanProgress: JobProgress | null,
  clusterProgress: JobProgress | null,
  phase: PipelinePhase,
  projectionSyncState: ProjectionSyncState,
): Milestone[] => {
  const milestones: Milestone[] = [];
  const scanDone = isScanComplete(scanProgress);
  const projectionReady = projectionSyncState === 'ready';

  // --- Scan milestone ---
  if (phase === 'scanning' || scanProgress) {
    const scanLabels = PIPELINE_PHASE_PRESENTATION.scanning.milestone;
    milestones.push({
      id: 'scan',
      label: scanDone ? scanLabels.complete : scanLabels.active,
      status: scanDone ? 'completed' : 'active',
      detail: scanProgress ? buildScanDetail(scanProgress, scanDone) : undefined,
    });
  }

  // --- Clustering milestone ---
  if (phase === 'clustering' || phase === 'projecting' || clusterProgress) {
    const clusterPhase = clusterProgress ? clusterProgress.phase : undefined;
    const clusterFailed = clusterPhase === 'failed';
    const clusterDone = clusterPhase === 'complete' || clusterPhase === 'awaiting_projection' || phase === 'projecting';

    let clusterStatus: MilestoneStatus;
    if (clusterFailed) {
      clusterStatus = 'failed';
    } else if (clusterDone) {
      clusterStatus = 'completed';
    } else if (phase === 'clustering') {
      clusterStatus = 'active';
    } else {
      clusterStatus = 'pending';
    }

    // Compute retry values before the push so they are not shadowed.
    const { retryCount, lastErrorCode } = getRetryInfo(clusterProgress, clusterPhase);

    const clusterLabels = PIPELINE_PHASE_PRESENTATION.clustering.milestone;
    milestones.push({
      id: 'clustering',
      label: clusterFailed ? clusterLabels.failed : clusterDone ? clusterLabels.complete : clusterLabels.active,
      status: clusterStatus,
      detail: clusterProgress ? buildClusterDetail(clusterProgress, clusterDone, clusterStatus) : undefined,
    });

    // --- Retry milestones (one per retry occurrence) ---
    milestones.push(...buildRetryMilestones(retryCount, clusterPhase, lastErrorCode));
  }

  // --- Results sync milestone ---
  if (phase === 'projecting' || projectionSyncState !== 'idle') {
    const projFailed = projectionSyncState === 'error';
    const projDone = projectionSyncState === 'idle' && phase !== 'projecting';

    let projStatus: MilestoneStatus;
    if (projFailed) {
      projStatus = 'failed';
    } else if (projectionReady) {
      projStatus = 'active';
    } else if (projDone) {
      projStatus = 'completed';
    } else if (projectionSyncState === 'acknowledging' || projectionSyncState === 'syncing') {
      projStatus = 'active';
    } else {
      projStatus = 'pending';
    }

    // Phase-derived labels come from the map; the ready/acknowledging variants
    // are projection-sync-state copy and stay on SYNC_VOCABULARY.
    const resultsLabels = PIPELINE_PHASE_PRESENTATION.projecting.milestone;
    milestones.push({
      id: 'results',
      label: projFailed
        ? resultsLabels.failed
        : projectionReady
          ? SYNC_VOCABULARY.resultsReadyHeadline.replace(/\.$/, '')
          : projDone
            ? resultsLabels.complete
            : projectionSyncState === 'acknowledging'
              ? SYNC_VOCABULARY.resultsAcknowledgingHeadline
              : resultsLabels.active,
      status: projStatus,
    });
  }

  return milestones;
};

const MILESTONE_ICONS: Record<MilestoneStatus, string> = {
  completed: '\u2713',
  active: '\u25cf',
  pending: '\u25cb',
  failed: '\u2715',
};

const MilestoneIcon = ({ status }: { status: MilestoneStatus }): React.JSX.Element => (
  <span className={`acx-job-timeline__icon acx-job-timeline__icon--${status}`} aria-hidden="true">
    {MILESTONE_ICONS[status]}
  </span>
);

export const JobTimeline = ({
  scanProgress,
  clusterProgress,
  phase,
  projectionSyncState = 'idle',
  compact = false,
}: JobTimelineProps): React.JSX.Element | null => {
  const milestones = buildMilestones(scanProgress, clusterProgress, phase, projectionSyncState);

  if (milestones.length === 0) {
    return null;
  }

  const listClass = compact ? 'acx-job-timeline acx-job-timeline--compact' : 'acx-job-timeline';

  return (
    <ol className={listClass} aria-label={__('Job progress milestones', 'alt-context')} data-compact={compact || undefined}>
      {milestones.map((milestone) => (
        <li key={milestone.id} className={`acx-job-timeline__item acx-job-timeline__item--${milestone.status}`}>
          <MilestoneIcon status={milestone.status} />
          <span className="acx-job-timeline__label">{milestone.label}</span>
          {!compact && milestone.detail ? <span className="acx-job-timeline__detail">{milestone.detail}</span> : null}
        </li>
      ))}
    </ol>
  );
};

export { buildMilestones };
