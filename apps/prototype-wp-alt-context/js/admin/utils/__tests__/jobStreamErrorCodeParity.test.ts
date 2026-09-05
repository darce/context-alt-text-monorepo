import { spawnSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

import { JOB_STREAM_ERROR_CODE } from '../errorTaxonomy';
import { shouldSkipPhpParity } from './helpers/phpParityAvailability';

const pluginRoot = resolve(dirname(fileURLToPath(import.meta.url)), '../../../..');
const producerSource = readFileSync(resolve(pluginRoot, 'src/api/services/class-job-stream-error-code.php'), 'utf8');
const consumerCodes = Object.values(JOB_STREAM_ERROR_CODE).sort();
const skipPhpParity = shouldSkipPhpParity();

const producerCodesFrom = (source: string): string[] => {
  const result = spawnSync('php', [resolve(pluginRoot, 'tests/job-stream-error-codes.php')], {
    input: source,
    encoding: 'utf8',
    timeout: 5000,
  });
  if (result.error || result.status !== 0) {
    throw result.error ?? new Error(`PHP vocabulary reflection failed: ${result.stderr}`);
  }
  const codes: unknown = JSON.parse(result.stdout);
  if (!Array.isArray(codes) || !codes.every((code) => typeof code === 'string')) {
    throw new Error('PHP producer vocabulary must contain only string wire codes.');
  }
  return codes;
};

describe.skipIf(skipPhpParity)('job stream error code contract', () => {
  it('derives producer codes from the PHP runtime vocabulary so wire drift fails', () => {
    const producerCodes = producerCodesFrom(producerSource);

    // rg-005 (docs/workbay/constitution.md:40): compare the two real contract
    // owners; a hand-maintained expected list would only prove itself.
    expect(producerCodes.length).toBeGreaterThan(0);
    expect(producerCodes.sort()).toEqual(consumerCodes);
  });

  // TEST-15 (/home/gate/canon/engineering.md:396): mutation probes must prove
  // the parity check detects real producer drift, regardless of PHP formatting.
  it('detects an added public const REVIEW_EXTRA_2', () => {
    const mutated = producerSource.replace(/}\s*$/, "public const REVIEW_EXTRA_2 = 'review_extra_2';\n}");
    const codes = producerCodesFrom(mutated);

    expect(codes).toContain('review_extra_2');
    expect(codes.sort()).not.toEqual(consumerCodes);
  });

  it('detects a comma-separated producer constant', () => {
    const mutated = producerSource.replace("'proxy_error';", "'proxy_error', REVIEW_EXTRA_2 = 'review_extra_2';");
    const codes = producerCodesFrom(mutated);

    expect(codes.sort()).toEqual([...consumerCodes, 'review_extra_2'].sort());
    expect(codes).not.toEqual(consumerCodes);
  });

  it('ignores commented-out declarations and declaration-like strings', () => {
    const mutated = producerSource.replace(/^(\s*public const [^\n]+)$/gm, '/* $1 */').replace(
      /}\s*$/,
      `
        // public const LINE_COMMENT = 'line_comment';
        # public const HASH_COMMENT = 'hash_comment';
        public function diagnostic() {
          return "const REVIEW_EXTRA_2 = 'review_extra_2';";
        }
      }`,
    );
    const codes = producerCodesFrom(mutated);

    expect(codes).toEqual([]);
    expect(codes).not.toEqual(consumerCodes);
  });
});
