import { fireEvent, render, screen, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import type { FaceThumbnailProps } from '../../../../components/ui/FaceThumbnail';
import { guidedCopy } from '../../../guidedPrototype/publicGuideCopy';
import {
  GUIDED_NAME_CHOICE,
  chooseGuidedName,
  createGuidedDemoState,
  createGuidedScenario,
  guidedNameCoverage,
  type GuidedFacePosition,
  type GuidedNameChoice,
} from '../../../guidedPrototype/state';
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

type ChooseName = (position: GuidedFacePosition, choice: GuidedNameChoice, origin: HTMLInputElement) => void;

const renderPanel = (
  state = createGuidedDemoState(),
  handlers?: {
    onChoose?: ChooseName;
    onContinue?: () => void;
  },
) => {
  const onChoose = handlers?.onChoose ?? vi.fn();
  const onContinue = handlers?.onContinue ?? vi.fn();
  const onConfirmReplacement = vi.fn();
  const onCancelReplacement = vi.fn();
  const view = render(
    <GuidedFacesPanel
      scenario={scenario}
      state={state}
      onChoose={onChoose}
      onContinue={onContinue}
      onConfirmReplacement={onConfirmReplacement}
      onCancelReplacement={onCancelReplacement}
    />,
  );

  return { ...view, onChoose, onContinue, onConfirmReplacement, onCancelReplacement };
};

describe('GuidedFacesPanel and GuidedFaceMatchCard', () => {
  it('puts a native unselected radio group inside each evidence article', () => {
    const { onChoose } = renderPanel();

    expect(screen.getByRole('heading', { name: guidedCopy('step.names') })).toBeInTheDocument();
    expect(screen.getByText(guidedCopy('names.intro'))).toBeInTheDocument();
    expect(screen.getByText(guidedCopy('names.assisted'))).toBeInTheDocument();
    expect(screen.queryByText(/How this works/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Match strength/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Yes, this is/)).not.toBeInTheDocument();

    const cards = screen.getAllByRole('article');
    expect(cards).toHaveLength(2);

    const left = screen.getByTestId('name-choice-left');
    const right = screen.getByTestId('name-choice-right');
    expect(cards[0]).toContainElement(left);
    expect(cards[1]).toContainElement(right);
    expect(left.tagName).toBe('FIELDSET');
    expect(right.tagName).toBe('FIELDSET');
    expect(within(left).getByText(guidedCopy('names.legend', { position: 'left' }))).toBeInTheDocument();
    expect(within(right).getByText(guidedCopy('names.legend', { position: 'right' }))).toBeInTheDocument();

    const leftRadios = within(left).getAllByRole('radio') as HTMLInputElement[];
    const rightRadios = within(right).getAllByRole('radio') as HTMLInputElement[];
    expect(leftRadios).toHaveLength(2);
    expect(rightRadios).toHaveLength(2);
    expect(leftRadios.every((radio) => !radio.checked)).toBe(true);
    expect(rightRadios.every((radio) => !radio.checked)).toBe(true);
    expect(within(cards[0]).getByText(guidedCopy('names.pending'))).toBeInTheDocument();
    expect(screen.getByRole('button', { name: guidedCopy('names.next') })).toBeDisabled();

    fireEvent.click(within(left).getByRole('radio', { name: guidedCopy('names.include', { name: 'Justin Trudeau' }) }));
    fireEvent.click(within(right).getByRole('radio', { name: guidedCopy('names.omit') }));
    expect(onChoose).toHaveBeenCalledWith('left', GUIDED_NAME_CHOICE.INCLUDE, expect.any(HTMLInputElement));
    expect(onChoose).toHaveBeenCalledWith('right', GUIDED_NAME_CHOICE.OMIT, expect.any(HTMLInputElement));
  });

  it('shows bundled reference counts and credits without inventing missing photos', () => {
    renderPanel();

    const cards = screen.getAllByRole('article');
    expect(within(cards[0]).getByText(guidedCopy('names.coverage_all', { total: 3 }))).toBeInTheDocument();
    expect(
      within(cards[1]).getByText(guidedCopy('names.coverage_partial', { shown: 3, total: 5 })),
    ).toBeInTheDocument();
    expect(within(cards[0]).getAllByRole('img', { name: /Justin Trudeau/ })).toHaveLength(3);
    expect(within(cards[1]).getAllByRole('img', { name: /Katy Perry/ })).toHaveLength(3);
    expect(within(cards[0]).getAllByText('© European Union, 2025, EU reuse licence, resized')).toHaveLength(2);
    expect(within(cards[1]).getByText('Justin Higuchi, CC BY 4.0, resized')).toHaveClass('screen-reader-text');

    const thumbnails = screen.getAllByTestId('face-thumbnail');
    expect(thumbnails.map((thumbnail) => thumbnail.getAttribute('data-bbox'))).toEqual([
      JSON.stringify({ x: 513, y: 76, width: 133, height: 189 }),
      JSON.stringify({ x: 196, y: 182, width: 89, height: 129 }),
      JSON.stringify({ x: 706, y: 139, width: 121, height: 182 }),
      JSON.stringify({ x: 386, y: 196, width: 80, height: 118 }),
    ]);
    expect(thumbnails.map((thumbnail) => thumbnail.getAttribute('data-media-url'))).toEqual([
      scenario.pressPhotos[0].src,
      scenario.pressPhotos[1].src,
      scenario.pressPhotos[0].src,
      scenario.pressPhotos[1].src,
    ]);
    expect(thumbnails[0]).toHaveAttribute('data-alt', 'Detected left face in Tribeca press photo');
    expect(thumbnails[1]).toHaveAttribute('data-alt', 'Detected left face in Coachella press photo');
    expect(thumbnails[2]).toHaveAttribute('data-alt', 'Detected right face in Tribeca press photo');
    expect(thumbnails[3]).toHaveAttribute('data-alt', 'Detected right face in Coachella press photo');
  });

  it('reflects include and omit as ordinary selected states', () => {
    let state = createGuidedDemoState();
    state = chooseGuidedName(state, scenario, 'left', GUIDED_NAME_CHOICE.INCLUDE);
    state = chooseGuidedName(state, scenario, 'right', GUIDED_NAME_CHOICE.OMIT);
    renderPanel(state);

    expect(
      within(screen.getByTestId('name-choice-left')).getByRole('radio', {
        name: guidedCopy('names.include', { name: 'Justin Trudeau' }),
      }),
    ).toBeChecked();
    expect(
      within(screen.getByTestId('name-choice-right')).getByRole('radio', { name: guidedCopy('names.omit') }),
    ).toBeChecked();
    expect(screen.getByText(guidedCopy('names.included', { name: 'Justin Trudeau' }))).toBeInTheDocument();
    expect(screen.getByText(guidedCopy('names.omitted'))).toBeInTheDocument();
    expect(screen.getByRole('button', { name: guidedCopy('names.next') })).toBeEnabled();
  });

  it('renders the fieldset on a standalone card', () => {
    const face = scenario.faces.find((candidate) => candidate.position === 'left');
    if (!face) {
      throw new Error('Expected the bundled two-face scenario fixture.');
    }
    const person = scenario.people.find((candidate) => candidate.key === face.matchedPersonKey);
    const coverage = guidedNameCoverage(scenario).find((entry) => entry.key === face.matchedPersonKey);
    if (!person || !coverage) {
      throw new Error('Expected the bundled person and coverage fixture.');
    }

    render(
      <GuidedFaceMatchCard
        matches={scenario.faces
          .filter((candidate) => candidate.matchedPersonKey === face.matchedPersonKey)
          .map((candidate) => ({
            face: candidate,
            mediaUrl: scenario.pressPhotos.find((photo) => photo.key === candidate.imageKey)?.src ?? '',
          }))}
        person={person}
        coverage={coverage}
        choice={GUIDED_NAME_CHOICE.UNDECIDED}
        disabled={false}
        onChoose={vi.fn()}
      />,
    );
    expect(screen.getByRole('article')).toHaveAttribute('aria-labelledby', `guided-face-${person.key}-title`);
    expect(screen.getByTestId('name-choice-left')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: guidedCopy('names.enlarge') })).toBeInTheDocument();
    expect(screen.getAllByTestId('face-thumbnail')[0]).toHaveAttribute(
      'data-alt',
      'Detected left face in Tribeca press photo',
    );
  });
});
