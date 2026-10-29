/**
 * Shared naming-option builder for both labeling surfaces.
 *
 * Union of roster persons ∪ human-labeled clusters with namespaced values,
 * canonical person-ID dedupe and a pre-dedupe collision set
 * for the pre-save duplicate guard.
 */

import { isHumanLabeledTarget } from './suggestionProjection';
import type { CanonicalRosterPerson } from './canonicalRosterPerson';
export type { CanonicalRosterPerson } from './canonicalRosterPerson';

export type NamingOptionSource = 'person' | 'cluster';

export const PERSON_VALUE_PREFIX = 'person:' as const;
export const CLUSTER_VALUE_PREFIX = 'cluster:' as const;

/** Combobox option group labels (sr-007) — shared by dropdown + panel. */
export const NAMING_GROUP_SUGGESTED = 'Suggested' as const;
export const NAMING_GROUP_ALL_LABELS = 'All Labels' as const;

/** Default max options after filter-before-slice. */
export const NAMING_OPTIONS_LIMIT = 20;

export interface NamingOption {
  readonly value: string;
  readonly label: string;
  readonly source: NamingOptionSource;
  readonly identityCount?: number;
}

export interface RosterNamingEntry {
  readonly id: number | string;
  readonly name: string;
  readonly person_uuid?: string;
}

export interface ClusterNamingEntry {
  readonly id: string;
  readonly label: string;
  readonly identity_count?: number;
  readonly person_uuid?: string | null;
}

export const canonicalPersonOption = (person: CanonicalRosterPerson): NamingOption => ({
  value: namingOptionValue('person', person.rosterEntryId),
  label: person.name,
  source: 'person',
});

export interface BuildNamingOptionsParams {
  readonly rosterEntries: readonly RosterNamingEntry[];
  readonly labelMatches: readonly ClusterNamingEntry[];
  /** Case-insensitive substring filter applied before slice. Empty = no filter. */
  readonly filter?: string;
  /** Max options after filter. Defaults to NAMING_OPTIONS_LIMIT. Pass null for no limit. */
  readonly limit?: number | null;
  /** Cluster id excluded from cluster legs (the editable cluster). */
  readonly excludeClusterId?: string | null;
}

export interface BuildNamingOptionsResult {
  readonly options: readonly NamingOption[];
  /** Binding proof from all supplied rows, independent of text filters and display caps. */
  readonly canonicalPeopleByClusterId: ReadonlyMap<string, CanonicalRosterPerson>;
  /** Pre-dedupe universe keyed by lowercased label (for the duplicate guard). */
  readonly collisionsByLabel: ReadonlyMap<string, readonly NamingOption[]>;
}

export const namingOptionValue = (source: NamingOptionSource, id: string | number): string =>
  source === 'person' ? `${PERSON_VALUE_PREFIX}${id}` : `${CLUSTER_VALUE_PREFIX}${id}`;

export const parseNamingOptionValue = (value: string): { source: NamingOptionSource; id: string } | null => {
  if (value.startsWith(PERSON_VALUE_PREFIX)) {
    return { source: 'person', id: value.slice(PERSON_VALUE_PREFIX.length) };
  }
  if (value.startsWith(CLUSTER_VALUE_PREFIX)) {
    return { source: 'cluster', id: value.slice(CLUSTER_VALUE_PREFIX.length) };
  }
  return null;
};

/** Unwrap a namespaced cluster option value; returns null for person or unknown shapes. */
export const unwrapClusterOptionId = (value: string): string | null => {
  const parsed = parseNamingOptionValue(value);
  return parsed?.source === 'cluster' ? parsed.id : null;
};

export const isClusterNamingOption = (option: { source?: NamingOptionSource; value: string }): boolean => {
  if (option.source === 'cluster') {
    return true;
  }
  if (option.source === 'person') {
    return false;
  }
  // Namespaced values only — bare legacy ids are not cluster options (FIX-10).
  return unwrapClusterOptionId(option.value) !== null;
};

/**
 * Resolve collisions for an exact case-insensitive label, excluding the editable cluster.
 */
export const findCollisionsForLabel = (
  collisionsByLabel: ReadonlyMap<string, readonly NamingOption[]>,
  label: string,
  excludeClusterId?: string | null,
): NamingOption[] => {
  const key = label.toLowerCase().trim();
  if (!key) {
    return [];
  }
  const raw = collisionsByLabel.get(key) ?? [];
  return raw.filter((option) => {
    if (option.source !== 'cluster') {
      return true;
    }
    const clusterId = unwrapClusterOptionId(option.value);
    return clusterId !== null && clusterId !== excludeClusterId;
  });
};

/**
 * Unique cluster merge target from a collision set, if exactly one cluster is present.
 */
export const uniqueClusterCollisionTarget = (collisions: readonly NamingOption[]): NamingOption | null => {
  const clusters = collisions.filter((option) => option.source === 'cluster');
  if (clusters.length !== 1) {
    return null;
  }
  return clusters[0] ?? null;
};

const matchesFilter = (label: string, filterLower: string): boolean => {
  if (!filterLower) {
    return true;
  }
  return label.toLowerCase().includes(filterLower);
};

type FilterRank = 0 | 1 | 2;

