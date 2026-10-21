import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { expect, it } from 'vitest';

import { parseRenderedUxMap, projectUxMapForRenderParity } from '../uxmap/renderParity';

const dir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../../docs/ux-maps');
const map = JSON.parse(readFileSync(path.join(dir, 'workbench-operator-loop.uxmap.json'), 'utf8'));

it('keeps policy mutation and read-only recovery beside scan without adding a primary or screen', () => {
  const scan = map.screens.find((screen: { id: string }) => screen.id === 'workbench-scan');
  expect(scan.zones.map((zone: { id: string }) => zone.id)).toContain('z-recognition-policy');
  expect(scan.primary_action_id).toBe('act-scan-selected');
  for (const [id, when] of [
    ['act-enable-recognition', ['policy_off']],
    ['act-disable-recognition', ['policy_on']],
    ['act-retry-policy-read', ['policy_unknown', 'policy_readback_error', 'policy_rejected']],
  ] as const) {
    expect(map.actions.find((action: { id: string }) => action.id === id)).toMatchObject({
      hierarchy: 'secondary', screen_id: 'workbench-scan', when: [...when],
      costly: false, irreversible: false,
    });
  }
  for (const state of ['policy_on', 'policy_off', 'policy_unknown', 'policy_saving', 'policy_readback', 'policy_readback_error', 'policy_permission_denied', 'policy_read_only', 'policy_rejected']) {
    expect(map.domain_state_mappings.some((mapping: { domain_states: string[] }) => mapping.domain_states.includes(state))).toBe(true);
  }
  const policy = map.actions.filter((action: { id: string }) => /recognition|policy-read/.test(action.id));
  expect(policy.every((action: { when: string[] }) => !action.when.some(state => /saving|readback$|permission_denied|read_only/.test(state)))).toBe(true);
  expect(map.screens.some((screen: { id: string }) => /confirm/.test(screen.id))).toBe(false);
  const recovery = map.flows.find((flow: { id: string }) => flow.id === 'flow-policy-recover');
  expect(recovery.steps.every((step: { screen_id: string }) => step.screen_id === 'workbench-scan')).toBe(true);
  expect(recovery.steps.map((step: { branch_label: string }) => step.branch_label).join(' ')).toContain('never replay acknowledged POST');
  const enable = map.flows.find((flow: { id: string }) => flow.id === 'flow-policy-enable');
  const labels = enable.steps.map((step: { branch_label: string }) => step.branch_label);
  expect(labels.findIndex((label: string) => label.startsWith('policy_readback:'))).toBeLessThan(
    labels.findIndex((label: string) => label.startsWith('policy_on:')),
  );
});

it('renders the complete policy inventory inside Screens, including conditional recovery', () => {
  const markdown = readFileSync(path.join(dir, 'workbench-operator-loop.md'), 'utf8');
  const parsed = parseRenderedUxMap(markdown);
  expect(parsed).toEqual(projectUxMapForRenderParity(map));
  const screens = markdown.split('## Screens\n')[1].split('\n## ')[0];
  expect(screens).toContain('z-recognition-policy');
});
