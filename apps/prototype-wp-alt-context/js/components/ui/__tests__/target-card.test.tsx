import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { RecognitionSource } from '../../../admin/api/settingsApi';
import { HealthStatus } from '../../../admin/pages/settings/settingsConstants';
import { TargetCard, TargetCardGroup } from '../target-card';

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
}));

describe('TargetCard', () => {
  it('exposes radio semantics inside the card group', () => {
    const onChange = vi.fn();
    render(
      <TargetCardGroup value={RecognitionSource.LOCAL} onValueChange={onChange}>
        <TargetCard
          id="acx-target-local"
          title="Local development"
          value={RecognitionSource.LOCAL}
          isEffectiveTarget
          healthStatus={HealthStatus.NOT_CHECKED}
          configured
        >
          <span>Local fields</span>
        </TargetCard>
        <TargetCard
          id="acx-target-service"
          title="Hosted service"
          value={RecognitionSource.SERVICE}
          isEffectiveTarget={false}
          healthStatus={HealthStatus.NOT_CHECKED}
          configured={false}
          emptyStateCta="Configure service URL"
        >
          <span>Service fields</span>
        </TargetCard>
      </TargetCardGroup>,
    );

    expect(screen.getByRole('radiogroup', { name: 'Recognition target' })).toBeInTheDocument();
    expect(screen.getByRole('radio', { name: /Local development/ })).toBeChecked();
    fireEvent.click(screen.getByRole('radio', { name: /Hosted service/ }));
    expect(onChange).toHaveBeenCalledWith(RecognitionSource.SERVICE);
  });

  it('marks the effective target card as active with icon and label', () => {
    render(
      <TargetCardGroup value={RecognitionSource.SERVICE} onValueChange={vi.fn()}>
        <TargetCard
          id="acx-target-local"
          title="Local development"
          value={RecognitionSource.LOCAL}
          isEffectiveTarget={false}
          healthStatus={HealthStatus.NOT_CHECKED}
          configured
        />
        <TargetCard
          id="acx-target-service"
          title="Hosted service"
          value={RecognitionSource.SERVICE}
          isEffectiveTarget
          healthStatus={HealthStatus.REACHABLE}
          configured
        />
      </TargetCardGroup>,
    );

    expect(screen.getByTestId('acx-target-card-service')).toHaveClass('acx-target-card--active');
    expect(screen.getByText('Active')).toBeInTheDocument();
    expect(screen.getByText('Reachable')).toBeInTheDocument();
  });

  it('shows unconfigured empty state CTA on the service card', () => {
    render(
      <TargetCardGroup value={RecognitionSource.SERVICE} onValueChange={vi.fn()}>
        <TargetCard
          id="acx-target-service"
          title="Hosted service"
          value={RecognitionSource.SERVICE}
          isEffectiveTarget
          healthStatus={HealthStatus.NOT_CHECKED}
          configured={false}
          emptyStateCta="Configure service URL"
          onEmptyStateCta={vi.fn()}
        />
      </TargetCardGroup>,
    );

    expect(screen.getByRole('button', { name: 'Configure service URL' })).toBeInTheDocument();
  });
});