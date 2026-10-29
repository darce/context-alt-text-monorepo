// @vitest-environment jsdom
import { act, renderHook } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { CONTEXT_CATEGORIES, type SettingsResponse } from '../../../api/settingsApi';
import { useSettingsPageState } from '../useSettingsPageState';

const persisted: SettingsResponse = {
  url: 'https://api.example.com',
  url_source: 'option',
  url_rejection_reason: null,
  url_rejection_source: null,
  url_rejection_value: null,
  effective_target_url: 'https://api.example.com',
  effective_target_mode: 'service',
  recognition_source: 'service',
  recognition_source_source: 'option',
  api_key_set: true,
  api_key_last4: '****abcd',
  key_source: 'option',
  tenant_id: 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee',
  tenant_id_source: 'option',
  tenant_paired: false,
  alt_style: 'alt_only',
  recognition_enabled: true,
  allow_person_names: true,
  allow_person_names_error: null,
  context_categories: null,
  context_categories_error: null,
  description_budget: {
    max_attempts: -1,
    usage: { attempts: 0, successes: 0, failures: 0, cost_total: 0 },
    recent_errors: [],
  },
};

const withBudget = (maxAttempts: number): SettingsResponse => ({
  ...persisted,
  description_budget: { ...persisted.description_budget, max_attempts: maxAttempts },
});

const renderState = () => renderHook(
  ({ settings }: { settings: SettingsResponse }) => useSettingsPageState(settings),
  { initialProps: { settings: persisted } },
);

describe('useSettingsPageState save intent', () => {
  it('publishes untouched non-routing fields from every readback', () => {
    const { result, rerender } = renderState();
    rerender({
      settings: {
        ...withBudget(10),
        recognition_enabled: false,
        allow_person_names: false,
        context_categories: ['post'],
      },
    });
    expect(result.current.state.descriptionBudgetMaxAttempts).toBe('10');
    expect(result.current.state.recognitionEnabled).toBe(false);
    expect(result.current.state.allowPersonNames).toBe(false);
    expect(result.current.state.contextCategories).toEqual(['post']);
  });

  it('keeps an unacknowledged budget edit when a readback still carries the old value', () => {
    const { result, rerender } = renderState();
    act(() => result.current.dispatch({ type: 'setDescriptionBudgetMaxAttempts', value: '4' }));
    rerender({ settings: withBudget(-1) });
    expect(result.current.state.descriptionBudgetMaxAttempts).toBe('4');
  });

  it('keeps every unacknowledged non-routing edit while untouched routing follows the readback', () => {
    const { result, rerender } = renderState();
    const categories = CONTEXT_CATEGORIES.slice(1);
    act(() => {
      result.current.dispatch({ type: 'setRecognitionEnabled', value: false });
      result.current.dispatch({ type: 'setAllowPersonNames', value: false });
      result.current.dispatch({ type: 'setContextCategories', value: categories });
    });
    const external = 'https://external.example.com';
    rerender({ settings: { ...persisted, url: external, effective_target_url: external } });
    expect(result.current.state.url).toBe(external);
    expect(result.current.state.recognitionEnabled).toBe(false);
    expect(result.current.state.allowPersonNames).toBe(false);
    expect(result.current.state.contextCategories).toEqual(categories);
  });

  it('keeps a newer edit through an older acknowledgement, then follows readbacks once it is acknowledged', () => {
    const { result, rerender } = renderState();
    act(() => result.current.dispatch({ type: 'setDescriptionBudgetMaxAttempts', value: '4' }));
    // A write snapshots the revisions it carries.
    const carried = { ...result.current.state.nonRoutingRevisions };
    act(() => result.current.dispatch({ type: 'setDescriptionBudgetMaxAttempts', value: '7' }));
    act(() => result.current.dispatch({
      type: 'acknowledgeNonRouting',
      revisions: { descriptionBudgetMaxAttempts: carried.descriptionBudgetMaxAttempts },
    }));
    rerender({ settings: withBudget(4) });
    expect(result.current.state.descriptionBudgetMaxAttempts).toBe('7');
    const newer = { ...result.current.state.nonRoutingRevisions };
    act(() => result.current.dispatch({ type: 'acknowledgeNonRouting', revisions: newer }));
    rerender({ settings: withBudget(7) });
    rerender({ settings: withBudget(10) });
    expect(result.current.state.descriptionBudgetMaxAttempts).toBe('10');
  });
});
