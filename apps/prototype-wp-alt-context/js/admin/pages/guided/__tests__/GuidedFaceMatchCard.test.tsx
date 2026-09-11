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

const getRadioInputs = (group: HTMLElement): HTMLInputElement[] =>
  within(group)
    .getAllByRole('radio')
    .map((radio) => {
      if (!(radio instanceof HTMLInputElement)) {
        throw new Error('Expected a native radio input.');
      }
      return radio;
    });

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
  const cardViews = scenario.faces
    .filter((face) => face.imageKey === scenario.pressPhotos[0].key)
    .map((face) => {
      const person = scenario.people.find((candidate) => candidate.key === face.matchedPersonKey);
      const coverage = guidedNameCoverage(scenario).find((entry) => entry.key === face.matchedPersonKey);
      if (!person || !coverage) {
        throw new Error('Expected the bundled person and coverage fixture.');
      }

      return (
        <GuidedFaceMatchCard
          key={face.id}
          matches={scenario.faces
            .filter((candidate) => candidate.matchedPersonKey === face.matchedPersonKey)
            .map((match) => ({
              face: match,
              mediaUrl: scenario.pressPhotos.find((photo) => photo.key === match.imageKey)?.src ?? '',
            }))}
          person={person}
          coverage={coverage}
          choice={state.choices[face.position]}
          idScope={face.imageKey}
          disabled={state.pendingChoiceChange !== null}
          onChoose={(choice, origin) => {
            onChoose(face.position, choice, origin);
          }}
        />
      );
    });
  const view = render(
    <>
      <GuidedFacesPanel
        scenario={scenario}
        state={state}
        onChoose={onChoose}
        onContinue={onContinue}
        onConfirmReplacement={onConfirmReplacement}
        onCancelReplacement={onCancelReplacement}
      />
      <div data-testid="guided-face-card-fixture">{cardViews}</div>
    </>,
  );

  return { ...view, onChoose, onContinue, onConfirmReplacement, onCancelReplacement };
};

describe('GuidedFacesPanel and GuidedFaceMatchCard', () => {
  it('puts a native unselected radio group inside each evidence card section', () => {
    const { onChoose } = renderPanel();

    expect(screen.getByRole('heading', { name: guidedCopy('step.names') })).toBeInTheDocument();
    expect(screen.getByText(guidedCopy('names.intro'))).toBeInTheDocument();
    expect(screen.getByText(guidedCopy('names.assisted'))).toBeInTheDocument();
    expect(screen.queryByText(/How this works/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Match strength/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Yes, this is/)).not.toBeInTheDocument();

    const cards = screen.getAllByRole('region', { name: /Saved suggestion:/ });
    expect(cards).toHaveLength(2);

    const left = screen.getByRole('group', { name: guidedCopy('names.legend', { position: 'left' }) });
    const right = screen.getByRole('group', { name: guidedCopy('names.legend', { position: 'right' }) });
    expect(cards[0]).toContainElement(left);
    expect(cards[1]).toContainElement(right);
    expect(left.tagName).toBe('FIELDSET');
    expect(right.tagName).toBe('FIELDSET');
    expect(within(left).getByText(guidedCopy('names.legend', { position: 'left' }))).toBeInTheDocument();
    expect(within(right).getByText(guidedCopy('names.legend', { position: 'right' }))).toBeInTheDocument();

    const leftRadios = getRadioInputs(left);
    const rightRadios = getRadioInputs(right);
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

    const cards = screen.getAllByRole('region', { name: /Saved suggestion:/ });
    expect(cards).toHaveLength(2);
    const leftCard = screen.getByRole('region', { name: guidedCopy('names.suggestion', { name: 'Justin Trudeau' }) });
    const rightCard = screen.getByRole('region', { name: guidedCopy('names.suggestion', { name: 'Katy Perry' }) });
    expect(within(leftCard).getByText(guidedCopy('names.coverage_all', { total: 3 }))).toBeInTheDocument();
    expect(
      within(rightCard).getByText(guidedCopy('names.coverage_partial', { shown: 3, total: 5 })),
    ).toBeInTheDocument();
    expect(within(leftCard).getAllByRole('img', { name: /Justin Trudeau/ })).toHaveLength(3);
    expect(within(rightCard).getAllByRole('img', { name: /Katy Perry/ })).toHaveLength(3);
    expect(within(leftCard).getAllByText('© European Union, 2025, EU reuse licence, resized')).toHaveLength(1);
    expect(within(rightCard).getByText('Justin Higuchi, CC BY 4.0, resized')).toHaveClass('screen-reader-text');

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
      within(screen.getByRole('group', { name: guidedCopy('names.legend', { position: 'left' }) })).getByRole('radio', {
        name: guidedCopy('names.include', { name: 'Justin Trudeau' }),
      }),
    ).toBeChecked();
    expect(
      within(screen.getByRole('group', { name: guidedCopy('names.legend', { position: 'right' }) })).getByRole(
        'radio',
        {
          name: guidedCopy('names.omit'),
        },
      ),
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
        idScope="tribeca"
        disabled={false}
        onChoose={vi.fn()}
      />,
    );
    const card = screen.getByRole('region', {
      name: guidedCopy('names.suggestion', { name: person.name }),
    });
    expect(card).toHaveAttribute('aria-labelledby', `guided-face-tribeca-${person.key}-title`);
    const fieldset = screen.getByTestId('name-choice-tribeca-left');
    expect(fieldset).toBeInTheDocument();
    const radios = within(fieldset).getAllByRole('radio');
    expect(radios[0]).toHaveAttribute('id', 'guided-name-tribeca-left-include');
    expect(radios[0]).toHaveAttribute('name', 'guided-name-tribeca-left');
    expect(radios[1]).toHaveAttribute('id', 'guided-name-tribeca-left-omit');
    expect(radios[1]).toHaveAttribute('name', 'guided-name-tribeca-left');
    expect(within(card).getByRole('button', { name: guidedCopy('names.enlarge') })).toHaveAttribute(
      'id',
      'guided-name-tribeca-left-enlarge',
    );
    expect(within(card).getAllByTestId('face-thumbnail')[0]).toHaveAttribute(
      'data-alt',
      'Detected left face in Tribeca press photo',
    );
  });
});
