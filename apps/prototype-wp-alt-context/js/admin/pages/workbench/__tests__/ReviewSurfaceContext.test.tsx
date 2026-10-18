import React from 'react';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';

import { ReviewSurfaceProvider, useReviewSurface } from '../ReviewSurfaceContext';

const Producer = (): React.JSX.Element => {
  const { setCardPrimaryPresent } = useReviewSurface();
  return (
    <button type="button" onClick={() => setCardPrimaryPresent(true)}>
      present
    </button>
  );
};

const Consumer = (): React.JSX.Element => {
  const { cardPrimaryPresent } = useReviewSurface();
  return <span>{cardPrimaryPresent ? 'active' : 'idle'}</span>;
};

const Orphan = (): React.JSX.Element => {
  useReviewSurface();
  return <span>orphan</span>;
};

describe('ReviewSurfaceContext', () => {
  it('shares cardPrimaryPresent across sibling subtrees under one provider', async () => {
    // [TEST-15] discrimination: if the provider held two independent useState instances
    // (not truly shared), the consumer would stay "idle" after the producer click.
    const user = userEvent.setup();
    render(
      <ReviewSurfaceProvider>
        <Producer />
        <Consumer />
      </ReviewSurfaceProvider>,
    );

    expect(screen.getByText('idle')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'present' }));
    expect(screen.getByText('active')).toBeInTheDocument();
  });

  it('throws when useReviewSurface is used outside ReviewSurfaceProvider', () => {
    expect(() => render(<Orphan />)).toThrow(/ReviewSurfaceProvider/);
  });
});
