import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { BulkDescribeReviewLink } from '../BulkDescribeReviewLink';

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
  sprintf: (format: string, ...args: (string | number)[]) => format.replace(/%d/g, () => String(args.shift() ?? '')),
}));

describe('BulkDescribeReviewLink', () => {
  it('D-22: links to the run-scoped apply view as a secondary CTA', () => {
    render(<BulkDescribeReviewLink runId="run-abc" isTerminal appliedCount={3} />);

    const link = screen.getByRole('link', { name: /Review & apply/ });
    expect(link).toHaveAttribute('href', '#/description-history?run=run-abc');
    expect(link).toHaveClass('button-secondary');
    expect(link).not.toHaveClass('button-primary');
  });

  it('url-encodes the run id', () => {
    render(<BulkDescribeReviewLink runId="a/b" isTerminal appliedCount={0} />);

    expect(screen.getByRole('link')).toHaveAttribute('href', '#/description-history?run=a%2Fb');
  });

  it('renders nothing until the run reaches a terminal state', () => {
    const { container } = render(<BulkDescribeReviewLink runId="run-abc" isTerminal={false} appliedCount={0} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('renders nothing without a run id', () => {
    const { container } = render(<BulkDescribeReviewLink runId={null} isTerminal appliedCount={0} />);
    expect(container).toBeEmptyDOMElement();
  });
});
