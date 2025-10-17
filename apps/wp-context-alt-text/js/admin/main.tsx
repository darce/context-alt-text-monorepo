/// <reference types="vite/client" />

import React from "react";
import { createRoot } from "react-dom/client";

import { App } from "./App";
import { RecognitionSettingsPanel } from "./settings/RecognitionSettingsPanel";
import { getDashboardConfig, getSettingsData } from "./dashboardData";
import { getAdminBootstrap, setAdminBootstrap } from "./globals";
import logger from "./logger";

if (typeof window !== "undefined") {
    const existingWp = (window as { wp?: unknown }).wp;
    if (existingWp && typeof existingWp === "object") {
        const wpGlobal = existingWp as Record<string, unknown>;
        if (!("svgPainter" in wpGlobal)) {
            Object.assign(wpGlobal, {
                svgPainter: {
                    init: () => {
                        // Fallback to keep WordPress admin handlers from crashing when svg-painter fails to bootstrap.
                    },
                },
            });
        }
    }
}

const tryRenderSettings = (): boolean => {
    const element = document.getElementById("context-alt-text-settings-root");
    if (!element) {
        return false;
    }

    element.removeAttribute("hidden");

    const config = getDashboardConfig();
    const settings = getSettingsData();
    const root = createRoot(element);

    root.render(
        <React.StrictMode>
            <RecognitionSettingsPanel
                initialSettings={settings.recognition}
                restNonce={config.restNonce ?? ""}
                saveEndpoint={config.endpoints?.settingsRecognition ?? ""}
                testEndpoint={config.endpoints?.settingsRecognitionTest ?? ""}
                canManage={Boolean(config.settings?.recognition?.canManage)}
                featureFlags={config.featureFlags ?? {}}
            />
        </React.StrictMode>,
    );

    return true;
};

if (!tryRenderSettings()) {
    interface MountCandidate {
        id: string;
        initialRoute: "dashboard" | "workbench";
    }

    const candidates: MountCandidate[] = [
        { id: "context-alt-text-admin-app", initialRoute: "dashboard" },
        { id: "context-alt-text-workbench-root", initialRoute: "workbench" },
    ];

    const selected = candidates
        .map((candidate) => ({ ...candidate, element: document.getElementById(candidate.id) }))
        .find((candidate) => Boolean(candidate.element));

    if (selected?.element) {
        const globalPayload = getAdminBootstrap();
        if (!globalPayload.page) {
            setAdminBootstrap({ ...globalPayload, page: selected.initialRoute });
        }

        const root = createRoot(selected.element);
        root.render(
            <React.StrictMode>
                <App />
            </React.StrictMode>,
        );
    } else if (import.meta.env.DEV) {
        const ids = candidates.map((candidate) => `#${candidate.id}`).join(", ");
        logger.warn(
            `Could not find a mount element. Ensure one of the following exists: ${ids}.`,
        );
    }
}
