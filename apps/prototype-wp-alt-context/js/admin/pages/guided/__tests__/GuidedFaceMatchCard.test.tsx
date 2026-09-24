import { fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import type { FaceThumbnailProps } from '../../../../components/ui/FaceThumbnail';
import { guidedCopy } from '../../../guidedPrototype/publicGuideCopy';
import {
  GUIDED_NAME_CHOICE,
  createGuidedScenario,
  guidedNameCoverage,
  type GuidedFace,
  type GuidedFacePosition,
  type GuidedImageKey,
  type GuidedNameChoice,
} from '../../../guidedPrototype/state';
import { GuidedFaceMatchCard, type GuidedFaceMatchCardProps } from '../GuidedFaceMatchCard';

vi.mock('../../../../components/ui/FaceThumbnail', () => ({
  FaceThumbnail: ({ alt, bbox, mediaUrl, shape, size, sizePx }: FaceThumbnailProps) => (
    <div
      role="img"
      aria-label={alt}
      data-testid="face-thumbnail"
      data-alt={alt}
      data-bbox={JSON.stringify(bbox)}
      data-media-url={mediaUrl}
      data-shape={shape}
      data-size={size}
      data-size-px={sizePx}
    />
  ),
}));

const scenario = createGuidedScenario();

type ChooseName = (
  position: GuidedFacePosition,
  choice: GuidedNameChoice,
  origin: HTMLInputElement,
  imageKey: GuidedImageKey,
) => void;

const matchesFor = (face: GuidedFace) =>
  scenario.faces
    .filter((candidate) => candidate.imageKey === face.imageKey && candidate.matchedPersonKey === face.matchedPersonKey)
    .map((match) => {
      const photo = scenario.pressPhotos.find((candidate) => candidate.key === match.imageKey);
      if (photo === undefined) {
        throw new Error(`Missing guided press photo for ${match.imageKey}.`);
      }
      return { face: match, mediaUrl: photo.src };
    });

const cardFor = (
  faceId: string,
  props?: { choice?: GuidedNameChoice; onChoose?: GuidedFaceMatchCardProps['onChoose'] },
) => {
  const face = scenario.faces.find((candidate) => candidate.id === faceId);
  if (face === undefined) {
    throw new Error(`Missing guided face ${faceId}.`);
  }
  const person = scenario.people.find((candidate) => candidate.key === face.matchedPersonKey);
  const coverage = guidedNameCoverage(scenario).find((entry) => entry.key === face.matchedPersonKey);
  if (person === undefined || coverage === undefined) {
    throw new Error(`Missing person evidence for ${face.matchedPersonKey}.`);
  }

  return (
    <GuidedFaceMatchCard
      matches={matchesFor(face)}
      person={person}
      coverage={coverage}
      choice={props?.choice ?? GUIDED_NAME_CHOICE.UNANSWERED}
      idScope={face.imageKey}
      disabled={false}
      onChoose={props?.onChoose ?? vi.fn()}
    />
  );
};

const getRadioInputs = (group: HTMLElement): HTMLInputElement[] =>
  within(group)
    .getAllByRole('radio')
    .map((radio) => {
      if (!(radio instanceof HTMLInputElement)) {
        throw new Error('Expected a native radio input.');
      }
      return radio;
    });

const renderPhotoCards = (onChoose: ChooseName = vi.fn()) =>
  render(
    <div>
      {scenario.faces
        .filter((face) => face.imageKey === 'tribeca')
        .map((face) => (
          <div key={face.id} data-testid={`face-card-${face.position}`}>
            {cardFor(face.id, {
              onChoose: (choice, origin, imageKey) => onChoose(face.position, choice, origin, imageKey),
            })}
          </div>
        ))}
    </div>,
  );

describe('GuidedFaceMatchCard', () => {
  it('provides native per-photo radio groups with large answer targets', () => {
    const onChoose = vi.fn();
    renderPhotoCards(onChoose);

    const left = screen.getByRole('group', { name: guidedCopy('names.legend', { position: 'left' }) });
    const right = screen.getByRole('group', { name: guidedCopy('names.legend', { position: 'right' }) });
    expect(left.tagName).toBe('FIELDSET');
    expect(right.tagName).toBe('FIELDSET');
    expect(getRadioInputs(left)).toHaveLength(2);
    expect(getRadioInputs(right)).toHaveLength(2);
    expect([...getRadioInputs(left), ...getRadioInputs(right)].every((radio) => !radio.checked)).toBe(true);

    const useJustin = within(left).getByRole('radio', {
      name: guidedCopy('names.use.public', { name: 'Justin Trudeau' }),
    });
    const leaveUnnamed = within(right).getByRole('radio', { name: guidedCopy('names.omit.public') });
    expect(useJustin.closest('label')).toHaveStyle({ minHeight: '44px' });
    expect(leaveUnnamed.closest('label')).toHaveStyle({ minHeight: '44px' });
    const justinCard = screen.getByRole('region', {
      name: 'Justin Trudeau',
    });
    expect(within(justinCard).getByText(guidedCopy('names.strong.public')).closest('li')).toHaveStyle({
      minHeight: '64px',
    });
    expect(screen.getAllByRole('button', { name: guidedCopy('names.compare.public') })[0]).toHaveStyle({
      minHeight: '44px',
    });

    fireEvent.click(useJustin);
    fireEvent.click(leaveUnnamed);
    expect(onChoose).toHaveBeenCalledWith('left', GUIDED_NAME_CHOICE.USE, expect.any(HTMLInputElement), 'tribeca');
    expect(onChoose).toHaveBeenCalledWith(
      'right',
      GUIDED_NAME_CHOICE.LEAVE_UNNAMED,
      expect.any(HTMLInputElement),
      'tribeca',
    );
  });

  it('keeps the same person’s answer groups separate for Tribeca and Coachella', () => {
    render(
      <div>
        {scenario.faces.map((face) => (
          <div key={face.id}>{cardFor(face.id)}</div>
        ))}
      </div>,
    );

    const tribecaLeft = screen.getByTestId('name-choice-tribeca-left');
    const coachellaLeft = screen.getByTestId('name-choice-coachella-left');
    const tribecaRadios = getRadioInputs(tribecaLeft);
    const coachellaRadios = getRadioInputs(coachellaLeft);
    expect(tribecaRadios[0]).toHaveAttribute('name', 'guided-name-tribeca-left');
    expect(coachellaRadios[0]).toHaveAttribute('name', 'guided-name-coachella-left');
    expect(tribecaRadios.every((radio) => !radio.checked)).toBe(true);
    expect(coachellaRadios.every((radio) => !radio.checked)).toBe(true);
  });

  it('uses strength words, warns on weak evidence, and explains the anchor has no score', () => {
    renderPhotoCards();

    const justinCard = screen.getByRole('region', { name: 'Justin Trudeau' });
    const katyCard = screen.getByRole('region', { name: 'Katy Perry' });
    expect(within(justinCard).getByText(guidedCopy('names.strong.public'))).toBeInTheDocument();
    expect(
      within(katyCard).getByText(/No score: the saved group for this name started from this face\./),
    ).toBeInTheDocument();
    expect(justinCard).not.toHaveTextContent(/Saved suggestion:/);
    expect(justinCard.textContent).not.toMatch(/\d+(?:\.\d+)?%/);
    expect(katyCard.textContent).not.toMatch(/\d+(?:\.\d+)?%/);

    const weakCard = render(cardFor('coachella-katy-perry'));
    expect(screen.getByText(guidedCopy('names.weak.public'))).toBeInTheDocument();
    expect(screen.getByRole('img', { name: guidedCopy('names.match.weak_icon') })).toBeInTheDocument();
    weakCard.unmount();
  });

  it('opens a crop-first comparison with visible reference credits and restores focus on Escape', async () => {
    const user = userEvent.setup();
    render(cardFor('tribeca-katy-perry'));

    const compareButton = screen.getByRole('button', { name: guidedCopy('names.compare.public') });
    await user.click(compareButton);
    const dialog = await screen.findByRole('dialog', {
      name: guidedCopy('lightbox.title.public', { name: 'Katy Perry' }),
    });
    const currentPhotoHeading = within(dialog).getByRole('heading', { name: guidedCopy('lightbox.current.public') });
    const referenceHeading = within(dialog).getByRole('heading', {
      name: guidedCopy('lightbox.references.public', { name: 'Katy Perry' }),
    });
    expect(
      currentPhotoHeading.compareDocumentPosition(referenceHeading) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    const currentPhoto = within(dialog).getByTestId('face-thumbnail');
    expect(currentPhoto).toHaveAttribute('data-media-url', scenario.pressPhotos[0].src);
    expect(currentPhoto).toHaveAttribute('data-size-px', '160');

    const references = within(dialog).getAllByTestId('guided-lightbox-reference-photo');
    expect(references).toHaveLength(3);
    expect(references.map((reference) => reference.className)).toEqual(
      Array.from({ length: 3 }, () => 'acx-guided-face__lightbox-reference'),
    );
    expect(within(dialog).getByText('Voice of America, public domain')).not.toHaveClass('screen-reader-text');
    expect(within(dialog).getByText(guidedCopy('names.coverage_partial', { shown: 3, total: 5 }))).toBeInTheDocument();

    const closeButton = within(dialog).getByRole('button', { name: guidedCopy('lightbox.close.public') });
    expect(closeButton).toHaveStyle({ minHeight: '44px', minWidth: '44px' });
    await user.keyboard('{Escape}');
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(compareButton).toHaveFocus();
  });

  it('keeps the standalone card ids and selected answer aligned to its photo', () => {
    render(cardFor('tribeca-justin-trudeau', { choice: GUIDED_NAME_CHOICE.USE }));

    const card = screen.getByRole('region', { name: 'Justin Trudeau' });
    expect(card).toHaveAttribute('aria-labelledby', 'guided-face-tribeca-justin-trudeau-title');
    const fieldset = screen.getByTestId('name-choice-tribeca-left');
    const radios = within(fieldset).getAllByRole('radio');
    expect(radios[0]).toHaveAttribute('id', 'guided-name-tribeca-left-include');
    expect(radios[0]).toHaveAttribute('name', 'guided-name-tribeca-left');
    expect(radios[1]).toHaveAttribute('id', 'guided-name-tribeca-left-omit');
    expect(radios[1]).toHaveAttribute('name', 'guided-name-tribeca-left');
    expect(
      within(fieldset).getByRole('radio', {
        name: guidedCopy('names.use.public', { name: 'Justin Trudeau' }),
      }),
    ).toBeChecked();
    expect(within(card).getByRole('button', { name: guidedCopy('names.compare.public') })).toHaveAttribute(
      'id',
      'guided-name-tribeca-left-enlarge',
    );
  });
});
