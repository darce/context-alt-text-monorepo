import { fireEvent, render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { createGuidedScenario, getGuidedFace } from '../../../guidedPrototype/state';
import { GuidedSamplePhoto } from '../GuidedSamplePhoto';

describe('GuidedSamplePhoto image geometry', () => {
  it('sets the loaded image ratio on the wrap used by the percentage overlay', () => {
    const scenario = createGuidedScenario();
    const photo = scenario.pressPhoto;

    render(
      <GuidedSamplePhoto
        photo={photo}
        currentAltText={photo.altText}
        showCurrentAltText={false}
        scope="admin"
        headingId="guided-photo-tribeca-title"
      />,
    );

    const image = screen.getByRole('img', { name: photo.altText });
    const wrap = image.closest('.acx-guided-page__image-wrap');
    expect(wrap).toBeInstanceOf(HTMLElement);
    expect(wrap).toHaveAttribute('data-orientation', 'landscape');
    expect((wrap as HTMLElement).style.aspectRatio).toBe('');
    expect((wrap as HTMLElement).style.getPropertyValue('--acx-guided-photo-ratio')).toBe('');

    const frame = wrap?.querySelector('.acx-guided-page__image-frame');
    expect(frame).toBeInstanceOf(HTMLElement);
    expect(frame).toContainElement(image);

    Object.defineProperty(image, 'naturalWidth', { configurable: true, value: 1000 });
    Object.defineProperty(image, 'naturalHeight', { configurable: true, value: 800 });
    fireEvent.load(image);

    expect(wrap).toHaveAttribute('data-orientation', 'landscape');
    expect((wrap as HTMLElement).style.getPropertyValue('--acx-guided-photo-ratio')).toBe('1000 / 800');
    expect((wrap as HTMLElement).style.aspectRatio).toBe('');

    const justinFace = getGuidedFace(scenario, 'tribeca-justin-trudeau');
    const outline = screen.getByRole('button', { name: /Justin Trudeau, 89\.4%/ });
    expect(outline).toHaveStyle({
      left: `${(justinFace.box.x / 1000) * 100}%`,
      top: `${(justinFace.box.y / 800) * 100}%`,
    });
  });

  it('marks a loaded portrait image as portrait', () => {
    const scenario = createGuidedScenario();
    const photo = scenario.pressPhotos[1];

    render(<GuidedSamplePhoto photo={photo} currentAltText={photo.altText} showCurrentAltText={false} scope="admin" />);

    const image = screen.getByRole('img', { name: photo.altText });
    const wrap = image.closest('.acx-guided-page__image-wrap');
    expect(wrap).toBeInstanceOf(HTMLElement);

    Object.defineProperty(image, 'naturalWidth', { configurable: true, value: 640 });
    Object.defineProperty(image, 'naturalHeight', { configurable: true, value: 852 });
    fireEvent.load(image);

    expect(wrap).toHaveAttribute('data-orientation', 'portrait');
    expect((wrap as HTMLElement).style.getPropertyValue('--acx-guided-photo-ratio')).toBe('640 / 852');
  });
});

describe('GuidedSamplePhoto figure content', () => {
  it('renders inline credit, trimmed AltText.ai provenance, and children after the figcaption', () => {
    const scenario = createGuidedScenario();
    const photo = scenario.pressPhotos[1];
    const { container } = render(
      <GuidedSamplePhoto
        photo={photo}
        currentAltText={photo.altText}
        showCurrentAltText
        scope="public"
        headingId="guided-photo-coachella-title"
      >
        <article data-testid="faces-slot">Faces</article>
      </GuidedSamplePhoto>,
    );

    const figure = screen.getByTestId('guided-photo-coachella');
    const heading = screen.getByRole('heading', { level: 3, name: photo.event });
    expect(heading).toHaveAttribute('id', 'guided-photo-coachella-title');
    expect(figure).toHaveAttribute('aria-labelledby', 'guided-photo-coachella-title');

    const wrap = figure.querySelector('.acx-guided-page__image-wrap');
    const credit = figure.querySelector('p.acx-guided-page__credit');
    const figcaption = figure.querySelector('figcaption');
    const slot = screen.getByTestId('faces-slot');
    expect(wrap).toBeInstanceOf(HTMLElement);
    expect(credit).toBeInstanceOf(HTMLParagraphElement);
    expect(wrap?.nextElementSibling).toBe(credit);
    expect(credit?.nextElementSibling).toBe(figcaption);
    expect(credit).toHaveTextContent(`Photo credit: ${photo.credit}`);
    expect(credit?.closest('details')).toBeNull();
    expect(credit?.querySelector('a')).toHaveAttribute('href', photo.credit);

    const altTextAiCaption = within(screen.getByRole('region', { name: /AltText\.ai/ }));
    const captionProvenance = altTextAiCaption.getByText(/Captured 10 September 2026\./, {
      selector: 'p.acx-guided-page__caption-provenance',
    });
    expect(captionProvenance).toHaveTextContent('AltText.ai · Captured 10 September 2026.');
    expect(captionProvenance).not.toHaveTextContent(photo.altTextAiCaption.note);
    expect(figure.querySelector('details.acx-guided-page__provenance')).toBeNull();

    expect(figcaption).not.toContainElement(slot);
    expect(figure.lastElementChild).toBe(slot);
    expect(container.querySelectorAll('section.acx-guided-page__caption')).toHaveLength(2);
  });
});
