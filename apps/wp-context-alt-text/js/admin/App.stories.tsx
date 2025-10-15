import type { Meta, StoryObj } from "@storybook/react";
import type { CSSProperties } from "react";
import { App } from "./App";
import { setAdminBootstrap } from "@/admin/globals";
import type { DashboardData, GlobalPayload } from "@/admin/types";

const meta: Meta<typeof App> = {
    title: "Admin/Dashboard",
    component: App,
    parameters: {
        layout: "fullscreen",
        docs: {
            description: {
                component:
                    "Dashboard buttons, tooltips, and progress bars use Radix primitives. Cards remain bespoke until Radix introduces a dedicated card primitive.",
            },
        },
    },
    decorators: [
        (Story) => {
            const sampleData: DashboardData = {
                hero: {
                    state: "ready",
                    message: "We found 5 images missing alt text.",
                    cta_label: "Open Alt-Text Workbench",
                    cta_url: "#",
                    last_updated_human: "2 minutes",
                },
                coverage: {
                    total: 120,
                    with_alt: 90,
                    missing: 30,
                    coverage_percent: 75,
                    trend_series: [
                        { timestamp: Date.now() - 3600 * 1000 * 3, coverage: 40, total: 120, with_alt: 48, missing: 72 },
                        { timestamp: Date.now() - 3600 * 1000 * 2, coverage: 55, total: 120, with_alt: 66, missing: 54 },
                        { timestamp: Date.now() - 3600 * 1000, coverage: 65, total: 120, with_alt: 78, missing: 42 },
                        { timestamp: Date.now(), coverage: 75, total: 120, with_alt: 90, missing: 30 },
                    ],
                },
                latestActivity: {
                    last_recognition: "5 minutes ago",
                    last_alt_text_generation: "just now",
                    last_roster_sync: "30 minutes ago",
                },
                recognition: {
                    pending_faces: 3,
                    pending_brands: 1,
                    unresolved_matches: 2,
                    roster_pending: 4,
                    roster_conflicts: 1,
                    roster_total: 12,
                    last_roster_sync_human: "30 minutes ago",
                    last_roster_sync_at: new Date().toISOString(),
                },
                automation: {
                    queued: 1,
                    running: 2,
                    completed: 6,
                    next_run: "15 minutes",
                },
                footer: {
                    actions: [
                        { label: "Run scan again", url: "#" },
                        { label: "Generate drafts", url: "#" },
                        { label: "Sync roster", url: "#" },
                    ],
                    statusText: "Last scan completed 2 minutes ago.",
                },
            };

            const bootstrap: GlobalPayload = {
                data: {
                    dashboard: sampleData,
                },
            };

            setAdminBootstrap(bootstrap);

            return <Story />;
        },
    ],
};

export default meta;

type Story = StoryObj<typeof App>;

export const Default: Story = {};

export const CustomTheme: Story = {
    decorators: [
        (Story) => (
            <div
                style={{
                    '--cat-accent': '#9333ea',
                    '--cat-accent-soft': 'rgba(147, 51, 234, 0.12)',
                    '--cat-background': '#0f172a',
                    '--cat-surface': '#111c32',
                    '--cat-text': '#f8fafc',
                    '--cat-border': 'rgba(148, 163, 184, 0.3)',
                    '--cat-muted': '#94a3b8',
                } as CSSProperties}
            >
                <Story />
            </div>
        ),
    ],
};
