import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

import { describe, expect, it } from 'vitest';

import { GUIDED_COPY } from './copy';

const CATALOG_PATH = resolve(
  __dirname,
  '../../../../../docs/assessments/current/demo/altcontext_guided_demo_qm_v1/copy.en.json',
);

const loadCatalog = (): Record<string, string> =>
  JSON.parse(readFileSync(CATALOG_PATH, 'utf8')) as Record<string, string>;

describe('guided copy generated artifact', () => {
  it('keeps generated copy keys and values in parity with the canonical catalog', () => {
    const catalog = loadCatalog();

    expect(Object.keys(GUIDED_COPY).sort()).toEqual(Object.keys(catalog).sort());
    expect(GUIDED_COPY).toEqual(catalog);
  });
});
