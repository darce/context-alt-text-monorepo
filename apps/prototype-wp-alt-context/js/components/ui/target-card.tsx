import * as React from 'react';
import { __ } from '@wordpress/i18n';

import type { RecognitionSourceValue } from '../../admin/api/settingsApi';
import {
  HEALTH_STATUS_ICONS,
  HEALTH_STATUS_LABELS,
  type HealthStatusValue,
} from '../../admin/pages/settings/settingsConstants';
import { RadioGroup, RadioGroupItem } from './radio-group';

export interface TargetCardGroupProps {
  value: RecognitionSourceValue;
  onValueChange: (value: RecognitionSourceValue) => void;
  disabled?: boolean;
  children: React.ReactNode;
}

export const TargetCardGroup = ({
  value,
  onValueChange,
  disabled = false,
  children,
}: TargetCardGroupProps): React.JSX.Element => (
  <RadioGroup
    aria-label={__('Recognition target', 'alt-context')}
    className="acx-target-cards"
    value={value}
    onValueChange={(next) => onValueChange(next as RecognitionSourceValue)}
    disabled={disabled}
  >
    {children}
  </RadioGroup>
);

export interface TargetCardProps {
  id: string;
  title: string;
  value: RecognitionSourceValue;
  isEffectiveTarget: boolean;
  healthStatus: HealthStatusValue;
  configured: boolean;
  disabled?: boolean;
  deemphasized?: boolean;
  emptyStateCta?: string;
  onEmptyStateCta?: () => void;
  onHealthCheck?: () => void;
  healthCheckPending?: boolean;
  healthCheckDisabled?: boolean;
  children?: React.ReactNode;
}

export const TargetCard = ({
  id,
  title,
  value,
  isEffectiveTarget,
  healthStatus,
  configured,
  disabled = false,
  deemphasized = false,
  emptyStateCta,
  onEmptyStateCta,
  onHealthCheck,
  healthCheckPending = false,
  healthCheckDisabled = false,
  children,
}: TargetCardProps): React.JSX.Element => {
  const cardClassName = [
    'acx-target-card',
    isEffectiveTarget ? 'acx-target-card--active' : '',
    deemphasized ? 'acx-target-card--deemphasized' : '',
  ]
    .filter(Boolean)
    .join(' ');

  return (
    <div className={cardClassName} data-testid={`acx-target-card-${value}`}>
      <div className="acx-target-card__header">
        <label className="acx-target-card__title" htmlFor={id}>
          <RadioGroupItem id={id} value={value} disabled={disabled} aria-label={title} />
          <span>{title}</span>
          {isEffectiveTarget ? (
            <span className="acx-target-card__active-badge">
              <span aria-hidden="true" className="acx-target-card__active-icon">
                {'\u2713'}
              </span>
              {__('Active', 'alt-context')}
            </span>
          ) : null}
        </label>
        <span className={`acx-target-card__health acx-target-card__health--${healthStatus}`}>
          <span aria-hidden="true" className="acx-target-card__health-icon">
            {HEALTH_STATUS_ICONS[healthStatus]}
          </span>
          {HEALTH_STATUS_LABELS[healthStatus]}
        </span>
      </div>

      {!configured && emptyStateCta ? (
        <div className="acx-target-card__empty">
          <p>{__('No service URL configured yet.', 'alt-context')}</p>
          {onEmptyStateCta ? (
            <button type="button" className="button button-secondary" onClick={onEmptyStateCta}>
              {emptyStateCta}
            </button>
          ) : null}
        </div>
      ) : (
        <div className="acx-target-card__body">{children}</div>
      )}

      {onHealthCheck ? (
        <div className="acx-target-card__actions">
          <button
            type="button"
            className="button button-secondary"
            onClick={onHealthCheck}
            disabled={healthCheckPending || healthCheckDisabled}
          >
            {healthCheckPending ? __('Checking\u2026', 'alt-context') : __('Check health', 'alt-context')}
          </button>
        </div>
      ) : null}
    </div>
  );
};