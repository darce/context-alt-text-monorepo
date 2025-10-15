import { expect } from "vitest";
import "@testing-library/jest-dom/vitest";
import "@/admin/testing/mswServer";
import * as matchers from "vitest-axe/matchers";

expect.extend(matchers);

if (typeof HTMLCanvasElement !== "undefined") {
    const canvasContextStub = function canvasContextStub(
        this: HTMLCanvasElement,
        contextId: string,
        options?: CanvasRenderingContext2DSettings,
    ): null {
        void contextId;
        void options;
        return null;
    };

    HTMLCanvasElement.prototype.getContext = canvasContextStub as HTMLCanvasElement["getContext"];
}
