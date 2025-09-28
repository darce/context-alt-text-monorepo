import React from "react";
import { createRoot } from "react-dom/client";

import { App } from "./App";

const mountId = "context-alt-text-admin-app";
const container = document.getElementById(mountId);

if (container) {
  const root = createRoot(container);
  root.render(
    <React.StrictMode>
      <App />
    </React.StrictMode>
  );
} else {
  if (import.meta.env.DEV) {
    console.warn(
      `[Context Alt Text] Could not find mount element #${mountId}. Ensure DashboardPage renders the container.`
    );
  }
}
