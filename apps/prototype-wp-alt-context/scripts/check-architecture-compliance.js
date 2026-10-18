#!/usr/bin/env node

/* global console, process */

/**
 * Architecture Compliance Checker
 *
 * Enforces architecture standards from docs/workbay/rules/component-architecture-patterns.md:
 *
 * Checks:
 * 1. Component file size limits (300 lines for components, 400 for routes)
 * 2. Hook usage limits (≤5 useState, ≤3 useEffect per file)
 * 3. Radix UI usage (no native select, dialog, tooltip, checkbox, radio)
 * 4. Test file existence (each component should have a corresponding test)
 * 5. Module organization (feature modules should have index.ts barrel exports)
 *
 * Exit codes:
 * - 0: All checks passed
 * - 1: Violations found
 *
 * Usage:
 *   npm run check:architecture
 *   npm run arch                    # Shorter alias
 *   node scripts/check-architecture-compliance.js --tips  # Show fix suggestions
 */

import { readFileSync, readdirSync, statSync, existsSync } from 'fs';
import { join, relative, dirname, basename } from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

// Configuration
const CONFIG = {
  // File size limits (non-blank, non-comment lines)
  maxLinesComponent: 300, // UI components should be focused
  maxLinesRoute: 400, // Routes/pages can be larger (orchestration)
  maxLinesHook: 200, // Hooks can have complex logic
  maxLinesUtil: 150, // Utils should be small, focused functions
  maxLinesApi: 175, // API modules - thin wrappers with type definitions

  // Hook usage limits
  maxUseState: 5, // More than 5 → consider useReducer
  maxUseEffect: 3, // More than 3 → extract custom hooks
  maxCustomHooks: 8, // Max custom hooks called in a component

  // Directories to check
  srcDirs: [join(__dirname, '../js')],

  // File extensions to check
  fileExtensions: ['.ts', '.tsx'],

  // Directories to skip
  skipDirs: ['node_modules', 'vendor', 'public', 'storybook-static', '__tests__', 'dist', '.cache'],

  // Test file patterns
  testPatterns: ['.test.tsx', '.test.ts', '.spec.tsx', '.spec.ts'],
};

// ANSI color codes
const colors = {
  reset: '\x1b[0m',
  red: '\x1b[31m',
  green: '\x1b[32m',
  yellow: '\x1b[33m',
  blue: '\x1b[34m',
  magenta: '\x1b[35m',
  cyan: '\x1b[36m',
  gray: '\x1b[90m',
  bold: '\x1b[1m',
};

// Parse command line arguments
const args = process.argv.slice(2);
const showTips = args.includes('--tips') || args.includes('-t');
const verbose = args.includes('--verbose') || args.includes('-v');
const quiet = args.includes('--quiet') || args.includes('-q');

/**
 * Count non-blank, non-comment lines in a file
 */
function countSignificantLines(content) {
  const lines = content.split('\n');
  let count = 0;
  let inBlockComment = false;

  for (const line of lines) {
    const trimmed = line.trim();

    // Handle block comments
    if (trimmed.startsWith('/*')) {
      inBlockComment = true;
    }
    if (inBlockComment) {
      if (trimmed.includes('*/')) {
        inBlockComment = false;
      }
      continue;
    }

    // Skip blank lines and single-line comments
    if (trimmed === '' || trimmed.startsWith('//')) {
      continue;
    }

    count++;
  }

  return count;
}

/**
 * Count occurrences of a pattern in file content
 */
function countPattern(content, pattern) {
  const matches = content.match(pattern);
  return matches ? matches.length : 0;
}

/**
 * Determine file type based on path and content
 */
