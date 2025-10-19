import { __ } from "@wordpress/i18n";
import type { CoverageCard } from "@/admin/types";

/**
 * Export coverage data as CSV file
 *
 * Generates a CSV file with coverage metrics and trend data (if available),
 * then triggers a browser download.
 *
 * @param {CoverageCard} coverage - Coverage data to export
 *
 * @example
 * ```ts
 * const coverage = {
 *   total: 100,
 *   with_alt: 85,
 *   missing: 15,
 *   coverage_percent: 85,
 *   trend_series: [...],
 * };
 *
 * exportCoverageToCSV(coverage);
 * // Downloads: coverage-report-2025-10-18.csv
 * ```
 */
export const exportCoverageToCSV = (coverage: CoverageCard): void => {
    if (typeof window === "undefined" || typeof document === "undefined") {
        return;
    }

    // Build CSV rows
    const rows: string[][] = [
        [__("Metric", "context-alt-text"), __("Value", "context-alt-text")],
        [__("Total items", "context-alt-text"), String(coverage.total)],
        [__("With alt text", "context-alt-text"), String(coverage.with_alt)],
        [__("Missing alt text", "context-alt-text"), String(coverage.missing)],
        [__("Coverage percent", "context-alt-text"), `${coverage.coverage_percent}`],
    ];

    // Add trend series if available
    if (Array.isArray(coverage.trend_series) && coverage.trend_series.length > 0) {
        rows.push([]);
        rows.push([
            __("Timestamp", "context-alt-text"),
            __("Coverage percent", "context-alt-text"),
            __("Total items", "context-alt-text"),
            __("With alt text", "context-alt-text"),
            __("Missing alt text", "context-alt-text"),
        ]);

        for (const point of coverage.trend_series) {
            rows.push([
                new Date(point.timestamp).toISOString(),
                `${point.coverage}`,
                String(point.total),
                String(point.with_alt),
                String(point.missing),
            ]);
        }
    }

    // Escape CSV cells
    const escapeCell = (cell: string): string => {
        if (cell.includes('"')) {
            return `"${cell.replace(/"/g, '""')}"`;
        }

        if (cell.includes(",") || cell.includes("\n")) {
            return `"${cell}"`;
        }

        return cell;
    };

    // Generate CSV content
    const csvContent = rows.map((row) => row.map((cell) => escapeCell(cell)).join(",")).join("\r\n");

    // Check for required browser APIs
    if (typeof window.URL?.createObjectURL !== "function" || !document.body) {
        return;
    }

    // Create blob and trigger download
    const blob = new Blob([csvContent], { type: "text/csv;charset=utf-8" });
    const url = window.URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `coverage-report-${new Date().toISOString().slice(0, 10)}.csv`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    window.URL.revokeObjectURL(url);
};
