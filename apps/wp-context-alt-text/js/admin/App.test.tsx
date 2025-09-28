import { describe, expect, it, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { axe } from "vitest-axe";
import { http, HttpResponse } from "msw";

import { App } from "./App";
import { useDashboardHandlers } from "@/admin/testing/mswServer";

const COVERAGE_ENDPOINT = "https://example.com/wp-json/cat/v1/dashboard/coverage";

const bootstrapPayload = {
    hero: {
        state: "ready" as const,
        message: "We found 12 images missing alt text.",
        cta_label: "Open Alt-Text Workbench",
        cta_url: "/wp-admin/admin.php?page=context-alt-text-workbench",
        last_updated_human: "5 minutes",
    },
    coverage: {
        total: 40,
        with_alt: 28,
        missing: 12,
        coverage_percent: 70,
        trend_series: [],
    },
    latestActivity: {
        last_recognition: null,
        last_alt_text_generation: null,
        last_roster_sync: null,
    },
    recognition: {
        pending_faces: 0,
        pending_brands: 0,
        unresolved_matches: 0,
    },
    automation: {
        queued: 0,
        running: 0,
        completed: 0,
        next_run: null,
    },
    footer: {
        actions: [
            { label: "Run scan again", url: "/wp-admin/admin.php?page=context-alt-text-scan" },
            { label: "Open Alt-Text Workbench", url: "/wp-admin/admin.php?page=context-alt-text-workbench" },
        ],
        statusText: "Last scan completed 5 minutes ago.",
    },
};

describe("App", () => {
    beforeEach(() => {
        (globalThis as any).ContextAltTextAdmin = {
            config: {
                endpoints: {
                    coverage: COVERAGE_ENDPOINT,
                },
                restNonce: "dashboard-nonce",
            },
            data: {
                dashboard: bootstrapPayload,
            },
        };

        useDashboardHandlers(
            http.get(COVERAGE_ENDPOINT, () => {
                console.info("coverage handler invoked");
                return HttpResponse.json({
                    total: 44,
                    with_alt: 40,
                    missing: 4,
                    coverage_percent: 90,
                    trend_series: [
                        {
                            timestamp: Date.now() - 60_000,
                            coverage: 80,
                            total: 40,
                            with_alt: 32,
                            missing: 8,
                        },
                        {
                            timestamp: Date.now(),
                            coverage: 90,
                            total: 44,
                            with_alt: 40,
                            missing: 4,
                        },
                    ],
                });
            }),
        );
    });

    afterEach(() => {
        (globalThis as any).ContextAltTextAdmin = undefined;
    });

    it("hydrates the dashboard and passes accessibility checks", async () => {
        const originalFetch = global.fetch;
        global.fetch = async (...args) => {
            console.info("fetch invoked", args[0]);
            return originalFetch(...args);
        };

        const { container } = render(<App />);

        expect(screen.getByText(/We found 12 images missing alt text/i)).toBeInTheDocument();


        await screen.findByRole("img", { name: /Coverage 90%/i });
        await screen.findByText("44");

        const results = await axe(container);
        expect(results).toHaveNoViolations();

        global.fetch = originalFetch;
    });
});
