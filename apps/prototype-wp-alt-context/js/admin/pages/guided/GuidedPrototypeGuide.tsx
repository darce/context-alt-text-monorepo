import React from 'react';

import { guidedCopy } from '../../guidedPrototype/copy';
import { guidedCopy as publicGuidedCopy } from '../../guidedPrototype/publicGuideCopy';
import { GUIDED_STEP, type GuidedStep } from '../../guidedPrototype/state';

export type GuidedGuideStep = GuidedStep;

const STEP_TITLE = {
  [GUIDED_STEP.CONTEXT]: 'step.context',
  [GUIDED_STEP.NAMES]: 'step.names',
  [GUIDED_STEP.DRAFT]: 'step.draft',
  [GUIDED_STEP.APPLY]: 'step.apply',
} as const;

const PUBLIC_STEP_TITLE = {
  [GUIDED_STEP.CONTEXT]: 'step.names.public',
  [GUIDED_STEP.NAMES]: null,
  [GUIDED_STEP.DRAFT]: 'step.review.public',
  [GUIDED_STEP.APPLY]: null,
} as const;

export const GUIDED_FACE_SECTION_ID = 'guided-section-face';

export const GUIDED_SECTION_IDS = {
  [GUIDED_STEP.CONTEXT]: 'guided-section-understand',
  [GUIDED_STEP.NAMES]: GUIDED_FACE_SECTION_ID,
  [GUIDED_STEP.DRAFT]: 'guided-section-review',
  [GUIDED_STEP.APPLY]: 'guided-section-apply',
} as const;

export const GUIDE_STEPS: readonly GuidedStep[] = [
  GUIDED_STEP.CONTEXT,
  GUIDED_STEP.NAMES,
  GUIDED_STEP.DRAFT,
  GUIDED_STEP.APPLY,
];

export const PUBLIC_GUIDE_STEPS: readonly GuidedStep[] = [GUIDED_STEP.CONTEXT, GUIDED_STEP.DRAFT];

export type GuidedPrototypeGuideScope = 'public' | 'admin';

export const guideStepsForScope = (scope: GuidedPrototypeGuideScope): readonly GuidedStep[] =>
  scope === 'public' ? PUBLIC_GUIDE_STEPS : GUIDE_STEPS;

export const PUBLIC_GUIDED_STEP_FALLBACKS = {
  [GUIDED_STEP.CONTEXT]: GUIDED_STEP.CONTEXT,
  [GUIDED_STEP.NAMES]: GUIDED_STEP.CONTEXT,
  [GUIDED_STEP.DRAFT]: GUIDED_STEP.DRAFT,
  [GUIDED_STEP.APPLY]: GUIDED_STEP.DRAFT,
} as const;

export const guidedStepLabel = (step: GuidedStep): string => guidedCopy(STEP_TITLE[step]);

export const guidedStepLabelForScope = (step: GuidedStep, scope: GuidedPrototypeGuideScope): string => {
  const publicStepTitle = PUBLIC_STEP_TITLE[step];
  return scope === 'public' && publicStepTitle !== null
    ? publicGuidedCopy(publicStepTitle)
    : guidedStepLabel(step);
};

export const resolveGuidedStepForScope = (
  activeStep: GuidedStep,
  scope: GuidedPrototypeGuideScope,
): GuidedStep => {
  const steps = guideStepsForScope(scope);
  return steps.includes(activeStep) ? activeStep : PUBLIC_GUIDED_STEP_FALLBACKS[activeStep];
};

const guidedStepIndexForList = (steps: readonly GuidedStep[], step: GuidedStep): number => {
  const index = steps.indexOf(step);
  if (index < 0) {
    throw new Error(`Guided step "${step}" is not in the rendered step list.`);
  }

  return index;
};

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
  scope?: GuidedPrototypeGuideScope;
}

export const GuidedPrototypeGuide = ({
  activeStep,
  open,
  onToggle,
  onSelect,
  scope = 'admin',
}: GuidedPrototypeGuideProps): React.JSX.Element => {
  const renderedSteps = guideStepsForScope(scope);
  const currentStep = resolveGuidedStepForScope(activeStep, scope);
  const currentStepIndex = guidedStepIndexForList(renderedSteps, currentStep);
  const stepNumber = currentStepIndex + 1;
  const stepTitle = guidedStepLabelForScope(currentStep, scope);
  const currentGuideLabel =
    scope === 'public'
      ? publicGuidedCopy('guide.current.public', {
          stepNumber,
          stepCount: renderedSteps.length,
          stepTitle,
        })
      : guidedCopy('guide.current', { stepNumber, stepTitle });

  return (
    <nav className="acx-guided-guide" aria-label={guidedCopy('guide.label')} data-testid="guided-demo-stepper">
      <div className="acx-guided-guide__bar">
        <div>
          <p className="acx-guided-guide__eyebrow">{guidedCopy('guide.label')}</p>
          <strong>{currentGuideLabel}</strong>
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
            {renderedSteps.map((step, index) => {
              const isCurrent = step === currentStep;
              const label = guidedStepLabelForScope(step, scope);
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
