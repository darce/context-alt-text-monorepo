import { describe, it, expect, beforeEach } from "vitest";

import { getDashboardConfig, getDashboardData, getInitialRoute, getWorkbenchData } from "./dashboardData";
import type { AdminConfig, DashboardData } from "@/admin/types";
import { setAdminBootstrap } from "@/admin/globals";

describe("dashboardData", () => {
    beforeEach(() => {
        setAdminBootstrap(undefined);
    });

    it("returns fallback values when global payload is missing", () => {
        const data = getDashboardData();

        expect(data.hero.message).toContain("Scanning");
        expect(data.coverage.total).toBe(0);
        expect(data.recognition.pending_faces).toBe(0);
        expect(data.recognition.roster_pending).toBe(0);
        expect(data.recognition.last_roster_sync_human).toBeNull();
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

        setAdminBootstrap({
            data: { dashboard: payload },
        });

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

        setAdminBootstrap({
            config,
        });

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

    it("returns fallback workbench data when payload is missing", () => {
        const data = getWorkbenchData();

        expect(data.items).toHaveLength(0);
        expect(data.viewMode).toBe("list");
        expect(data.pagination).toMatchObject({ page: 1, perPage: 20, total: 0, totalPages: 0 });
    });

    it("normalizes workbench bootstrap data from the global payload", () => {
        setAdminBootstrap({
            data: {
                workbench: {
                    viewMode: "grid",
                    pagination: {
                        page: 2,
                        perPage: 15,
                        total: 30,
                        totalPages: 2,
                    },
                    items: [
                        {
                            id: 42,
                            title: "Sample asset",
                            status: "draft",
                            updatedAt: "2024-04-02T00:00:00.000Z",
                            altText: "Drafted alt text",
                            mimeType: "image/jpeg",
                            dimensions: { width: 1200, height: 800 },
                            editUrl: "https://example.com/edit/42",
                        },
                        {
                            id: null,
                            title: null,
                        },
                    ],
                },
            },
        });

        const data = getWorkbenchData();

        expect(data.items).toEqual([
            {
                id: "42",
                title: "Sample asset",
                status: "draft",
                updatedAt: "2024-04-02T00:00:00.000Z",
                altText: "Drafted alt text",
                mimeType: "image/jpeg",
                dimensions: { width: 1200, height: 800 },
                editUrl: "https://example.com/edit/42",
                thumbnailUrl: undefined,
            },
        ]);
        expect(data.viewMode).toBe("grid");
        expect(data.pagination).toEqual({ page: 2, perPage: 15, total: 30, totalPages: 2 });
    });

    it("derives the initial route from the global payload", () => {
        setAdminBootstrap({ page: "workbench" });
        expect(getInitialRoute()).toBe("workbench");

        setAdminBootstrap({ page: "roster" });
        expect(getInitialRoute()).toBe("roster");

        setAdminBootstrap({ page: "dashboard" });
        expect(getInitialRoute()).toBe("dashboard");

        setAdminBootstrap({ page: "unknown" });
        expect(getInitialRoute()).toBe("dashboard");
    });
});
