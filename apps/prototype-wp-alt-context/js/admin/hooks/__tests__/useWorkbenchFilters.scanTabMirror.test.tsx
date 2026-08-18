/** Mirrors the pre-fix ScanTabContent.tsx mirror block + ReviewQueue.handleFilterClick/handleNext call pattern. */
import React from 'react';
import { act, render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import { useWorkbenchFilters, type ReviewQueueKindParam, type ReviewQueueBandParam } from '../useWorkbenchFilters';

const Mirror = () => {
  const { queueState, setQueueState } = useWorkbenchFilters();
  const loc = useLocation();
  const [queueIndex, setQueueIndex] = React.useState(queueState.index);
  const [queueKind, setQueueKind] = React.useState<ReviewQueueKindParam>(queueState.kind);
  const [queueBand, setQueueBand] = React.useState<ReviewQueueBandParam>(queueState.band);
  React.useEffect(() => {
    setQueueIndex(queueState.index); setQueueKind(queueState.kind); setQueueBand(queueState.band);
  }, [queueState.index, queueState.kind, queueState.band]);
  const handleIndexChange = React.useCallback((n: number) => { setQueueIndex(n); setQueueState({ index: n }); }, [setQueueState]);
  const handleKindChange = React.useCallback((k: ReviewQueueKindParam) => { setQueueKind(k); setQueueState({ kind: k, index: 0 }); setQueueIndex(0); }, [setQueueState]);
  const handleBandChange = React.useCallback((b: ReviewQueueBandParam) => { setQueueBand(b); setQueueState({ band: b, index: 0 }); setQueueIndex(0); }, [setQueueState]);
  const chip = () => { handleKindChange(queueKind === 'assignment' ? 'all' : 'assignment'); handleIndexChange(0); };
  const next = () => handleIndexChange(queueIndex + 1);
  const clear = () => { handleKindChange('all'); handleBandChange('all'); };
  return (
    <div>
      <button onClick={chip}>Close matches</button>
      <button onClick={next}>Next</button>
      <button onClick={clear}>Clear filters</button>
      <output data-testid="local">{`${queueKind}.${queueBand}.${queueIndex}`}</output>
      <output data-testid="url">{loc.search}</output>
    </div>
  );
};
const mount = (url: string) => render(
  <MemoryRouter initialEntries={[url]}><Routes><Route path="/" element={<Mirror />} /></Routes></MemoryRouter>);

describe('ScanTabContent mirror: local kind vs rq= URL', () => {
  it('chip from default: URL must contain rq=assignment (no split-brain)', () => {
    mount('/');
    act(() => { screen.getByText('Close matches').click(); });
    expect(screen.getByTestId('url').textContent).toContain('rq=assignment');
  });
  it('chip then Next: chip must stay active (kind stays assignment)', () => {
    mount('/');
    act(() => { screen.getByText('Close matches').click(); });
    act(() => { screen.getByText('Next').click(); });
    expect(screen.getByTestId('local').textContent).toMatch(/^assignment\./);
  });
  it('chip when rq already present (index 3): kind sticks', () => {
    mount('/?rq=all.all.3');
    act(() => { screen.getByText('Close matches').click(); });
    expect(screen.getByTestId('local').textContent).toMatch(/^assignment\./);
  });
  it('Clear filters with both active: rq removed entirely', () => {
    mount('/?rq=assignment.strong.0');
    act(() => { screen.getByText('Clear filters').click(); });
    expect(screen.getByTestId('url').textContent).toBe('');
  });
});
