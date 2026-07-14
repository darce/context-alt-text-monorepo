import { describe, expect, expectTypeOf, it } from 'vitest';

import type { PipelinePhase } from '../../../hooks/jobStateMachineUtils';
import {
  JOB_PHASE_PRESENTATION,
  PIPELINE_PHASE_PRESENTATION,
  type JobPhase,
  type PresentationEntry,
} from '../phasePresentation';
import { SYNC_VOCABULARY } from '../syncPresentation';

const ALL_JOB_PHASES = [
  'queued',
  'detecting',
  'clustering',
  'retrying',
  'awaiting_projection',
  'failed',
  'complete',
] as const satisfies readonly JobPhase[];

const ALL_PIPELINE_PHASES = ['idle', 'scanning', 'clustering', 'projecting'] as const satisfies readonly PipelinePhase[];

// sr-005: assertion helper for the unreachable missing-entry branch.
const assertPresentationEntry: (
  entry: PresentationEntry | undefined,
  phase: string,
) => asserts entry is PresentationEntry = (entry, phase) => {
  if (entry === undefined) {
    throw new Error(`Missing presentation entry for phase: ${phase}`);
  }
};

describe('phasePresentation exhaustiveness', () => {
  it('JOB_PHASE_PRESENTATION covers exactly the generated JobProgress phase union', () => {
    // Compile-time: the local list covers the union (complements the module's
    // `satisfies Record<Union, PresentationEntry>` exhaustiveness check).
    expectTypeOf<Exclude<JobPhase, (typeof ALL_JOB_PHASES)[number]>>().toEqualTypeOf<never>();
    expect(Object.keys(JOB_PHASE_PRESENTATION).sort()).toEqual([...ALL_JOB_PHASES].sort());
    for (const phase of ALL_JOB_PHASES) {
      const entry: PresentationEntry | undefined = JOB_PHASE_PRESENTATION[phase];
      assertPresentationEntry(entry, phase);
      expect(entry.label.length).toBeGreaterThan(0);
    }
  });

  it('PIPELINE_PHASE_PRESENTATION covers exactly the client PipelinePhase union', () => {
    expectTypeOf<Exclude<PipelinePhase, (typeof ALL_PIPELINE_PHASES)[number]>>().toEqualTypeOf<never>();
    expect(Object.keys(PIPELINE_PHASE_PRESENTATION).sort()).toEqual([...ALL_PIPELINE_PHASES].sort());
    for (const phase of ALL_PIPELINE_PHASES) {
      const entry: PresentationEntry | undefined = PIPELINE_PHASE_PRESENTATION[phase];
      assertPresentationEntry(entry, phase);
    }
  });
});

describe('shared clustering vocabulary', () => {
  it('both records source the clustering label from SYNC_VOCABULARY', () => {
    expect(JOB_PHASE_PRESENTATION.clustering.label).toBe(SYNC_VOCABULARY.phaseClustering);
    expect(PIPELINE_PHASE_PRESENTATION.clustering.label).toBe(SYNC_VOCABULARY.clusteringHeadline);
    expect(PIPELINE_PHASE_PRESENTATION.clustering.milestone.active).toBe(SYNC_VOCABULARY.clusteringHeadline);
  });
});

describe('phase status builders', () => {
  it('builds the queued count line from params', () => {
    expect(JOB_PHASE_PRESENTATION.queued.status({ completed: 0, total: 7 })).toBe('Queued 7 items…');
  });

  it('builds both detecting variants from params', () => {
    expect(JOB_PHASE_PRESENTATION.detecting.status({ completed: 3, total: 10 })).toBe(
      'Detecting faces… 3/10 processed',
    );
    expect(JOB_PHASE_PRESENTATION.detecting.status({ completed: 3, total: 10, facesFound: 4 })).toBe(
      'Detecting faces… 3/10 processed · 4 faces found',
    );
  });

  it('builds clustering status with counts and a countless fallback', () => {
    expect(JOB_PHASE_PRESENTATION.clustering.status({ completed: 2, total: 9 })).toBe('Clustering 2/9 identities…');
    expect(JOB_PHASE_PRESENTATION.clustering.statusFallback).toBe('Clustering faces…');
  });

  it('owns the awaiting_projection copy', () => {
    expect(JOB_PHASE_PRESENTATION.awaiting_projection.statusFallback).toBe('Syncing projected results…');
  });
});
