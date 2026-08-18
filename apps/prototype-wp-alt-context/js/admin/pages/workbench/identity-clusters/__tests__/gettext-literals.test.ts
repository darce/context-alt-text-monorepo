import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { describe, expect, it } from 'vitest';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

const SCOPED_FILES = [
  'reservedLabel.ts',
  'PersonCommitControl.tsx',
  'ClusterLabelingPanel.tsx',
  'useClusterSaveAction.ts',
];

const GETTEXT_RESERVED_VARIABLE =
  /(?:__|_n|_x|_nx)\(\s*(?:RESERVED_LABEL_MESSAGE|[A-Za-z_]*RESERVED[A-Za-z_]*)\s*[,)]/;

describe('gettext first arguments are literals (UXW2-3-R1-10)', () => {
  it('does not pass RESERVED_LABEL_MESSAGE into __() in naming files', () => {
    const offenders: string[] = [];
    for (const file of SCOPED_FILES) {
      const source = readFileSync(path.join(root, file), 'utf8');
      const match = GETTEXT_RESERVED_VARIABLE.exec(source);
      if (match) {
        offenders.push(`${file}: ${match[0]}`);
      }
    }
    expect(offenders).toEqual([]);
    const reserved = readFileSync(path.join(root, 'reservedLabel.ts'), 'utf8');
    expect(reserved).toMatch(/__\(\s*'This label format is reserved/);
  });
});
