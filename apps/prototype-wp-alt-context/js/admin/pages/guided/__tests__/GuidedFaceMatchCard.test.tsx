import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import type { FaceThumbnailProps } from '../../../../components/ui/FaceThumbnail';
import {
  confirmGuidedIdentity,
  createGuidedScenario,
  leaveGuidedIdentityUnidentified,
  type GuidedPersonKey,
} from '../../../guidedPrototype/state';
import { GuidedDescriptionReview } from '../GuidedDescriptionReview';
import { GuidedFaceMatchCard } from '../GuidedFaceMatchCard';
import { GuidedFacesPanel } from '../GuidedFacesPanel';

vi.mock('../../../../components/ui/FaceThumbnail', () => ({
  FaceThumbnail: ({ alt, bbox, mediaUrl, shape, size }: FaceThumbnailProps) => (
    <div
      role="img"
      aria-label={alt}
      data-testid="face-thumbnail"
      data-alt={alt}
      data-bbox={JSON.stringify(bbox)}
      data-media-url={mediaUrl}
      data-shape={shape}
      data-size={size}
    />
  ),
}));

const scenario = createGuidedScenario();
const JUSTIN: GuidedPersonKey = 'justin-trudeau';
const KATY: GuidedPersonKey = 'katy-perry';

const renderPanel = (currentScenario = scenario, hasUnsavedEdit = false) => {
  const onConfirm = vi.fn();
  const onLeaveUnnamed = vi.fn();
  const view = render(
    <GuidedFacesPanel
      scenario={currentScenario}
      hasUnsavedEdit={hasUnsavedEdit}
      onConfirm={onConfirm}
      onLeaveUnnamed={onLeaveUnnamed}
    />,
  );

  return { ...view, onConfirm, onLeaveUnnamed };
};

const renderReview = (currentScenario = scenario) =>
  render(
    <GuidedDescriptionReview
      liveMediaId={null}
      scenario={currentScenario}
      resetVersion={0}
      onSaveEdit={vi.fn(() => undefined)}
      onReject={vi.fn()}
      onApply={vi.fn()}
      onUndo={vi.fn()}
    />,
  );

const getDecisionBlock = (): HTMLElement => {
  const block = document.getElementById('guided-section-identity');
  if (!(block instanceof HTMLElement)) {
    throw new Error('Expected the guided identity decisions block.');
  }
  return block;
};

const getDecisionRows = (block: HTMLElement): HTMLElement[] =>
  Array.from(block.querySelectorAll<HTMLElement>('.acx-guided-face__decision-row'));

