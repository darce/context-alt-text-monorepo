import React from 'react';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, useSearchParams } from 'react-router-dom';
import { describe, expect, it } from 'vitest';

import { ClusterPanelProvider, useClusterPanel } from '../ClusterPanelContext';

const RouteProbe = (): React.JSX.Element => {
  const [searchParams] = useSearchParams();
  return <div data-testid="route-probe">{searchParams.toString()}</div>;
};

const SameTickDriver = ({
  first,
  second,
}: {
  first: Parameters<ReturnType<typeof useClusterPanel>['dispatchClusterPanel']>[0];
  second: Parameters<ReturnType<typeof useClusterPanel>['dispatchClusterPanel']>[0];
}): React.JSX.Element => {
  const { dispatchClusterPanel, clusterPanel } = useClusterPanel();
  return (
    <>
      <div data-testid="panel-mode">{clusterPanel.mode}</div>
      <div data-testid="panel-cluster">{clusterPanel.clusterId ?? ''}</div>
      <button
        type="button"
        onClick={() => {
          dispatchClusterPanel(first);
          dispatchClusterPanel(second);
        }}
      >
        same-tick
      </button>
    </>
  );
};

const SequentialDriver = (): React.JSX.Element => {
  const { dispatchClusterPanel } = useClusterPanel();
  return (
    <>
      <button type="button" onClick={() => dispatchClusterPanel({ type: 'open_review', clusterId: 'c-1' })}>
        open
      </button>
      <button type="button" onClick={() => dispatchClusterPanel({ type: 'close' })}>
        close
      </button>
    </>
  );
};

const renderPanel = (
  initialEntry: string,
  driver: React.ReactNode,
): void => {
  render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <ClusterPanelProvider>
        {driver}
        <RouteProbe />
      </ClusterPanelProvider>
    </MemoryRouter>,
  );
};

describe('ClusterPanelContext same-tick URL writer (UXW2-4-R1-17)', () => {
  it('same-tick open then close does not leave panel=review in the URL', async () => {
    const user = userEvent.setup();
    renderPanel(
      '/workbench?tab=scan',
      <SameTickDriver
        first={{ type: 'open_review', clusterId: 'c-same' }}
        second={{ type: 'close' }}
      />,
    );

    await user.click(screen.getByRole('button', { name: 'same-tick' }));

    expect(screen.getByTestId('route-probe').textContent).not.toContain('panel=review');
    expect(screen.getByTestId('route-probe').textContent).not.toContain('cluster=c-same');
    expect(screen.getByTestId('panel-mode').textContent).toBe('none');
  });

  it('same-tick open then close restores a prior overlay', async () => {
    const user = userEvent.setup();
    renderPanel(
      '/workbench?tab=scan&panel=conflicts',
      <SameTickDriver
        first={{ type: 'open_review', clusterId: 'c-same' }}
        second={{ type: 'close' }}
      />,
    );

    await user.click(screen.getByRole('button', { name: 'same-tick' }));

    expect(screen.getByTestId('route-probe').textContent).toContain('panel=conflicts');
    expect(screen.getByTestId('route-probe').textContent).not.toContain('cluster=c-same');
    expect(screen.getByTestId('panel-mode').textContent).toBe('none');
  });

  it('same-tick close then open leaves the second action in the URL', async () => {
    const user = userEvent.setup();
    renderPanel(
      '/workbench?tab=scan&panel=review&cluster=c-old',
      <SameTickDriver
        first={{ type: 'close' }}
        second={{ type: 'open_review', clusterId: 'c-new' }}
      />,
    );

    await user.click(screen.getByRole('button', { name: 'same-tick' }));

    expect(screen.getByTestId('route-probe').textContent).toContain('panel=review');
    expect(screen.getByTestId('route-probe').textContent).toContain('cluster=c-new');
    expect(screen.getByTestId('panel-mode').textContent).toBe('review');
    expect(screen.getByTestId('panel-cluster').textContent).toBe('c-new');
  });

  it('closing review after open restores a prior overlay', async () => {
    const user = userEvent.setup();
    renderPanel('/workbench?tab=scan&panel=dead-letter', <SequentialDriver />);

    await user.click(screen.getByRole('button', { name: 'open' }));
    expect(screen.getByTestId('route-probe').textContent).toContain('panel=review');
    expect(screen.getByTestId('route-probe').textContent).toContain('cluster=c-1');

    await user.click(screen.getByRole('button', { name: 'close' }));
    expect(screen.getByTestId('route-probe').textContent).toContain('panel=dead-letter');
    expect(screen.getByTestId('route-probe').textContent).not.toContain('cluster=c-1');
  });
});
