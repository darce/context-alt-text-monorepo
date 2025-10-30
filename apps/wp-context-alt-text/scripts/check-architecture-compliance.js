#!/usr/bin/env node

/**
 * Architecture Compliance Checker
 *
 * Enforces architecture standards defined in docs/architecture/rules/:
 * - Component file size limits (300 lines for components, 400 for routes)
 * - Hook usage limits (≤5 useState, ≤3 useEffect per file)
 * - Radix UI usage (no native select, dialog, tooltip, checkbox, radio)
 *
 * Exit codes:
 * - 0: All checks passed
 * - 1: Violations found
 */

import { readFileSync, readdirSync, statSync } from "fs";
import { join, relative } from "path";
import { fileURLToPath } from "url";
import { dirname } from "path";

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

// Configuration
const CONFIG = {
    maxLinesComponent: 300,
    maxLinesRoute: 400,
    maxUseState: 5,
    maxUseEffect: 3,
    componentsDir: join(__dirname, "../js"),
    fileExtensions: [".ts", ".tsx"],
};

// ANSI color codes
const colors = {
    reset: "\x1b[0m",
    red: "\x1b[31m",
    green: "\x1b[32m",
    yellow: "\x1b[33m",
    blue: "\x1b[34m",
    gray: "\x1b[90m",
};

/**
 * Count non-blank, non-comment lines in a file
 */
