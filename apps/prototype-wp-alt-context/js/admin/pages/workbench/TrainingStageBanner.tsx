/**
 * Training Stage Banner
 *
 * Displays the current training stage based on curriculum learning principles.
 * Thresholds start strict (early stage) and relax as more identities are labeled.
 *
 * Inspired by CurricularFace: "address easy samples first, hard ones later"
 * For clustering, we invert: be strict early (avoid false positives), relax as system matures.
 */

import { __ } from '@wordpress/i18n';
import { useTrainingStage } from '../../hooks/useRecognitionHooks';
import { isDevMode } from '../../api/config';

const stageColors: Record<string, string> = {
  early: '#dc3545', // red - caution
  developing: '#fd7e14', // orange - progress
  mature: '#28a745', // green - stable
};

const stageIcons: Record<string, string> = {
  early: '🎯', // precision focus
  developing: '📈', // growing
  mature: '✅', // stable
};

export const TrainingStageBanner = (): React.JSX.Element | null => {
  const { data: stage, isLoading, isError } = useTrainingStage();

  // Don't show banner while loading or on error
  if (isLoading || isError || !stage) {
    return null;
  }

  const stageColor = stageColors[stage.stage] ?? '#6c757d';
  const stageIcon = stageIcons[stage.stage] ?? '📊';
  const devMode = isDevMode();

  return (
    <div
      className="acx-training-stage-banner"
      style={{
        backgroundColor: `${stageColor}15`,
        borderLeft: `4px solid ${stageColor}`,
      }}
    >
      <div className="acx-training-stage-banner__content">
        <span className="acx-training-stage-banner__icon">{stageIcon}</span>
        <div className="acx-training-stage-banner__info">
          <span className="acx-training-stage-banner__label">{stage.stage_label}</span>
          <span className="acx-training-stage-banner__stats">
            {stage.identity_count} {__('faces', 'alt-context')} · {stage.cluster_count} {__('clusters', 'alt-context')}
          </span>
        </div>
        {devMode && (
          <div className="acx-training-stage-banner__threshold">
            <span className="acx-training-stage-banner__threshold-label">{__('Threshold:', 'alt-context')}</span>
            <span className="acx-training-stage-banner__threshold-value">
              {Math.round(stage.current_threshold * 100)}%
            </span>
            <span className="acx-training-stage-banner__threshold-range">
              ({Math.round(stage.base_threshold * 100)}% → {Math.round(stage.strict_threshold * 100)}%)
            </span>
          </div>
        )}
        <div className="acx-training-stage-banner__progress">
          <div className="acx-training-stage-banner__progress-bar">
            <div
              className="acx-training-stage-banner__progress-fill"
              style={{
                width: `${stage.progress_percent}%`,
                backgroundColor: stageColor,
              }}
            />
          </div>
          <span className="acx-training-stage-banner__progress-text">{stage.progress_percent}%</span>
        </div>
      </div>
      {stage.stage === 'early' && (
        <p className="acx-training-stage-banner__hint">
          {__(
            'Label more faces to improve clustering accuracy. Higher thresholds are used in early stages to prevent false matches.',
            'alt-context',
          )}
        </p>
      )}
    </div>
  );
};
