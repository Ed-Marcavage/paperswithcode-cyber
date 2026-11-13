import posthog from "posthog-js";
import { catalogOptions, catalogPrivacySignal, startCatalogRecording } from "./lib/catalogAnalytics";
import { isDiscoveryCatalog } from "./lib/apiUrl";
import React from "react";
import { createRoot } from "react-dom/client";
import { ThemeProvider } from "next-themes";
import { PostHogProvider } from "@posthog/react";

import AppErrorBoundary from "./components/AppErrorBoundary";
import "./index.css";
import { installChunkReloadRecovery } from "./lib/chunkReload";
import { posthogPrivacyOptions } from "./lib/posthogPrivacy";
import "./styles.css";
import "./styles/features/index.css";
import "./components/chat/styles/index.css";
import App from "./App";

installChunkReloadRecovery();

const posthogToken = import.meta.env.VITE_POSTHOG_PROJECT_TOKEN;

const catalog = isDiscoveryCatalog();
// Do Not Track or Global Privacy Control: no analytics and no session recording.
if (catalog && posthogToken && !catalogPrivacySignal()) {
  posthog.init(posthogToken, catalogOptions);
  void startCatalogRecording();
}

const app = (
  <ThemeProvider
    attribute="class"
    defaultTheme="system"
    enableSystem
    disableTransitionOnChange
    storageKey="pwc-theme"
  >
    <AppErrorBoundary>
      <App />
    </AppErrorBoundary>
  </ThemeProvider>
);

const root = createRoot(document.getElementById("root")!);
root.render(
  <React.StrictMode>
    {posthogToken && !catalog ? (
      <PostHogProvider apiKey={posthogToken} options={posthogPrivacyOptions}>
        {app}
      </PostHogProvider>
    ) : app}
  </React.StrictMode>,
);
