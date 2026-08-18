import { describe, expect, it } from 'vitest';

import {
  NAMING_OPTIONS_LIMIT,
  buildNamingOptions,
  findCollisionsForLabel,
  namingOptionValue,
  parseNamingOptionValue,
  uniqueClusterCollisionTarget,
  unwrapClusterOptionId,
} from '../buildNamingOptions';

describe('buildNamingOptions', () => {
  const roster = [
    { id: 1, name: 'Alice' },
    { id: 2, name: 'Bob' },
  ];
  const clusters = [
    { id: 'c-alice', label: 'alice', identity_count: 4 },
    { id: 'c-carol', label: 'Carol', identity_count: 2 },
    { id: 'c-auto', label: 'cluster-1234', identity_count: 1 },
  ];

  it('unions roster persons and labeled clusters with namespaced values', () => {
    // Predicted first failure: buildNamingOptions is not a function / module missing
    const { options } = buildNamingOptions({
      rosterEntries: roster,
      labelMatches: clusters,
      limit: null,
    });

    expect(options.map((option) => option.value)).toEqual([
      namingOptionValue('person', 1),
      namingOptionValue('person', 2),
      namingOptionValue('cluster', 'c-carol'),
    ]);
    expect(options.map((option) => option.source)).toEqual(['person', 'person', 'cluster']);
    expect(options.every((option) => parseNamingOptionValue(option.value) !== null)).toBe(true);
  });

  it('lists persons before clusters', () => {
    const { options } = buildNamingOptions({
      rosterEntries: [{ id: 9, name: 'Zed' }],
      labelMatches: [{ id: 'c-ann', label: 'Ann', identity_count: 1 }],
      limit: null,
    });

    expect(options.map((option) => option.label)).toEqual(['Zed', 'Ann']);
    expect(options[0]?.source).toBe('person');
    expect(options[1]?.source).toBe('cluster');
  });

  it('dedupes case-insensitively preferring the person entry (canonical casing)', () => {
    const { options } = buildNamingOptions({
      rosterEntries: [{ id: 1, name: 'Bob' }],
      labelMatches: [{ id: 'c-bob', label: 'bob', identity_count: 7 }],
      limit: null,
    });

    expect(options).toHaveLength(1);
    expect(options[0]).toMatchObject({
      label: 'Bob',
      source: 'person',
      value: namingOptionValue('person', 1),
    });
  });

  it('filter-before-slice keeps a prefix match beyond the default limit', () => {
    const manyPersons = Array.from({ length: NAMING_OPTIONS_LIMIT + 5 }, (_, index) => ({
      id: index + 1,
      name: `Person ${String(index + 1).padStart(2, '0')}`,
    }));
    // "Zebra" would be truncated without filter; with filter it is first.
    const withZebra = [...manyPersons, { id: 999, name: 'Zebra' }];

    const unfiltered = buildNamingOptions({
      rosterEntries: withZebra,
      labelMatches: [],
      limit: NAMING_OPTIONS_LIMIT,
    });
    expect(unfiltered.options.some((option) => option.label === 'Zebra')).toBe(false);

    const filtered = buildNamingOptions({
      rosterEntries: withZebra,
      labelMatches: [],
      filter: 'Zeb',
      limit: NAMING_OPTIONS_LIMIT,
    });
    expect(filtered.options.map((option) => option.label)).toEqual(['Zebra']);
  });

  it('exposes pre-dedupe collision set so person+cluster same name both appear', () => {
    // Predicted first failure (BR-18): collisions only keep the person after dedupe
    const { collisionsByLabel, options } = buildNamingOptions({
      rosterEntries: [{ id: 1, name: 'Bob' }],
      labelMatches: [{ id: 'c-bob', label: 'bob', identity_count: 7 }],
      limit: null,
    });

    expect(options).toHaveLength(1);
    const collisions = findCollisionsForLabel(collisionsByLabel, 'BOB');
    expect(collisions).toHaveLength(2);
    expect(collisions.map((option) => option.source).sort()).toEqual(['cluster', 'person']);
    expect(uniqueClusterCollisionTarget(collisions)?.value).toBe(namingOptionValue('cluster', 'c-bob'));
  });

  it('excludes auto cluster-* labels from options but registers collisions (BR-17 / BR-42)', () => {
    // BR-17: machine labels never render as naming options.
    // BR-42: collision detection uses raw equality — they still register in collisionsByLabel.
    const { options, collisionsByLabel } = buildNamingOptions({
      rosterEntries: [],
      labelMatches: [
        { id: 'auto-1', label: 'cluster-1234', identity_count: 1 },
        { id: 'human-1', label: 'Dana', identity_count: 3 },
      ],
      limit: null,
    });

    expect(options.map((option) => option.label)).toEqual(['Dana']);
    expect(options.every((option) => !option.label.startsWith('cluster-'))).toBe(true);
    expect(findCollisionsForLabel(collisionsByLabel, 'cluster-1234')).toHaveLength(1);
    expect(findCollisionsForLabel(collisionsByLabel, 'Dana')).toHaveLength(1);
  });

  it('registers collision for machine-shaped cluster-auto-1 without offering it as a candidate (BR-42)', () => {
    // Predicted first failure: BR-17 human-gate continues before addCollision → collision set blind
    const { options, collisionsByLabel } = buildNamingOptions({
      rosterEntries: [],
      labelMatches: [{ id: 'auto-machine', label: 'cluster-auto-1', identity_count: 2 }],
      limit: null,
    });

    expect(options.map((option) => option.label)).toEqual([]);
    expect(options.some((option) => option.label === 'cluster-auto-1')).toBe(false);
    const collisions = findCollisionsForLabel(collisionsByLabel, 'cluster-auto-1');
    expect(collisions).toHaveLength(1);
    expect(collisions[0]).toMatchObject({
      label: 'cluster-auto-1',
      source: 'cluster',
      value: namingOptionValue('cluster', 'auto-machine'),
    });
  });

  // BR-48 dual-lock: collision registration vs candidate exclusion must be independently pinned.
  it('registers a collision for a machine-labeled cluster row (BR-48 collision lock)', () => {
    const { collisionsByLabel } = buildNamingOptions({
      rosterEntries: [],
      labelMatches: [{ id: 'br48-auto', label: 'cluster-1234', identity_count: 1 }],
      limit: null,
    });

    const collisions = findCollisionsForLabel(collisionsByLabel, 'cluster-1234');
    expect(collisions).toHaveLength(1);
    expect(collisions[0]).toMatchObject({
      label: 'cluster-1234',
      source: 'cluster',
      value: namingOptionValue('cluster', 'br48-auto'),
    });
  });

  it('excludes a machine-labeled cluster row from clusterCandidates (BR-48 candidate lock)', () => {
    // Human control row defeats vacuous-green (matchesPrefix starvation / fixture typo).
    const { options } = buildNamingOptions({
      rosterEntries: [],
      labelMatches: [
        { id: 'br48-auto', label: 'cluster-1234', identity_count: 1 },
        { id: 'br48-human', label: 'Pat Rivera', identity_count: 4 },
      ],
      limit: null,
    });

    expect(options.some((option) => option.label === 'Pat Rivera')).toBe(true);
    expect(options.some((option) => option.value === namingOptionValue('cluster', 'br48-human'))).toBe(true);
    expect(options.some((option) => option.label === 'cluster-1234')).toBe(false);
    expect(options.some((option) => option.value === namingOptionValue('cluster', 'br48-auto'))).toBe(false);
    expect(options).toHaveLength(1);
  });

  it('excludes the editable cluster from options and collision cluster leg', () => {
    const { options, collisionsByLabel } = buildNamingOptions({
      rosterEntries: [],
      labelMatches: [
        { id: 'self', label: 'thistle', identity_count: 2 },
        { id: 'other', label: 'thistle Archive', identity_count: 1 },
      ],
      excludeClusterId: 'self',
      limit: null,
    });

    expect(options.map((option) => option.label)).toEqual(['thistle Archive']);
    expect(findCollisionsForLabel(collisionsByLabel, 'thistle', 'self')).toHaveLength(0);
  });

  it('uniqueClusterCollisionTarget is null when no unique cluster target exists', () => {
    expect(uniqueClusterCollisionTarget([{ value: 'person:1', label: 'Bob', source: 'person' }])).toBeNull();
    expect(
      uniqueClusterCollisionTarget([
        { value: 'cluster:a', label: 'Bob', source: 'cluster' },
        { value: 'cluster:b', label: 'Bob', source: 'cluster' },
      ]),
    ).toBeNull();
  });
});

describe('naming option value helpers', () => {
  it('parses and unwraps namespaced values', () => {
    expect(parseNamingOptionValue('person:42')).toEqual({ source: 'person', id: '42' });
    expect(parseNamingOptionValue('cluster:abc')).toEqual({ source: 'cluster', id: 'abc' });
    expect(unwrapClusterOptionId('cluster:abc')).toBe('abc');
    expect(unwrapClusterOptionId('person:42')).toBeNull();
    expect(parseNamingOptionValue('bare-id')).toBeNull();
  });
});
