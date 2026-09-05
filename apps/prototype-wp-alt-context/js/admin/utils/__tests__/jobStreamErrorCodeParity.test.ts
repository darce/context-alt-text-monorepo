import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

import { JOB_STREAM_ERROR_CODE } from '../errorTaxonomy';

const producerCodesFrom = (source: string): string[] =>
  Array.from(
    source.matchAll(/\b(?:case|const)\s+[a-zA-Z_\x80-\xff][a-zA-Z0-9_\x80-\xff]*\s*=\s*['"]([^'"]+)['"]/g),
    (match) => match[1],
  );

describe('job stream error code contract', () => {
  it('derives producer codes from the PHP vocabulary so wire drift fails', () => {
    const producerSource = readFileSync(
      resolve(dirname(fileURLToPath(import.meta.url)), '../../../../src/api/services/class-job-stream-error-code.php'),
      'utf8',
    );
    const producerCodes = producerCodesFrom(producerSource);

    // rg-005 (docs/workbay/constitution.md:40): compare the two real contract
    // owners; a hand-maintained expected list would only prove itself.
    expect(producerCodes.length).toBeGreaterThan(0);
    expect([...Object.values(JOB_STREAM_ERROR_CODE)].sort()).toEqual(producerCodes.sort());
  });

  // TEST-15 (/home/gate/canon/engineering.md:396): prove a new producer
  // member changes the comparison, including identifiers containing digits.
  it.each(['case', 'public const'])('detects an added %s REVIEW_EXTRA_2', (declaration) => {
    const source = readFileSync(
      resolve(dirname(fileURLToPath(import.meta.url)), '../../../../src/api/services/class-job-stream-error-code.php'),
      'utf8',
    );
    const mutated = source.replace(/}\s*$/, `${declaration} REVIEW_EXTRA_2 = 'review_extra_2';\n}`);
    const codes = producerCodesFrom(mutated);

    expect(codes).toContain('review_extra_2');
    expect(codes.sort()).not.toEqual([...Object.values(JOB_STREAM_ERROR_CODE)].sort());
  });
});
