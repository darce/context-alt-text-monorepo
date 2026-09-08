/**
 * UXW2-2-R5-11: gettext extractors only see string-literal msgids.
 *
 * Scope is intentionally ScanTabContent.tsx + ReviewQueue.tsx — not repo-wide.
 * A repo-wide scan would fail on out-of-scope files and block sibling lanes.
 */
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import ts from 'typescript';
import { describe, expect, it } from 'vitest';

const here = path.dirname(fileURLToPath(import.meta.url));

/** Owned FE surfaces for this lane plus ReviewQueue.tsx (the other constant-msgid cluster). */
const SCOPED_FILES = [
  path.resolve(here, '../ScanTabContent.tsx'),
  path.resolve(here, '../identity-clusters/ReviewQueue.tsx'),
] as const;

const GETTEXT_CALLEES = new Set(['__', '_n', '_x']);

interface Offender {
  file: string;
  line: number;
  column: number;
  callee: string;
  preview: string;
}

const collectOffenders = (filePath: string): { callCount: number; offenders: Offender[] } => {
  const source = readFileSync(filePath, 'utf8');
  const sf = ts.createSourceFile(filePath, source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  const offenders: Offender[] = [];
  let callCount = 0;

  const visit = (node: ts.Node): void => {
    if (
      ts.isCallExpression(node) &&
      ts.isIdentifier(node.expression) &&
      GETTEXT_CALLEES.has(node.expression.text)
    ) {
      callCount += 1;
      const arg = node.arguments[0];
      const isLiteral =
        arg !== undefined && (ts.isStringLiteral(arg) || ts.isNoSubstitutionTemplateLiteral(arg));
      if (!isLiteral) {
        const pos = sf.getLineAndCharacterOfPosition(node.expression.getStart(sf));
        offenders.push({
          file: path.basename(filePath),
          line: pos.line + 1,
          column: pos.character + 1,
          callee: node.expression.text,
          preview: (arg?.getText(sf) ?? '(missing)').replace(/\s+/g, ' ').slice(0, 80),
        });
      }
    }
    ts.forEachChild(node, visit);
  };

  visit(sf);
  return { callCount, offenders };
};

describe('gettext first-arg literals (ScanTabContent.tsx + ReviewQueue.tsx only)', () => {
  it('every __ / _n / _x first argument in ScanTabContent.tsx and ReviewQueue.tsx is a string literal', () => {
    let totalCalls = 0;
    const offenders: Offender[] = [];
    for (const filePath of SCOPED_FILES) {
      const result = collectOffenders(filePath);
      totalCalls += result.callCount;
      offenders.push(...result.offenders);
    }
    expect(totalCalls).toBeGreaterThan(0);
    if (offenders.length > 0) {
      const detail = offenders
        .map(
          (offender) =>
            `${offender.file}:${offender.line}:${offender.column} ${offender.callee}(${offender.preview}) first argument is not a string literal`,
        )
        .join('\n');
      expect.fail(detail);
    }
  });
});