/** Exact (0), then prefix (1), then remaining substring (2). */
const filterRank = (label: string, filterLower: string): FilterRank => {
  const lower = label.toLowerCase();
  if (lower === filterLower) {
    return 0;
  }
  if (lower.startsWith(filterLower)) {
    return 1;
  }
  return 2;
};

const rankFilteredOptions = (
  options: readonly NamingOption[],
  filterLower: string,
): NamingOption[] => {
  if (!filterLower) {
    return [...options];
  }
  const exact: NamingOption[] = [];
  const prefix: NamingOption[] = [];
  const substring: NamingOption[] = [];
  for (const option of options) {
    const rank = filterRank(option.label, filterLower);
    if (rank === 0) {
      exact.push(option);
    } else if (rank === 1) {
      prefix.push(option);
    } else {
      substring.push(option);
    }
  }
  return [...exact, ...prefix, ...substring];
};

const canonicalPeopleByClusterId = (
  roster: readonly RosterNamingEntry[],
  clusters: readonly ClusterNamingEntry[],
): ReadonlyMap<string, CanonicalRosterPerson> => {
  const byUuid = new Map<string, CanonicalRosterPerson>();
  const byCluster = new Map<string, CanonicalRosterPerson>();
  for (const entry of roster) {
    // Only local roster IDs are numeric. Backend UUIDs are joined as opaque strings.
    if (!/^[1-9]\d*$/.test(String(entry.id))) {
      continue;
    }
    const rosterEntryId = Number(entry.id);
    const name = entry.name.trim();
    if (!Number.isSafeInteger(rosterEntryId) || !name) {
      continue;
    }
    const person = { rosterEntryId, name };
    if (entry.person_uuid) {
      byUuid.set(entry.person_uuid, person);
    }
  }
  // Roster clusters are a same-name aggregate, not authoritative person bindings.
  // Only the cluster's explicit person UUID can select a local roster entry.
  for (const cluster of clusters) {
    if (cluster.person_uuid === undefined) {
      continue;
    }
    const person = cluster.person_uuid ? byUuid.get(cluster.person_uuid) : undefined;
    // An explicit unresolved/unmapped binding cannot borrow another person's label.
    if (person) {
      byCluster.set(cluster.id, person);
    } else {
      byCluster.delete(cluster.id);
    }
  }
  return byCluster;
};

/**
 * Build the union naming options for both labeling surfaces.
 *
 * - Cluster candidates apply isHumanLabeledTarget so auto `cluster-*` labels never appear (BR-17).
 * - collisionsByLabel registers every truthy cluster label (BR-42 raw equality), including machine shapes.
 * - Choices dedupe by ID; a bound cluster uses its mapped roster person.
 * - Filter-before-slice: case-insensitive substring filter, then rank exact /
 *   prefix / remaining substring (stable within each tier), then truncate.
 */
export const buildNamingOptions = ({
  rosterEntries,
  labelMatches,
  filter = '',
  limit = NAMING_OPTIONS_LIMIT,
  excludeClusterId = null,
}: BuildNamingOptionsParams): BuildNamingOptionsResult => {
  const filterLower = filter.toLowerCase().trim();
  const collisions = new Map<string, NamingOption[]>();
  const canonicalPeople = canonicalPeopleByClusterId(rosterEntries, labelMatches);

  const addCollision = (option: NamingOption): void => {
    const key = option.label.toLowerCase();
    const existing = collisions.get(key);
    if (existing) {
      existing.push(option);
    } else {
      collisions.set(key, [option]);
    }
  };

  const personCandidates: NamingOption[] = [];
  for (const person of rosterEntries) {
    const name = person.name?.trim() ?? '';
    if (!name) {
      continue;
    }
    const option: NamingOption = {
      value: namingOptionValue('person', person.id),
      label: name,
      source: 'person',
    };
    addCollision(option);
    if (matchesFilter(name, filterLower)) {
      personCandidates.push(option);
    }
  }

  const clusterCandidates: NamingOption[] = [];
  for (const cluster of labelMatches) {
    const label = cluster.label?.trim() ?? '';
    if (!label) {
      continue;
    }
    if (excludeClusterId && cluster.id === excludeClusterId) {
      continue;
    }
    const option: NamingOption = {
      value: namingOptionValue('cluster', cluster.id),
      label,
      source: 'cluster',
      identityCount: cluster.identity_count,
    };
    // BR-42: collision detection uses raw equality — every truthy label registers.
    addCollision(option);
    // BR-17: machine-shaped labels never render as naming-option candidates.
    if (!isHumanLabeledTarget(label)) {
      continue;
    }
    const person = canonicalPeople.get(cluster.id);
    const choice = person ? canonicalPersonOption(person) : option;
    if (matchesFilter(choice.label, filterLower)) {
      clusterCandidates.push(choice);
    }
  }

  // Names are nonunique. Collapse a Person/Group pair only through binding proof.
  const seen = new Set<string>();
  const deduped: NamingOption[] = [];
  for (const option of [...personCandidates, ...clusterCandidates]) {
    if (seen.has(option.value)) {
      continue;
    }
    seen.add(option.value);
    deduped.push(option);
  }

  const ranked = rankFilteredOptions(deduped, filterLower);
  const options = limit === null ? ranked : ranked.slice(0, limit);

  return {
    options,
    canonicalPeopleByClusterId: canonicalPeople,
    collisionsByLabel: collisions,
  };
};
