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
});

interface PolicyFlow {
  id: string;
  steps: { screen_id: string; branch_label: string }[];
}

const POLICY_WRITES = [
  ['flow-policy-enable', 'policy_off', 'policy_on'],
  ['flow-policy-disable', 'policy_on', 'policy_off'],
] as const;

const policyFlow = (id: string): PolicyFlow => {
  const flow = (map.flows as PolicyFlow[]).find((candidate) => candidate.id === id);
  if (!flow) throw new Error(`${id} is absent`);
  return flow;
};

// FORM-08: claim the new value only after the write is acknowledged and read back.
// Presence is checked first; a missing step must never satisfy an ordering comparison.
const assertConfirmedAfterReadback = (flow: PolicyFlow, from: string, to: string): void => {
  const states = flow.steps.map((step) => step.branch_label.split(':', 1)[0]);
  const required = [from, 'policy_saving', 'policy_readback', to];
  const missing = required.filter((state) => !states.includes(state));
  if (missing.length > 0) throw new Error(`${flow.id} lacks ${missing.join(', ')}`);
  if (states.join(' -> ') !== required.join(' -> ')) {
    throw new Error(`${flow.id} runs ${states.join(' -> ')} instead of ${required.join(' -> ')}`);
  }
};

it.each(POLICY_WRITES)('%s confirms %s -> %s only after acknowledgement and readback', (id, from, to) => {
  expect(() => assertConfirmedAfterReadback(policyFlow(id), from, to)).not.toThrow();
});

it.each(POLICY_WRITES.flatMap(([id, from, to]) => ['policy_saving', 'policy_readback'].map((omitted) => [id, omitted, from, to] as const)))(
  'rejects %s without its %s step',
  (id, omitted, from, to) => {
    const flow = policyFlow(id);
    const mutant = { ...flow, steps: flow.steps.filter((step) => !step.branch_label.startsWith(`${omitted}:`)) };
    expect(mutant.steps).toHaveLength(flow.steps.length - 1);
    expect(() => assertConfirmedAfterReadback(mutant, from, to)).toThrow(`${id} lacks ${omitted}`);
  },
);

it.each(POLICY_WRITES)('rejects %s confirming %s -> %s before readback', (id, from, to) => {
  const flow = policyFlow(id);
  const readback = flow.steps.find((step) => step.branch_label.startsWith('policy_readback:'))!;
  const mutant = { ...flow, steps: [...flow.steps.filter((step) => step !== readback), readback] };
  expect(() => assertConfirmedAfterReadback(mutant, from, to)).toThrow(`${id} runs ${from} -> policy_saving -> ${to} -> policy_readback`);
});

it('renders the complete policy inventory inside Screens, including conditional recovery', () => {
  const markdown = readFileSync(path.join(dir, 'workbench-operator-loop.md'), 'utf8');
  const parsed = parseRenderedUxMap(markdown);
  expect(parsed).toEqual(projectUxMapForRenderParity(map));
  const screens = markdown.split('## Screens\n')[1].split('\n## ')[0];
  expect(screens).toContain('z-recognition-policy');
});