describe('GuidedFacesPanel and GuidedFaceMatchCard', () => {
  it('renders the two matched faces, evidence, galleries, and shared decisions in face order', () => {
    const { onConfirm, onLeaveUnnamed } = renderPanel();

    const faceSection = screen.getByRole('region', { name: 'Faces found in the photo' });
    expect(faceSection).toHaveAttribute('tabindex', '-1');
    expect(faceSection).toHaveAttribute('aria-labelledby', 'guided-faces-title');
    expect(screen.getByRole('heading', { level: 3, name: 'Faces found in the photo' })).toBeInTheDocument();
    expect(
      screen.getByText('AltContext found 2 faces. Each one matched a person you named before.'),
    ).toBeInTheDocument();

    const steps = within(faceSection).getAllByRole('list')[0];
    expect(screen.queryByText('How this works')).not.toBeInTheDocument();
    expect(
      within(steps)
        .getAllByRole('listitem')
        .map((item) => item.textContent),
    ).toEqual([
      'AltContext finds every face in the photo.',
      'It compares each face to the people you already named.',
      'It asks you to confirm each match. Nothing is named without your OK.',
    ]);
    expect(
      screen.getByText('These matches were saved from a real run. The demo does not run recognition live.'),
    ).toBeInTheDocument();

    const cards = screen.getAllByRole('article');
    expect(cards).toHaveLength(2);
    expect(cards[0]).toHaveClass('acx-guided-face__card');
    expect(cards[1]).toHaveClass('acx-guided-face__card');

    const leftCard = cards[0];
    const rightCard = cards[1];
    expect(leftCard).toHaveAttribute('aria-labelledby', 'guided-face-justin-trudeau-title');
    expect(rightCard).toHaveAttribute('aria-labelledby', 'guided-face-katy-perry-title');
    expect(within(leftCard).getByRole('heading', { level: 4, name: 'Face on the left' })).toBeInTheDocument();
    expect(within(rightCard).getByRole('heading', { level: 4, name: 'Face on the right' })).toBeInTheDocument();
    expect(within(leftCard).getByText(/It matches a person you named before:/)).toHaveTextContent('Justin Trudeau');
    expect(within(rightCard).getByText(/It matches a person you named before:/)).toHaveTextContent('Katy Perry');
    expect(within(leftCard).getByText(/Match strength: strong\./)).toHaveTextContent(
      'This face is close to the 2 saved photos of Justin Trudeau.',
    );
    expect(within(rightCard).getByText(/Match strength: strong\./)).toHaveTextContent(
      'This face is close to the 5 saved photos of Katy Perry.',
    );
    expect(within(leftCard).queryByText('Her face is turned a little to the side.')).not.toBeInTheDocument();
    expect(within(rightCard).getByText('Her face is turned a little to the side.')).toBeInTheDocument();
    expect(within(leftCard).queryByRole('button')).not.toBeInTheDocument();
    expect(within(rightCard).queryByRole('button')).not.toBeInTheDocument();

    const thumbnails = screen.getAllByTestId('face-thumbnail');
    expect(thumbnails.map((thumbnail) => thumbnail.getAttribute('data-bbox'))).toEqual([
      JSON.stringify({ x: 514, y: 77, width: 132, height: 189 }),
      JSON.stringify({ x: 707, y: 140, width: 121, height: 181 }),
    ]);
    expect(thumbnails.map((thumbnail) => thumbnail.getAttribute('data-alt'))).toEqual([
      'Face on the left',
      'Face on the right',
    ]);
    expect(thumbnails.every((thumbnail) => thumbnail.getAttribute('data-size') === 'lg')).toBe(true);
    expect(thumbnails.every((thumbnail) => thumbnail.getAttribute('data-shape') === 'square')).toBe(true);
    expect(thumbnails.every((thumbnail) => thumbnail.getAttribute('data-media-url') === scenario.pressPhoto.src)).toBe(
      true,
    );

    const justinGallery = within(leftCard).getByRole('list', { name: 'Saved photos of Justin Trudeau' });
    const katyGallery = within(rightCard).getByRole('list', { name: 'Saved photos of Katy Perry' });
    expect(within(justinGallery).getAllByRole('img')).toHaveLength(2);
    expect(within(katyGallery).getAllByRole('img')).toHaveLength(3);
    expect(
      within(justinGallery)
        .getAllByRole('img')
        .every((image) => image.getAttribute('loading') === 'lazy'),
    ).toBe(true);
    expect(
      within(katyGallery)
        .getAllByRole('img')
        .every((image) => image.getAttribute('loading') === 'lazy'),
    ).toBe(true);
    expect(within(leftCard).getByText('Saved photos of Justin Trudeau: 2 of 2 shown.')).toBeInTheDocument();
    expect(within(rightCard).getByText('Saved photos of Katy Perry: 3 of 5 shown.')).toBeInTheDocument();
    expect(within(leftCard).getAllByText('© European Union, 2025, EU reuse licence, resized')).toHaveLength(2);
    expect(within(rightCard).getByText('Justin Higuchi, CC BY 4.0, resized')).toHaveClass('screen-reader-text');

    const decisions = getDecisionBlock();
    expect(decisions).toHaveAttribute('tabindex', '-1');
    expect(decisions).toHaveAttribute('aria-label', 'Confirm each match');
    expect(decisions).toHaveClass('acx-guided-face__decisions');
    expect(screen.getByRole('heading', { level: 4, name: 'Confirm each match' })).toBeInTheDocument();
    expect(
      screen.getByText('Changing an answer swaps in a different saved draft. Save or discard your edit first.'),
    ).toHaveAttribute('id', 'guided-identity-change-reason');

    const rows = getDecisionRows(decisions);
    expect(rows).toHaveLength(2);
    expect(within(rows[0]).getByText('Justin Trudeau, face on the left')).toBeInTheDocument();
    expect(within(rows[1]).getByText('Katy Perry, face on the right')).toBeInTheDocument();
    expect(within(rows[0]).getByRole('button', { name: 'Yes, this is Justin Trudeau' })).toBeEnabled();
    expect(within(rows[1]).getByRole('button', { name: 'Yes, this is Katy Perry' })).toBeEnabled();
    expect(within(rows[0]).getByRole('button', { name: 'Keep this person unnamed' })).toBeEnabled();
    expect(within(rows[1]).getByRole('button', { name: 'Keep this person unnamed' })).toBeEnabled();

    fireEvent.click(within(rows[0]).getByRole('button', { name: 'Yes, this is Justin Trudeau' }));
    fireEvent.click(within(rows[1]).getByRole('button', { name: 'Keep this person unnamed' }));
    expect(onConfirm).toHaveBeenCalledWith(JUSTIN);
    expect(onLeaveUnnamed).toHaveBeenCalledWith(KATY);
  });

  it('disables both answers and describes them while the description has an unsaved edit', () => {
    renderPanel(scenario, true);

    const rows = getDecisionRows(getDecisionBlock());
    for (const row of rows) {
      const buttons = within(row).getAllByRole('button');
      expect(buttons).toHaveLength(2);
      for (const button of buttons) {
        expect(button).toBeDisabled();
        expect(button).toHaveAttribute('aria-describedby', 'guided-identity-change-reason');
      }
    }
  });

  it('only disables the answer that matches an existing decision when there is no unsaved edit', () => {
    const justinConfirmed = confirmGuidedIdentity(scenario, JUSTIN);
    renderPanel(justinConfirmed);

    const rows = getDecisionRows(getDecisionBlock());
    expect(within(rows[0]).getByRole('button', { name: 'Yes, this is Justin Trudeau' })).toBeDisabled();
    expect(within(rows[0]).getByRole('button', { name: 'Keep this person unnamed' })).toBeEnabled();
    expect(within(rows[0]).getByRole('button', { name: 'Yes, this is Justin Trudeau' })).not.toHaveAttribute(
      'aria-describedby',
    );
    expect(within(rows[0]).getByRole('button', { name: 'Keep this person unnamed' })).not.toHaveAttribute(
      'aria-describedby',
    );

    cleanup();
    const katyUnidentified = leaveGuidedIdentityUnidentified(scenario, KATY);
    renderPanel(katyUnidentified);
    const nextRows = getDecisionRows(getDecisionBlock());
    expect(within(nextRows[1]).getByRole('button', { name: 'Keep this person unnamed' })).toBeDisabled();
    expect(within(nextRows[1]).getByRole('button', { name: 'Yes, this is Katy Perry' })).toBeEnabled();
  });

  it('keeps the face controls in the panel and uses the four wave-2 explanation cases in review', () => {
    renderReview();

    expect(document.getElementById('guided-section-face')).toBeNull();
    expect(document.getElementById('guided-section-identity')).toBeNull();
    expect(screen.getByText(/Draft without names:/)).toHaveTextContent(`Draft without names: ${scenario.drafts.none}`);
    expect(screen.getByRole('heading', { level: 3, name: 'Without the names' })).toBeInTheDocument();
    expect(screen.getByText('This draft comes from a saved run, not a live one.')).toBeInTheDocument();
    expect(
      screen.getByText(
        'Decide each face match first: confirm it, or keep the person unnamed. Until then the draft only says what is visible.',
      ),
    ).toBeInTheDocument();
  });

  it('updates the review explanation for both, one, and zero confirmed matches', () => {
    const bothConfirmed = confirmGuidedIdentity(confirmGuidedIdentity(scenario, JUSTIN), KATY);
    renderReview(bothConfirmed);
    expect(
      screen.getByText(
        'You confirmed both matches, so both names are in the draft. The visual details and page context stay the same.',
      ),
    ).toBeInTheDocument();

    cleanup();
    const oneConfirmed = confirmGuidedIdentity(scenario, JUSTIN);
    renderReview(oneConfirmed);
    expect(
      screen.getByText(
        'You confirmed one match, so one name is in the draft. The other person is described, not named.',
      ),
    ).toBeInTheDocument();

    cleanup();
    const noneConfirmed = leaveGuidedIdentityUnidentified(leaveGuidedIdentityUnidentified(scenario, JUSTIN), KATY);
    renderReview(noneConfirmed);
    expect(
      screen.getByText('You kept both people unnamed, so the draft only says what is visible.'),
    ).toBeInTheDocument();
  });

  it('renders a presentational card without decision controls when mounted by itself', () => {
    const face = scenario.faces.find((candidate) => candidate.position === 'left');
    if (!face) {
      throw new Error('Expected the bundled two-face scenario fixture.');
    }
    const person = scenario.people.find((candidate) => candidate.key === face.matchedPersonKey);
    const identity = scenario.identities.find((candidate) => candidate.faceId === face.id);
    if (!person || !identity) {
      throw new Error('Expected the bundled person and identity fixture.');
    }

    render(<GuidedFaceMatchCard face={face} person={person} identity={identity} mediaUrl={scenario.pressPhoto.src} />);
    expect(screen.getByRole('article')).toHaveAttribute('aria-labelledby', `guided-face-${face.id}-title`);
    expect(screen.queryByRole('button')).not.toBeInTheDocument();
  });
});
