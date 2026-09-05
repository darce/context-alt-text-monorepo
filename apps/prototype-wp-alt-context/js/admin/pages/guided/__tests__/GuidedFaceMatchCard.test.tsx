import { fireEvent, render, screen, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { createGuidedScenario, type GuidedIdentity } from '../../../guidedPrototype/state';
import { GuidedFaceMatchCard } from '../GuidedFaceMatchCard';

const scenario = createGuidedScenario();

const renderCard = (identity: GuidedIdentity = scenario.identity, hasUnsavedEdit = false) => {
  const onConfirm = vi.fn();
  const onLeaveUnnamed = vi.fn();
  render(
    <GuidedFaceMatchCard
      faceMatch={scenario.faceMatch}
      identity={identity}
      mediaUrl={scenario.originalMedia.src}
      hasUnsavedEdit={hasUnsavedEdit}
      onConfirm={onConfirm}
      onLeaveUnnamed={onLeaveUnnamed}
    />,
  );
  return { onConfirm, onLeaveUnnamed };
};

describe('GuidedFaceMatchCard', () => {
  it('shows the face crop, the count, the match and its strength before asking for a decision', () => {
    renderCard();

    const card = document.getElementById('guided-section-face');
    expect(card).not.toBeNull();
    expect(card).toHaveAttribute('tabindex', '-1');
    expect(card).toHaveAttribute('aria-labelledby', 'guided-face-match-title');
    expect(screen.getByRole('heading', { level: 3, name: 'Face found in the photo' })).toHaveAttribute(
      'id',
      'guided-face-match-title',
    );
    expect(screen.getByRole('img', { name: 'Face found in the photo' })).toBeInTheDocument();
    expect(screen.getByText('AltContext found 1 face.')).toBeInTheDocument();
    expect(screen.getByText(/It matches a person you named before:/)).toHaveTextContent('Keanu Reeves');
    expect(screen.getByText(/Match strength: strong\./)).toHaveTextContent(
      'This face is close to 3 saved photos of Keanu Reeves.',
    );

    const steps = screen.getByRole('list', { name: 'How this works' });
    expect(within(steps).getAllByRole('listitem').map((item) => item.textContent)).toEqual([
      'AltContext finds faces in the photo.',
      'It compares each face to people you already named.',
      'It asks you to confirm. Nothing is named without your OK.',
    ]);
    expect(
      screen.getByText('This match was saved from an earlier run. The demo does not run recognition live.'),
    ).toBeInTheDocument();
  });

  it('offers both decisions from the undecided state and reports each choice', () => {
    const { onConfirm, onLeaveUnnamed } = renderCard();

    expect(screen.getByText('You have not decided yet.')).toBeInTheDocument();
    const actions = document.getElementById('guided-section-identity');
    expect(actions).toHaveAttribute('tabindex', '-1');
    expect(actions).toHaveAttribute('aria-label', 'Confirm the match');

    fireEvent.click(screen.getByRole('button', { name: 'Yes, this is Keanu Reeves' }));
    expect(onConfirm).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole('button', { name: 'Keep the person unnamed' }));
    expect(onLeaveUnnamed).toHaveBeenCalledTimes(1);
  });

  it('states the decision once it is made and explains why the answer cannot change mid-edit', () => {
    renderCard({ status: 'confirmed', name: 'Keanu Reeves', source: 'face-match' }, true);
    expect(screen.getByText('You confirmed: Keanu Reeves.')).toBeInTheDocument();
    const confirm = screen.getByRole('button', { name: 'Yes, this is Keanu Reeves' });
    const unnamed = screen.getByRole('button', { name: 'Keep the person unnamed' });
    expect(confirm).toBeDisabled();
    expect(unnamed).toBeDisabled();
    expect(unnamed).toHaveAttribute('aria-describedby', 'guided-identity-change-reason');
    expect(document.getElementById('guided-identity-change-reason')).toHaveTextContent(
      'Changing your answer swaps in a different saved draft. Save or discard your edit first.',
    );
  });

  it('reads the unnamed decision back in plain words', () => {
    renderCard({ status: 'unidentified', source: 'none' });

    expect(screen.getByText('You kept the person unnamed.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Keep the person unnamed' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Yes, this is Keanu Reeves' })).not.toBeDisabled();
  });
});
