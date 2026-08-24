import * as React from 'react';
import { __, sprintf } from '@wordpress/i18n';

/** [sr-007] Single canonical source for the workbench step values. */
export const STEP_MAP_VALUES = {
  scan: 'scan',
  confirm: 'confirm',
  review: 'review',
} as const;

export type StepMapValue = (typeof STEP_MAP_VALUES)[keyof typeof STEP_MAP_VALUES];

export interface StepMapStep {
  id: StepMapValue;
  label: string;
  onSelect?: () => void;
}

export interface StepMapProps {
  activeStep: StepMapValue;
  steps: readonly StepMapStep[];
}

export const StepMap = ({ activeStep, steps }: StepMapProps): React.JSX.Element => {
  const activeIndex = steps.findIndex((step) => step.id === activeStep);
  const active = steps[activeIndex];
  const position = activeIndex + 1;
  const positionText = sprintf(
    /* translators: 1: current step number, 2: total steps, 3: current step name. */
    __('Step %1$d of %2$d: %3$s', 'alt-context'),
    position,
    steps.length,
    active.label,
  );

  return (
    <nav className="acx-workbench-steps" aria-label={__('Progress', 'alt-context')}>
      <div className="acx-workbench-steps__position" role="status" aria-live="polite">
        {positionText}
      </div>
      <ol className="acx-workbench-steps__list" aria-label={__('Progress', 'alt-context')}>
        {steps.map((step, index) => {
          const isCurrent = step.id === activeStep;
          const isComplete = index < activeIndex;
          const state = isCurrent ? 'current' : isComplete ? 'complete' : 'remaining';
          const stateLabel = isCurrent
            ? __('Current', 'alt-context')
            : isComplete
              ? __('Completed', 'alt-context')
              : __('Remaining', 'alt-context');
          const itemClassName = `acx-workbench-steps__item acx-workbench-steps__item--${state}`;
          const content = (
            <>
              <span className="acx-workbench-steps__marker" aria-hidden="true">
                {isComplete ? '✓' : index + 1}
              </span>
              <span className="acx-workbench-steps__label">{step.label}</span>
              <span className={`acx-workbench-steps__status acx-workbench-steps__status--${state}`}>
                {stateLabel}
              </span>
            </>
          );

          return (
            <li
              key={step.id}
              className={itemClassName}
              aria-current={isCurrent ? 'step' : undefined}
              data-testid={`acx-workbench-step-${step.id}`}
            >
              {step.onSelect ? (
                <button type="button" className="acx-workbench-steps__control" onClick={step.onSelect}>
                  {content}
                </button>
              ) : (
                <span className="acx-workbench-steps__control">{content}</span>
              )}
            </li>
          );
        })}
      </ol>
    </nav>
  );
};

StepMap.displayName = 'StepMap';
