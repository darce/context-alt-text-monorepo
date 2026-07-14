/**
 * First-visitor walkthrough timing capture (E21-13, roadmap §Phase-3 Gate).
 *
 * Records per-step wall-clock timings for the scripted scan → review →
 * first-named-person walkthrough so `time-to-first-named-person` has a
 * measured baseline before Phase-3 construction (roadmap §8 outcome check).
 */

export interface WalkthroughStep {
  step: string;
  started_at_ms: number;
  ended_at_ms: number;
  elapsed_ms: number;
  outcome: 'ok' | 'skipped' | 'failed';
  note: string | null;
}

export interface FirstVisitorWalkthroughManifest {
  task_ref: string;
  captured_at: string;
  base_url: string;
  deploy_commit_sha: string | null;
  steps: WalkthroughStep[];
  /** Total ms from Workbench landing to first named person visible, null if never reached. */
  time_to_first_named_person_ms: number | null;
  first_named_person_reached: boolean;
  scan_triggered: boolean;
  scan_completed: boolean;
  captures: Record<string, boolean>;
  verdict: 'pass' | 'fail';
}

export class WalkthroughTimer {
  private readonly origin = Date.now();

  readonly steps: WalkthroughStep[] = [];

  /** Time a step; failures are recorded, then rethrown unless `optional`. */
  async step<T>(
    name: string,
    run: () => Promise<T>,
    options: { optional?: boolean; note?: string } = {},
  ): Promise<T | null> {
    const startedAt = Date.now() - this.origin;
    try {
      const result = await run();
      this.push(name, startedAt, 'ok', options.note ?? null);
      return result;
    } catch (error) {
      this.push(name, startedAt, options.optional ? 'skipped' : 'failed', String(error).slice(0, 300));
      if (options.optional) {
        return null;
      }
      throw error;
    }
  }

  elapsedMs(): number {
    return Date.now() - this.origin;
  }

  private push(step: string, startedAtMs: number, outcome: WalkthroughStep['outcome'], note: string | null): void {
    const endedAt = Date.now() - this.origin;
    this.steps.push({
      step,
      started_at_ms: startedAtMs,
      ended_at_ms: endedAt,
      elapsed_ms: endedAt - startedAtMs,
      outcome,
      note,
    });
  }
}

export const renderWalkthroughLogFragment = (manifest: FirstVisitorWalkthroughManifest): string => {
  const stepRows = manifest.steps
    .map(
      (step) =>
        `| ${step.step} | ${(step.elapsed_ms / 1000).toFixed(1)}s | ${step.outcome}${step.note ? ` — ${step.note}` : ''} |`,
    )
    .join('\n');

  const ttfnp =
    manifest.time_to_first_named_person_ms === null
      ? 'not reached'
      : `${(manifest.time_to_first_named_person_ms / 1000).toFixed(1)}s`;

  return `## First-visitor walkthrough (${manifest.task_ref})

- Captured: ${manifest.captured_at}
- Base URL: ${manifest.base_url}
- Deploy SHA: ${manifest.deploy_commit_sha ?? 'unknown'}
- **time-to-first-named-person: ${ttfnp}**
- Verdict: **${manifest.verdict}**

| Step | Elapsed | Outcome |
| --- | --- | --- |
${stepRows}
`;
};

export const WALKTHROUGH_FRAGMENT_FILENAME = 'first-visitor-walkthrough-fragment.md';
