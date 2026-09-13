import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { GuidedPhotoFaces } from '../GuidedPhotoFaces';

describe('GuidedPhotoFaces', () => {
  it('labels the per-image article and keeps its children in the faces list', () => {
    const title = 'People recognised in this photo';

    render(
      <GuidedPhotoFaces photoKey="tribeca" title={title}>
        <p data-testid="face-child">Justin Trudeau</p>
      </GuidedPhotoFaces>,
    );

    const article = screen.getByRole('article', { name: title });
    expect(article).toHaveAttribute('aria-labelledby', 'guided-faces-tribeca-title');
    expect(screen.getByTestId('guided-faces-tribeca')).toBe(article);

    const heading = within(article).getByRole('heading', { level: 4, name: title });
    expect(heading).toHaveAttribute('id', 'guided-faces-tribeca-title');

    const list = article.querySelector('.acx-guided-page__faces-list');
    expect(list).toBeInstanceOf(HTMLDivElement);
    expect(within(list as HTMLDivElement).getByTestId('face-child')).toHaveTextContent('Justin Trudeau');
  });
});
