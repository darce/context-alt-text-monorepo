import React from 'react';

import { guidedCopy } from '../../guidedPrototype/copy';
import { GUIDED_STEP, guidedStepIndex, type GuidedStep } from '../../guidedPrototype/state';

export type GuidedGuideStep = GuidedStep;

const STEP_TITLE = {
  [GUIDED_STEP.CONTEXT]: 'step.context',
  [GUIDED_STEP.NAMES]: 'step.names',
  [GUIDED_STEP.DRAFT]: 'step.draft',
  [GUIDED_STEP.APPLY]: 'step.apply',
} as const;

export const GUIDED_SECTION_IDS: Record<GuidedStep, string> = {
  [GUIDED_STEP.CONTEXT]: 'guided-section-understand',
  [GUIDED_STEP.NAMES]: 'guided-section-identity',
  [GUIDED_STEP.DRAFT]: 'guided-section-review',
  [GUIDED_STEP.APPLY]: 'guided-section-apply',
};

export const GUIDED_FACE_SECTION_ID = 'guided-section-face';

export const GUIDE_STEPS: readonly GuidedStep[] = [
  GUIDED_STEP.CONTEXT,
  GUIDED_STEP.NAMES,
  GUIDED_STEP.DRAFT,
  GUIDED_STEP.APPLY,
];

export const guidedStepLabel = (step: GuidedStep): string => guidedCopy(STEP_TITLE[step]);

export const focusGuidedSection = (step: GuidedStep): void => {
  const target = document.getElementById(GUIDED_SECTION_IDS[step]);
  if (!target) {
    return;
  }

  const prefersReducedMotion =
    typeof window !== 'undefined' &&
    typeof window.matchMedia === 'function' &&
    window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  target.scrollIntoView({ behavior: prefersReducedMotion ? 'auto' : 'smooth', block: 'start' });
  target.focus();
};

export interface GuidedPrototypeGuideProps {
  activeStep: GuidedStep;
  open: boolean;
  onToggle: () => void;
  onSelect: (step: GuidedStep) => void;
}

export const GuidedPrototypeGuide = ({
  activeStep,
  open,
  onToggle,
  onSelect,
}: GuidedPrototypeGuideProps): React.JSX.Element => {
  const stepNumber = guidedStepIndex(activeStep) + 1;
  const stepTitle = guidedStepLabel(activeStep);

  return (
    <nav className="acx-guided-guide" aria-label={guidedCopy('guide.label')} data-testid="guided-demo-stepper">
      <div className="acx-guided-guide__bar">
        <div>
          <p className="acx-guided-guide__eyebrow">{guidedCopy('guide.label')}</p>
          <strong>{guidedCopy('guide.current', { stepNumber, stepTitle })}</strong>
        </div>
        <button
          type="button"
          className="acx-button acx-button--secondary acx-guided-guide__toggle"
          aria-expanded={open}
          onClick={onToggle}
        >
          {open ? guidedCopy('guide.hide') : guidedCopy('guide.show')}
        </button>
      </div>
      {open ? (
        <div className="acx-guided-guide__body">
          <ol>
            {GUIDE_STEPS.map((step, index) => {
              const isCurrent = step === activeStep;
              const label = guidedStepLabel(step);
              return (
                <li key={step} className={isCurrent ? 'is-current' : undefined}>
                  <button
                    type="button"
                    onClick={() => {
                      onSelect(step);
                      focusGuidedSection(step);
                    }}
                    aria-current={isCurrent ? 'step' : undefined}
                    aria-controls={GUIDED_SECTION_IDS[step]}
                  >
                    <span aria-hidden="true">{index + 1}</span>
                    <span>
                      <strong>{label}</strong>
                    </span>
                  </button>
                </li>
              );
            })}
          </ol>
        </div>
      ) : null}
    </nav>
  );
};

GuidedPrototypeGuide.displayName = 'GuidedPrototypeGuide';
