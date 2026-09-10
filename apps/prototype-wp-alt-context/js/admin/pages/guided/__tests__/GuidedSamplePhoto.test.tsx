import { fireEvent, render, screen } from '@testing-library/react';
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
        provenance={scenario.provenance}
        scope="admin"
      />,
    );

    const image = screen.getByRole('img', { name: photo.altText });
    const wrap = image.closest('.acx-guided-page__image-wrap');
    expect(wrap).toBeInstanceOf(HTMLElement);
    expect((wrap as HTMLElement).style.aspectRatio).toBe('');

    Object.defineProperty(image, 'naturalWidth', { configurable: true, value: 1000 });
    Object.defineProperty(image, 'naturalHeight', { configurable: true, value: 800 });
    fireEvent.load(image);

    expect(wrap).toHaveStyle({ aspectRatio: '1000 / 800' });

    const justinFace = getGuidedFace(scenario, 'tribeca-justin-trudeau');
    const outline = screen.getByRole('button', { name: /Justin Trudeau, 89\.4%/ });
    expect(outline).toHaveStyle({
      left: `${(justinFace.box.x / 1000) * 100}%`,
      top: `${(justinFace.box.y / 800) * 100}%`,
    });
  });
});
