import { beforeEach, describe, expect, it } from "vitest";

import { getDashboardConfig, getDashboardData, getWorkbenchData } from "./dashboardData";
import {
    dashboardContractPayload,
    dashboardContractExpectation,
    workbenchContractPayload,
    workbenchContractExpectation,
} from "@/admin/testing/fixtures/adminPayloads";
import { setAdminBootstrap } from "@/admin/globals";

describe("admin bootstrap REST contracts", () => {
    beforeEach(() => {
        setAdminBootstrap(undefined);
    });

    it("parses the dashboard bootstrap payload without losing data", () => {
        setAdminBootstrap(dashboardContractPayload);

        const data = getDashboardData();

        expect(data).toEqual(dashboardContractExpectation.data);
    });

    it("maps dashboard config endpoints and feature flags", () => {
        setAdminBootstrap(dashboardContractPayload);

        const config = getDashboardConfig();

        expect(config).toEqual(dashboardContractExpectation.config);
    });

    it("normalizes the workbench bootstrap payload into application types", () => {
        setAdminBootstrap(workbenchContractPayload);

        const workbenchData = getWorkbenchData();

        expect(workbenchData).toEqual(workbenchContractExpectation);
    });
});
