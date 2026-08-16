import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { InlineSuggestionPrompt } from '../InlineSuggestionPrompt';
import type { ProjectedSuggestion } from '../suggestionProjection';

const match: ProjectedSuggestion = {
  identityId: 'identity-ada',
  clusterId: 'cluster-ada',
  label: 'Ada Lovelace',
  similarity: 0.92,
  identityCount: 3,
  suggestionId: 'sug-ada-1',
};

afterEach(() => cleanup());

describe('InlineSuggestionPrompt (presentational)', () => {
  it('renders the supplied match by prop without fetching', () => {
    render(<InlineSuggestionPrompt match={match} onConfirm={vi.fn()} onReject={vi.fn()} isPending={false} />);

    expect(screen.getByText('Ada Lovelace')).toBeInTheDocument();
    expect(screen.getByText('92%')).toBeInTheDocument();
  });

  it('renders nothing when no match is supplied', () => {
    const { container } = render(
      <InlineSuggestionPrompt match={undefined} onConfirm={vi.fn()} onReject={vi.fn()} isPending={false} />,
    );

    expect(container).toBeEmptyDOMElement();
  });

  it('renders nothing when the match carries no label', () => {
    const labelless = { ...match, label: '' };
    const { container } = render(
      <InlineSuggestionPrompt match={labelless} onConfirm={vi.fn()} onReject={vi.fn()} isPending={false} />,
    );

    expect(container).toBeEmptyDOMElement();
  });

  it('renders nothing when the match label is whitespace-only (BR-14)', () => {
    const blank = { ...match, label: '   ' };
    const { container } = render(
      <InlineSuggestionPrompt match={blank} onConfirm={vi.fn()} onReject={vi.fn()} isPending={false} />,
    );

    expect(container).toBeEmptyDOMElement();
  });

  it('fires onConfirm with the match clusterId, label, and suggestionId on Yes (BR-16)', async () => {
    // Predicted first failure: third arg undefined when match.suggestionId is dropped
    const onConfirm = vi.fn();
    const user = userEvent.setup();
    render(<InlineSuggestionPrompt match={match} onConfirm={onConfirm} onReject={vi.fn()} isPending={false} />);

    await user.click(screen.getByRole('button', { name: 'Yes' }));
    expect(onConfirm).toHaveBeenCalledWith('cluster-ada', 'Ada Lovelace', 'sug-ada-1');
  });

  it('fires onReject on No', async () => {
    const onReject = vi.fn();
    const user = userEvent.setup();
    render(<InlineSuggestionPrompt match={match} onConfirm={vi.fn()} onReject={onReject} isPending={false} />);

    await user.click(screen.getByRole('button', { name: 'No' }));
    expect(onReject).toHaveBeenCalledTimes(1);
  });

  it('disables both actions while a mutation is pending', () => {
    render(<InlineSuggestionPrompt match={match} onConfirm={vi.fn()} onReject={vi.fn()} isPending />);

    expect(screen.getByRole('button', { name: 'Yes' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'No' })).toBeDisabled();
  });
});
