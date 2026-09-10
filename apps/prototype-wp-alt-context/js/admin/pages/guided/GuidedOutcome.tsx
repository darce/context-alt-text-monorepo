import React from 'react';

import { guidedCopy } from '../../guidedPrototype/publicGuideCopy';
import {
  GUIDED_IMAGE_KEYS,
  GUIDED_OUTCOME,
  type GuidedImageKey,
  type GuidedOutcome as GuidedOutcomeValue,
} from '../../guidedPrototype/state';

export interface GuidedOutcomeSummary {
  imageKey: GuidedImageKey;
  label: string;
  outcome: GuidedOutcomeValue;
  appliedAltText?: string;
}

export type GuidedOutcomeInput = GuidedOutcomeValue | Partial<Record<GuidedImageKey, GuidedOutcomeValue>>;

export interface GuidedOutcomeProps {
  outcome?: GuidedOutcomeInput;
  onReturn: () => void;
  scope?: 'public' | 'admin';
  outcomes?: Partial<Record<GuidedImageKey, GuidedOutcomeValue>>;
  summaries?: readonly GuidedOutcomeSummary[];
}

const GUIDED_IMAGE_LABELS: Record<GuidedImageKey, string> = {
  tribeca: 'Tribeca',
  coachella: 'Coachella',
};

const outcomeSummaries = (
  outcome: GuidedOutcomeInput | undefined,
  outcomes: Partial<Record<GuidedImageKey, GuidedOutcomeValue>> | undefined,
  summaries: readonly GuidedOutcomeSummary[] | undefined,
): readonly GuidedOutcomeSummary[] => {
  if (summaries !== undefined) {
    return summaries;
  }

  const perImage = outcomes ?? (typeof outcome === 'object' && outcome !== null ? outcome : undefined);
  if (perImage !== undefined) {
    return GUIDED_IMAGE_KEYS.map((imageKey) => ({
      imageKey,
      label: GUIDED_IMAGE_LABELS[imageKey],
      outcome: perImage[imageKey] ?? GUIDED_OUTCOME.NOT_FINISHED,
    }));
  }

  return [];
};

export const GuidedOutcome = ({
  outcome,
  onReturn,
  scope = 'admin',
  outcomes,
  summaries,
}: GuidedOutcomeProps): React.JSX.Element | null => {
  const imageSummaries = outcomeSummaries(outcome, outcomes, summaries);
  const singleOutcome = typeof outcome === 'string' ? outcome : undefined;
  const allOutcomes = imageSummaries.length > 0 ? imageSummaries.map((summary) => summary.outcome) : [singleOutcome];
  if (allOutcomes.every((value) => value === undefined || value === GUIDED_OUTCOME.NOT_FINISHED)) {
    return null;
  }

  const applied = allOutcomes.some((value) => value === GUIDED_OUTCOME.APPLIED);
  const publicScope = scope === 'public';

  return (
    <section className="acx-guided-outcome" data-testid="demo-outcome" aria-labelledby="acx-guided-outcome-title">
      <h2 id="acx-guided-outcome-title">{applied ? guidedCopy('outcome.applied') : guidedCopy('outcome.kept')}</h2>
      {applied ? (
        <p>{guidedCopy('apply.success')}</p>
      ) : (
        <p>{guidedCopy(publicScope ? 'outcome.kept_body.public' : 'outcome.kept_body')}</p>
      )}
      {imageSummaries.length > 0 ? (
        <ul data-testid="guided-outcome-summaries">
          {imageSummaries.map((summary) => (
            <li key={summary.imageKey} data-image-key={summary.imageKey}>
              <h3>{summary.label}</h3>
              <p>
                {summary.outcome === GUIDED_OUTCOME.APPLIED
                  ? guidedCopy('outcome.applied')
                  : guidedCopy('outcome.kept')}
              </p>
              {summary.appliedAltText !== undefined ? <p data-applied-text>{summary.appliedAltText}</p> : null}
            </li>
          ))}
        </ul>
      ) : null}
      {publicScope ? (
        <>
          <p>{guidedCopy('outcome.scope.public')}</p>
          <p>{guidedCopy('outcome.next_batch.public')}</p>
        </>
      ) : null}
      <button type="button" className="acx-button acx-button--secondary" onClick={onReturn}>
        {guidedCopy('outcome.return')}
      </button>
    </section>
  );
};

GuidedOutcome.displayName = 'GuidedOutcome';
