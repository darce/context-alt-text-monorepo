import { describe, it, expect, beforeEach } from "vitest";

import { getDashboardConfig, getDashboardData } from "./dashboardData";
import type { AdminConfig, DashboardData } from "@/admin/types";

describe("dashboardData", () => {
    beforeEach(() => {
        (globalThis as any).ContextAltTextAdmin = undefined;
    });

    it("returns fallback values when global payload is missing", () => {
        const data = getDashboardData();

        expect(data.hero.message).toContain("Scanning");
        expect(data.coverage.total).toBe(0);
        expect(data.recognition.pending_faces).toBe(0);
        expect(data.footer.actions).toHaveLength(0);
    });

    it("merges global payload with fallbacks", () => {
        const payload: Partial<DashboardData> = {
            hero: {
                state: "ready",
                message: "We found 5 images missing alt text.",
                cta_label: "Open workbench",
                cta_url: "#",
                last_updated_human: "2 minutes",
            },
            coverage: {
                total: 10,
                with_alt: 6,
                missing: 4,
                coverage_percent: 60,
            },
            footer: {
                actions: [{ label: "Sync roster", url: "#" }],
                statusText: "Last scan completed 2 minutes ago.",
            },
        };

        (globalThis as any).ContextAltTextAdmin = {
            data: { dashboard: payload },
        };

        const data = getDashboardData();

        expect(data.hero.message).toBe(payload.hero?.message);
        expect(data.coverage.missing).toBe(4);
        expect(data.coverage.trend_series).toEqual([]);
        expect(data.footer.actions).toHaveLength(1);
        expect(data.footer.statusText).toContain("Last scan");
    });

    it("reads dashboard config from the global payload", () => {
        const config: AdminConfig = {
            missingAltMediaUrl: "/wp-admin/upload.php",
            endpoints: {
                coverage: "https://example.com/wp-json/context-alt-text/v1/dashboard/coverage",
            },
            restNonce: "nonce-wp_rest",
        };

        (globalThis as any).ContextAltTextAdmin = {
            config,
        };

        const value = getDashboardConfig();
        expect(value.missingAltMediaUrl).toBe(config.missingAltMediaUrl);
        expect(value.endpoints?.coverage).toBe(config.endpoints?.coverage);
        expect(value.restNonce).toBe("nonce-wp_rest");
    });

    it("falls back to empty config when payload is missing", () => {
        const value = getDashboardConfig();
        expect(value.missingAltMediaUrl).toBeUndefined();
        expect(value.endpoints?.coverage).toBeUndefined();
        expect(value.restNonce).toBeUndefined();
    });
});