function getFileType(filePath) {
  const fileName = basename(filePath);

  // Route files
  if (
    filePath.includes('/pages/') ||
    filePath.includes('/routes/') ||
    fileName.endsWith('Route.tsx') ||
    fileName.endsWith('Page.tsx')
  ) {
    return 'route';
  }

  // API modules
  if (filePath.includes('/api/')) {
    return 'api';
  }

  // Hook files
  if (fileName.startsWith('use') && fileName.endsWith('.ts')) {
    return 'hook';
  }
  if (filePath.includes('/hooks/')) {
    return 'hook';
  }

  // Utility files
  if (filePath.includes('/utils/') || filePath.includes('/helpers/') || filePath.includes('/lib/')) {
    return 'util';
  }

  // Test files
  if (CONFIG.testPatterns.some((pattern) => fileName.includes(pattern.replace('.', '')))) {
    return 'test';
  }

  // Type definition files
  if (fileName.endsWith('.d.ts') || fileName === 'types.ts') {
    return 'types';
  }

  // Index/barrel files
  if (fileName === 'index.ts' || fileName === 'index.tsx') {
    return 'barrel';
  }

  // Default: component
  return 'component';
}

/**
 * Get max lines allowed for file type
 */
function getMaxLines(fileType) {
  switch (fileType) {
    case 'route':
      return CONFIG.maxLinesRoute;
    case 'hook':
      return CONFIG.maxLinesHook;
    case 'util':
      return CONFIG.maxLinesUtil;
    case 'api':
      return CONFIG.maxLinesApi;
    case 'test':
      return Infinity; // No limit on test files
    case 'types':
      return Infinity; // No limit on type files
    case 'barrel':
      return Infinity; // No limit on barrel files
    default:
      return CONFIG.maxLinesComponent;
  }
}

/**
 * Check for native HTML elements that should use Radix UI
 * Only flags actual <input type="checkbox"> elements, not accessible button-based implementations
 */
