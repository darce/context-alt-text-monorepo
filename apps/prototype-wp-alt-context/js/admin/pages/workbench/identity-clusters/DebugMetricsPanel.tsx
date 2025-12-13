/**
 * Debug metrics panel for development environments.
 *
 * Displays InsightFace metadata (pose, age, gender, detection score, etc.)
 * and clustering decision info when available.
 * Only shown when wp_get_environment_type() === 'development'.
 */

import React from 'react';
import { __ } from '@wordpress/i18n';

import type { DebugMetrics } from '../../../api/recognition';
import { isDevMode } from '../../../api/config';

interface DebugMetricsPanelProps {
  metrics: DebugMetrics | null | undefined;
}

/**
 * Format clustering method for display.
 */
const formatClusteringMethod = (method: string | null): string => {
  if (!method) {
    return '—';
  }
  switch (method) {
    case 'new_cluster':
      return '🆕 New cluster';
    case 'similarity_match':
      return '🔗 Matched';
    case 'representative_match':
      return '👤 Rep match';
    case 'centroid_match':
      return '📍 Centroid';
    default:
      return method;
  }
};

/**
 * Format clustering algorithm for display.
 */
const formatClusteringAlgorithm = (algorithm: string | null): string => {
  if (!algorithm) {
    return '—';
  }
  switch (algorithm) {
    case 'cosine_similarity':
      return 'Cosine';
    case 'chinese_whispers':
      return 'CW';
    case 'hdbscan':
      return 'HDBSCAN';
    default:
      return algorithm;
  }
};

/**
 * Renders InsightFace debug metrics in a compact panel.
 * Only visible in development mode.
 */
export const DebugMetricsPanel = ({ metrics }: DebugMetricsPanelProps): React.JSX.Element | null => {
  const [isExpanded, setIsExpanded] = React.useState(false);
  const devMode = isDevMode();

  // Only show in development mode
  if (!devMode || !metrics) {
    return null;
  }

  const {
    pose,
    age,
    gender,
    det_score,
    bbox_area,
    landmark_quality,
    clustering_method,
    clustering_algorithm,
    similarity_threshold,
    match_similarity,
  } = metrics;

  // Format pose angles for display
  const poseLabel = `P:${pose.pitch.toFixed(0)}° Y:${pose.yaw.toFixed(0)}° R:${pose.roll.toFixed(0)}°`;

  // Determine pose quality (extreme angles may reduce recognition quality)
  const isExtremeYaw = Math.abs(pose.yaw) > 45;
  const isExtremePitch = Math.abs(pose.pitch) > 30;
  const poseQuality = isExtremeYaw || isExtremePitch ? 'poor' : 'good';

  // Determine if match was borderline (close to threshold)
  const isBorderline =
    match_similarity !== null &&
    similarity_threshold !== null &&
    match_similarity < similarity_threshold + 0.05 &&
    match_similarity >= similarity_threshold;

  return (
    <div className="acx-debug-metrics">
      <button
        type="button"
        className="acx-debug-metrics__toggle"
        onClick={() => setIsExpanded(!isExpanded)}
        aria-expanded={isExpanded}
      >
        <span className="acx-debug-metrics__icon">🔍</span>
        <span className="acx-debug-metrics__summary">
          {gender === 'male' ? '♂' : '♀'} ~{Math.round(age)}y
          {match_similarity !== null && match_similarity < 1.0 && ` | ${(match_similarity * 100).toFixed(0)}%`}
          {clustering_method && ` | ${formatClusteringMethod(clustering_method)}`}
        </span>
        <span className="acx-debug-metrics__chevron">{isExpanded ? '▼' : '▶'}</span>
      </button>

      {isExpanded && (
        <dl className="acx-debug-metrics__details">
          {/* Clustering Decision Section */}
          {(clustering_method ?? clustering_algorithm) && (
            <>
              <div className="acx-debug-metrics__section-header">{__('Clustering', 'alt-context')}</div>
              <div className="acx-debug-metrics__row">
                <dt>{__('Method', 'alt-context')}</dt>
                <dd>{formatClusteringMethod(clustering_method)}</dd>
              </div>
              <div className="acx-debug-metrics__row">
                <dt>{__('Algorithm', 'alt-context')}</dt>
                <dd>{formatClusteringAlgorithm(clustering_algorithm)}</dd>
              </div>
              {similarity_threshold !== null && (
                <div className="acx-debug-metrics__row">
                  <dt>{__('Threshold', 'alt-context')}</dt>
                  <dd>{(similarity_threshold * 100).toFixed(1)}%</dd>
                </div>
              )}
              {match_similarity !== null && (
                <div className="acx-debug-metrics__row">
                  <dt>{__('Match Score', 'alt-context')}</dt>
                  <dd className={isBorderline ? 'acx-debug-metrics__value--warning' : undefined}>
                    {(match_similarity * 100).toFixed(1)}%{isBorderline && ' ⚠️'}
                  </dd>
                </div>
              )}
            </>
          )}

          {/* Face Metrics Section */}
          <div className="acx-debug-metrics__section-header">{__('Face Metrics', 'alt-context')}</div>
          <div className="acx-debug-metrics__row">
            <dt>{__('Pose', 'alt-context')}</dt>
            <dd className={`acx-debug-metrics__value--${poseQuality}`}>{poseLabel}</dd>
          </div>
          <div className="acx-debug-metrics__row">
            <dt>{__('Age', 'alt-context')}</dt>
            <dd>{age.toFixed(1)}</dd>
          </div>
          <div className="acx-debug-metrics__row">
            <dt>{__('Gender', 'alt-context')}</dt>
            <dd>{gender === 'male' ? __('Male', 'alt-context') : __('Female', 'alt-context')}</dd>
          </div>
          <div className="acx-debug-metrics__row">
            <dt>{__('Detection', 'alt-context')}</dt>
            <dd>{(det_score * 100).toFixed(1)}%</dd>
          </div>
          <div className="acx-debug-metrics__row">
            <dt>{__('Bbox Area', 'alt-context')}</dt>
            <dd>{bbox_area.toLocaleString()} px²</dd>
          </div>
          <div className="acx-debug-metrics__row">
            <dt>{__('Landmark Quality', 'alt-context')}</dt>
            <dd>{landmark_quality.toFixed(2)}</dd>
          </div>
        </dl>
      )}
    </div>
  );
};
