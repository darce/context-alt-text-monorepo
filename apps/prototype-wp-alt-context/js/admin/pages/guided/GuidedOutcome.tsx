import React from 'react';

import { guidedCopy } from '../../guidedPrototype/publicGuideCopy';
import { GUIDED_OUTCOME, type GuidedOutcome as GuidedOutcomeValue } from '../../guidedPrototype/state';

export interface GuidedOutcomeProps {
  outcome: GuidedOutcomeValue;
  onReturn: () => void;
  scope?: 'public' | 'admin';
}

export const GuidedOutcome = ({ outcome, onReturn, scope = 'admin' }: GuidedOutcomeProps): React.JSX.Element | null => {
  if (outcome === GUIDED_OUTCOME.NOT_FINISHED) {
    return null;
  }

  const applied = outcome === GUIDED_OUTCOME.APPLIED;
  const publicScope = scope === 'public';

  return (
    <section className="acx-guided-outcome" data-testid="demo-outcome" aria-labelledby="acx-guided-outcome-title">
      <h2 id="acx-guided-outcome-title">{applied ? guidedCopy('outcome.applied') : guidedCopy('outcome.kept')}</h2>
      {applied ? (
        <p>{guidedCopy('apply.success')}</p>
      ) : (
        <p>{guidedCopy(publicScope ? 'outcome.kept_body.public' : 'outcome.kept_body')}</p>
      )}
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