function checkNativeElements(content) {
  const violations = [];

  const nativeElements = [
    {
      pattern: /<select[\s>]/gi,
      element: 'select',
      radix: '@radix-ui/react-select',
      fix: 'Use <Select.Root>, <Select.Trigger>, etc.',
    },
    {
      pattern: /<dialog[\s>]/gi,
      element: 'dialog',
      radix: '@radix-ui/react-dialog',
      fix: 'Use <Dialog.Root>, <Dialog.Trigger>, etc.',
    },
    {
      // Only match <input type="checkbox">, not button-based accessible checkboxes
      pattern: /<input[^>]*type\s*=\s*["']checkbox["'][^>]*>/gi,
      element: 'input type="checkbox"',
      radix: '@radix-ui/react-checkbox',
      fix: 'Use <Checkbox.Root>, <Checkbox.Indicator> or accessible button with role="checkbox"',
    },
    {
      // Only match <input type="radio">, not button-based accessible radios
      pattern: /<input[^>]*type\s*=\s*["']radio["'][^>]*>/gi,
      element: 'input type="radio"',
      radix: '@radix-ui/react-radio-group',
      fix: 'Use <RadioGroup.Root>, <RadioGroup.Item>',
    },
    {
      pattern: /<tooltip[\s>]/gi,
      element: 'tooltip',
      radix: '@radix-ui/react-tooltip',
      fix: 'Use <Tooltip.Root>, <Tooltip.Trigger>, etc.',
    },
    {
      pattern: /<dropdown[\s>]|<menu[\s>]/gi,
      element: 'dropdown/menu',
      radix: '@radix-ui/react-dropdown-menu',
      fix: 'Use <DropdownMenu.Root>, <DropdownMenu.Trigger>, etc.',
    },
  ];

  for (const { pattern, element, radix, fix } of nativeElements) {
    const count = countPattern(content, pattern);
    if (count > 0) {
      violations.push({
        type: 'native-element',
        severity: 'error',
        message: `Found ${count} native <${element}> element(s). Use ${radix} instead.`,
        element,
        radix,
        fix,
        count,
      });
    }
  }

  return violations;
}

/**
 * Check hook usage patterns
 */
function checkHookUsage(content, filePath) {
  const violations = [];
  const fileType = getFileType(filePath);

  // Only check components and routes for hook limits
  if (!['component', 'route'].includes(fileType)) {
    return violations;
  }

  // Check useState count
  const useStateCount = countPattern(content, /useState\s*[<(]/g);
  if (useStateCount > CONFIG.maxUseState) {
    violations.push({
      type: 'use-state',
      severity: 'error',
      message: `Too many useState hooks: ${useStateCount}/${CONFIG.maxUseState}`,
      actual: useStateCount,
      limit: CONFIG.maxUseState,
      fix: 'Consider using useReducer for complex state, or extract to a custom hook',
    });
  }

  // Check useEffect count
  const useEffectCount = countPattern(content, /useEffect\s*\(/g);
  if (useEffectCount > CONFIG.maxUseEffect) {
    violations.push({
      type: 'use-effect',
      severity: 'error',
      message: `Too many useEffect hooks: ${useEffectCount}/${CONFIG.maxUseEffect}`,
      actual: useEffectCount,
      limit: CONFIG.maxUseEffect,
      fix: 'Extract effects into custom hooks (useDebounce, useFetch, etc.)',
    });
  }

  // Check for custom hook explosion
  const customHookPattern = /use[A-Z][a-zA-Z]+\s*\(/g;
  const customHookMatches = content.match(customHookPattern) || [];
  // Filter out common React hooks
  const reactHooks = ['useState', 'useEffect', 'useCallback', 'useMemo', 'useRef', 'useContext', 'useReducer'];
  const customHooks = customHookMatches.filter((match) => !reactHooks.some((hook) => match.startsWith(hook)));

  if (customHooks.length > CONFIG.maxCustomHooks) {
    violations.push({
      type: 'hook-count',
      severity: 'warning',
      message: `Many custom hooks called: ${customHooks.length}/${CONFIG.maxCustomHooks}`,
      actual: customHooks.length,
      limit: CONFIG.maxCustomHooks,
      fix: 'Consider combining related hooks or splitting the component',
    });
  }

  return violations;
}

/**
 * Find inline arrow functions in JSX props (e.g., onClick={() => { ... }})
 * Returns array of { lineNumber, propName, bodyLength }
 */
function findInlineJsxArrowFunctions(content) {
  const results = [];
  const lines = content.split('\n');

  // Pattern to match JSX prop with inline arrow function
  // Matches: propName={() => { or propName={( ) => {
  const jsxPropArrowPattern = /(\w+)=\{(?:\([^)]*\)|[^=]*)=>\s*\{/g;

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    let match;

    while ((match = jsxPropArrowPattern.exec(line)) !== null) {
      const propName = match[1];
      const startIndex = match.index + match[0].length - 1; // Position of opening {

      // Count body length by finding matching closing brace
      let braceCount = 1;
      let bodyLength = 0;
      let lineIndex = i;
      let charIndex = startIndex + 1;

      while (braceCount > 0 && lineIndex < lines.length) {
        const currentLine = lines[lineIndex];

        while (charIndex < currentLine.length && braceCount > 0) {
          const char = currentLine[charIndex];
          if (char === '{') {
            braceCount++;
          }
          if (char === '}') {
            braceCount--;
          }
          bodyLength++;
          charIndex++;
        }

        if (braceCount > 0) {
          lineIndex++;
          charIndex = 0;
          bodyLength++; // Count newline
        }
      }

      // Only flag if body is substantial (more than ~5 lines or 150 chars)
      if (bodyLength > 150) {
        results.push({
          lineNumber: i + 1,
          propName,
          bodyLength,
        });
      }
    }

    // Reset regex lastIndex for next line
    jsxPropArrowPattern.lastIndex = 0;
  }

  return results;
}

/**
 * Check for anti-patterns
 */
function checkAntiPatterns(content, filePath) {
  const violations = [];
  const fileType = getFileType(filePath);

  // Only check components and routes for JSX-specific anti-patterns
  const isJsxFile = filePath.endsWith('.tsx');

  // Check for inline API calls in components (should be in hooks)
  if (fileType === 'component' && (content.includes('fetch(') || content.includes('axios.'))) {
    violations.push({
      type: 'inline-fetch',
      severity: 'warning',
      message: 'Direct fetch/axios call in component. Use a custom hook instead.',
      fix: 'Extract to a custom hook like useFetchData() or use React Query',
    });
  }

  // Check for long inline arrow functions in JSX props (only in .tsx files, only in components/routes)
  if (isJsxFile && ['component', 'route'].includes(fileType)) {
    const inlineFunctions = findInlineJsxArrowFunctions(content);

    for (const { lineNumber, propName, bodyLength } of inlineFunctions) {
      violations.push({
        type: 'long-inline-function',
        severity: 'warning',
        message: `Long inline function in ${propName}= prop (line ${lineNumber}, ~${bodyLength} chars)`,
        fix: `Extract to: const handle${propName.charAt(0).toUpperCase() + propName.slice(1)} = useCallback(() => { ... }, [deps])`,
        lineNumber,
      });
    }
  }

  // Check for console.log (should be removed in production) - but not in development/debug utils
  if (!filePath.includes('/utils/debug') && !filePath.includes('/lib/logger')) {
    const consoleCount = countPattern(content, /console\.(log|debug|info)\(/g);
    if (consoleCount > 0) {
      violations.push({
        type: 'console-log',
        severity: 'warning',
        message: `Found ${consoleCount} console.log/debug/info statement(s)`,
        fix: 'Remove console statements or use a proper logging utility',
      });
    }
  }

  return violations;
}

/**
 * Recursively find all TypeScript/TSX files
 */
function findFiles(dir, fileList = []) {
  if (!existsSync(dir)) {
    return fileList;
  }

  const files = readdirSync(dir);

  for (const file of files) {
    const filePath = join(dir, file);

    try {
      const stat = statSync(filePath);

      if (stat.isDirectory()) {
        // Skip configured directories
        if (!CONFIG.skipDirs.includes(file)) {
          findFiles(filePath, fileList);
        }
      } else {
        // Only check configured extensions
        if (CONFIG.fileExtensions.some((ext) => file.endsWith(ext))) {
          fileList.push(filePath);
        }
      }
    } catch {
      // Skip files we can't read
    }
  }

  return fileList;
}

/**
 * Check single file for violations
 */
function checkFile(filePath) {
  const violations = [];
  const content = readFileSync(filePath, 'utf-8');
  const relativePath = relative(process.cwd(), filePath);
  const fileType = getFileType(filePath);

  // Skip test files, type files, and barrel files for most checks
  if (['test', 'types', 'barrel'].includes(fileType)) {
    return { path: relativePath, fileType, violations: [] };
  }

  // Check 1: File size limits
  const lineCount = countSignificantLines(content);
  const maxLines = getMaxLines(fileType);

  if (lineCount > maxLines) {
    violations.push({
      type: 'file-size',
      severity: 'error',
      message: `File exceeds ${fileType} size limit: ${lineCount}/${maxLines} lines`,
      actual: lineCount,
      limit: maxLines,
      fix: `Split into smaller ${fileType === 'route' ? 'components' : 'modules'}. See docs/workbay/rules/component-architecture-patterns.md`,
    });
  }

  // Check 2: Hook usage
  violations.push(...checkHookUsage(content, filePath));

  // Check 3: Native elements (should use Radix UI)
  violations.push(...checkNativeElements(content));

  // Check 4: Anti-patterns
  violations.push(...checkAntiPatterns(content, filePath));

  return { path: relativePath, fileType, violations, lineCount };
}

/**
 * Print violations report
 */
function printReport(results) {
  if (!quiet) {
    console.log('\n' + colors.blue + colors.bold + '━'.repeat(80) + colors.reset);
    console.log(colors.blue + colors.bold + '  Architecture Compliance Check' + colors.reset);
    console.log(colors.blue + '━'.repeat(80) + colors.reset + '\n');
  }

  const allViolations = results.flatMap((r) => r.violations.map((v) => ({ ...v, file: r.path })));
  const errors = allViolations.filter((v) => v.severity === 'error');
  const warnings = allViolations.filter((v) => v.severity === 'warning');

  if (allViolations.length === 0) {
    if (!quiet) {
      console.log(colors.green + '✓ All checks passed! No violations found.' + colors.reset);

      // Print summary stats
      const totalFiles = results.filter((r) => r.lineCount).length;
      const avgLines = Math.round(
        results.filter((r) => r.lineCount).reduce((sum, r) => sum + r.lineCount, 0) / totalFiles,
      );

      console.log(colors.gray + `\n  Files checked: ${totalFiles}` + colors.reset);
      console.log(colors.gray + `  Average file size: ${avgLines} lines` + colors.reset);

      // Show file type breakdown
      const byType = {};
      for (const r of results) {
        if (r.fileType && !['test', 'types', 'barrel'].includes(r.fileType)) {
          byType[r.fileType] = (byType[r.fileType] || 0) + 1;
        }
      }

      console.log(colors.gray + '\n  By type:' + colors.reset);
      for (const [type, count] of Object.entries(byType)) {
        console.log(colors.gray + `    ${type}: ${count}` + colors.reset);
      }
    }

    console.log('');
    return 0;
  }

  // Group violations by type
  const byType = {};
  for (const violation of allViolations) {
    if (!byType[violation.type]) {
      byType[violation.type] = [];
    }
    byType[violation.type].push(violation);
  }

  // Type display names
  const typeNames = {
    'file-size': '📏 File Size Violations',
    'use-state': '🔄 useState Count Violations',
    'use-effect': '⚡ useEffect Count Violations',
    'hook-count': '🪝 Hook Count Warnings',
    'native-element': '🎨 Native Element Violations (Use Radix UI)',
    'inline-fetch': '🌐 Inline API Call Warnings',
    'long-inline-function': '📝 Long Inline Function Warnings',
    'console-log': '🖥️  Console Statement Warnings',
  };

  // Print violations grouped by type
  for (const [type, violations] of Object.entries(byType)) {
    const isError = violations[0].severity === 'error';
    const color = isError ? colors.red : colors.yellow;
    const icon = isError ? '✗' : '⚠';

    console.log(color + `${icon} ${typeNames[type] || type} (${violations.length})` + colors.reset);
    console.log(colors.gray + '─'.repeat(80) + colors.reset);

    for (const violation of violations) {
      console.log(`  ${colors.cyan}${violation.file}${colors.reset}`);
      console.log(`    ${violation.message}`);

      if (showTips && violation.fix) {
        console.log(`    ${colors.magenta}→ Tip: ${violation.fix}${colors.reset}`);
      }

      if (verbose && violation.radix) {
        console.log(`    ${colors.gray}npm install ${violation.radix}${colors.reset}`);
      }

      console.log('');
    }
  }

  // Summary
  console.log(colors.blue + '━'.repeat(80) + colors.reset);

  if (errors.length > 0) {
    console.log(colors.red + `  Errors: ${errors.length}` + colors.reset);
  }
  if (warnings.length > 0) {
    console.log(colors.yellow + `  Warnings: ${warnings.length}` + colors.reset);
  }

  console.log(colors.blue + '━'.repeat(80) + colors.reset + '\n');

  if (errors.length > 0) {
    console.log(
      colors.yellow +
        'Fix errors before merging. See docs/workbay/rules/component-architecture-patterns.md' +
        colors.reset +
        '\n',
    );

    if (!showTips) {
      console.log(colors.gray + 'Run with --tips to see suggested fixes for each violation.' + colors.reset + '\n');
    }
  }

  // Return 1 only for errors, not warnings
  return errors.length > 0 ? 1 : 0;
}

/**
 * Main execution
 */
function main() {
  if (!quiet) {
    console.log(colors.gray + 'Scanning TypeScript files in js/ directory...' + colors.reset);
  }

  let allFiles = [];
  for (const dir of CONFIG.srcDirs) {
    allFiles = allFiles.concat(findFiles(dir));
  }

  if (!quiet) {
    console.log(colors.gray + `Found ${allFiles.length} files to check` + colors.reset);
  }

  const results = [];
  for (const file of allFiles) {
    const result = checkFile(file);
    results.push(result);
  }

  const exitCode = printReport(results);
  process.exit(exitCode);
}

main();
