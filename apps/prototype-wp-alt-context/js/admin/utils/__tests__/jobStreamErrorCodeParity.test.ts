import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

import { JOB_STREAM_ERROR_CODE } from '../errorTaxonomy';

describe('job stream error code contract', () => {
  it('derives producer codes from the PHP enum so wire drift fails', () => {
    const producerSource = readFileSync(
      resolve(
        dirname(fileURLToPath(import.meta.url)),
        '../../../../src/api/services/class-job-stream-error-code.php',
      ),
      'utf8',
    );
    const producerCodes = Array.from(
      producerSource.matchAll(/case\s+[A-Z_]+\s*=\s*['"]([^'"]+)['"]/g),
      (match) => match[1],
    );

    // rg-005 (docs/workbay/constitution.md:33): compare the two real contract
    // owners; a hand-maintained expected list would only prove itself.
    expect(producerCodes.length).toBeGreaterThan(0);
    expect([...Object.values(JOB_STREAM_ERROR_CODE)].sort()).toEqual(producerCodes.sort());
  });
});
