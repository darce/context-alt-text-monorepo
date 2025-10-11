import { beforeEach, describe, expect, it } from "vitest";

import { getDashboardConfig, getDashboardData, getWorkbenchData } from "./dashboardData";
import {
    dashboardContractPayload,
    dashboardContractExpectation,
    workbenchContractPayload,
    workbenchContractExpectation,
} from "@/admin/testing/fixtures/adminPayloads";

describe("admin bootstrap REST contracts", () => {
    beforeEach(() => {
        (globalThis as any).ContextAltTextAdmin = undefined;
    });

    it("parses the dashboard bootstrap payload without losing data", () => {
        (globalThis as any).ContextAltTextAdmin = dashboardContractPayload;

        const data = getDashboardData();

        expect(data).toEqual(dashboardContractExpectation.data);
    });

    it("maps dashboard config endpoints and feature flags", () => {
        (globalThis as any).ContextAltTextAdmin = dashboardContractPayload;

        const config = getDashboardConfig();

        expect(config).toEqual(dashboardContractExpectation.config);
    });

    it("normalizes the workbench bootstrap payload into application types", () => {
        (globalThis as any).ContextAltTextAdmin = workbenchContractPayload;

        const workbenchData = getWorkbenchData();

        expect(workbenchData).toEqual(workbenchContractExpectation);
    });
});
