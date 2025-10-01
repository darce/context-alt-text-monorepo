import React from "react";
import { createRoot } from "react-dom/client";

import { App } from "./App";

type MountCandidate = {
  id: string;
  initialRoute: "dashboard" | "workbench";
};

const candidates: MountCandidate[] = [
  { id: "context-alt-text-admin-app", initialRoute: "dashboard" },
  { id: "context-alt-text-workbench-root", initialRoute: "workbench" },
];

const selected = candidates
  .map((candidate) => ({ ...candidate, element: document.getElementById(candidate.id) }))
  .find((candidate) => Boolean(candidate.element));

if (selected?.element) {
  const globalPayload = (window as any).ContextAltTextAdmin ?? {};
  if (!globalPayload.page) {
    globalPayload.page = selected.initialRoute;
    (window as any).ContextAltTextAdmin = globalPayload;
  }

  const root = createRoot(selected.element);
  root.render(
    <React.StrictMode>
      <App />
    </React.StrictMode>
  );
} else if (import.meta.env.DEV) {
  const ids = candidates.map((candidate) => `#${candidate.id}`).join(", ");
  console.warn(
    `[Context Alt Text] Could not find a mount element. Ensure one of the following exists: ${ids}.`,
  );
}