function countSignificantLines(content) {
    const lines = content.split("\n");
    let count = 0;
    let inBlockComment = false;

    for (const line of lines) {
        const trimmed = line.trim();

        // Handle block comments
        if (trimmed.startsWith("/*")) {
            inBlockComment = true;
        }
        if (inBlockComment) {
            if (trimmed.endsWith("*/")) {
                inBlockComment = false;
            }
            continue;
        }

        // Skip blank lines and single-line comments
        if (trimmed === "" || trimmed.startsWith("//")) {
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
 * Check if file is a route component
 */
function isRoute(filePath) {
    return filePath.includes("/routes/") || filePath.endsWith("Route.tsx");
}

/**
 * Recursively find all TypeScript/TSX files
 */
function findFiles(dir, fileList = []) {
    const files = readdirSync(dir);

    for (const file of files) {
        const filePath = join(dir, file);
        const stat = statSync(filePath);

        if (stat.isDirectory()) {
            // Skip node_modules, vendor, public
            if (!["node_modules", "vendor", "public", "storybook-static"].includes(file)) {
                findFiles(filePath, fileList);
            }
        } else {
            // Only check configured extensions
            if (CONFIG.fileExtensions.some((ext) => file.endsWith(ext))) {
                fileList.push(filePath);
            }
        }
    }

    return fileList;
}

/**
 * Check single file for violations
 */
function checkFile(filePath) {
    const violations = [];
    const content = readFileSync(filePath, "utf-8");
    const relativePath = relative(process.cwd(), filePath);

    // Check 1: File size limits
    const lineCount = countSignificantLines(content);
    const maxLines = isRoute(filePath) ? CONFIG.maxLinesRoute : CONFIG.maxLinesComponent;

    if (lineCount > maxLines) {
        const limitType = isRoute(filePath) ? "route" : "component";
        violations.push({
            type: "file-size",
            severity: "error",
            message: `File exceeds ${limitType} size limit: ${lineCount}/${maxLines} lines`,
            file: relativePath,
            limit: maxLines,
            actual: lineCount,
        });
    }

    // Check 2: useState count
    const useStateCount = countPattern(content, /useState\s*</g);
    if (useStateCount > CONFIG.maxUseState) {
        violations.push({
            type: "use-state",
            severity: "error",
            message: `Too many useState hooks: ${useStateCount}/${CONFIG.maxUseState}. Consider useReducer.`,
            file: relativePath,
            limit: CONFIG.maxUseState,
            actual: useStateCount,
        });
    }

    // Check 3: useEffect count
    const useEffectCount = countPattern(content, /useEffect\s*\(/g);
    if (useEffectCount > CONFIG.maxUseEffect) {
        violations.push({
            type: "use-effect",
            severity: "error",
            message: `Too many useEffect hooks: ${useEffectCount}/${CONFIG.maxUseEffect}. Extract custom hooks.`,
            file: relativePath,
            limit: CONFIG.maxUseEffect,
            actual: useEffectCount,
        });
    }

    // Check 4: Native HTML elements (should use Radix UI)
    const nativeElements = [
        { pattern: /<select[\s>]/g, element: "select", radix: "@radix-ui/react-select" },
        { pattern: /<dialog[\s>]/g, element: "dialog", radix: "@radix-ui/react-dialog" },
        { pattern: /type=["']checkbox["']/g, element: "checkbox input", radix: "@radix-ui/react-checkbox" },
        { pattern: /type=["']radio["']/g, element: "radio input", radix: "@radix-ui/react-radio-group" },
    ];

    for (const { pattern, element, radix } of nativeElements) {
        const count = countPattern(content, pattern);
        if (count > 0) {
            violations.push({
                type: "native-element",
                severity: "error",
                message: `Found ${count} native <${element}> element(s). Use ${radix} instead.`,
                file: relativePath,
                element,
                radix,
            });
        }
    }

    return violations;
}

/**
 * Print violations report
 */
function printReport(allViolations) {
    console.log("\n" + colors.blue + "━".repeat(80) + colors.reset);
    console.log(colors.blue + "  Architecture Compliance Check" + colors.reset);
    console.log(colors.blue + "━".repeat(80) + colors.reset + "\n");

    if (allViolations.length === 0) {
        console.log(colors.green + "✓ All checks passed! No violations found." + colors.reset + "\n");
        return 0;
    }

    // Group violations by type
    const byType = {
        "file-size": [],
        "use-state": [],
        "use-effect": [],
        "native-element": [],
    };

    for (const violation of allViolations) {
        byType[violation.type].push(violation);
    }

    let totalErrors = 0;

    // Print each violation type
    for (const [type, violations] of Object.entries(byType)) {
        if (violations.length === 0) continue;

        totalErrors += violations.length;

        const typeNames = {
            "file-size": "File Size Violations",
            "use-state": "useState Count Violations",
            "use-effect": "useEffect Count Violations",
            "native-element": "Native Element Violations (Use Radix UI)",
        };

        console.log(colors.red + `✗ ${typeNames[type]} (${violations.length})` + colors.reset);
        console.log(colors.gray + "─".repeat(80) + colors.reset);

        for (const violation of violations) {
            console.log(`  ${colors.yellow}${violation.file}${colors.reset}`);
            console.log(`    ${violation.message}`);

            if (violation.radix) {
                console.log(`    ${colors.gray}→ npm install ${violation.radix}${colors.reset}`);
            }

            console.log("");
        }
    }

    // Summary
    console.log(colors.blue + "━".repeat(80) + colors.reset);
    console.log(colors.red + `  Total violations: ${totalErrors}` + colors.reset);
    console.log(colors.blue + "━".repeat(80) + colors.reset + "\n");

    console.log(
        colors.yellow +
            "Fix these violations or update docs/architecture/rules/ if exceptions are needed." +
            colors.reset +
            "\n",
    );

    return 1; // Exit with error code
}

/**
 * Main execution
 */
function main() {
    console.log(colors.gray + "Scanning TypeScript files in js/ directory..." + colors.reset);

    const files = findFiles(CONFIG.componentsDir);
    console.log(colors.gray + `Found ${files.length} files to check\n` + colors.reset);

    const allViolations = [];

    for (const file of files) {
        const violations = checkFile(file);
        allViolations.push(...violations);
    }

    const exitCode = printReport(allViolations);
    process.exit(exitCode);
}

main();
