import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";

import { App } from "@/app";
import { ToastProvider, Toaster } from "@/components/toast";
import "@/index.css";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: false,
      refetchOnWindowFocus: false,
    },
  },
});

// Optional error reporting: only loads @sentry/react when a DSN is baked in
// at build time (VITE_SENTRY_DSN). No DSN means zero Sentry code runs.
// beforeSend drops request bodies (may hold passwords and message texts).
const sentryDsn = import.meta.env.VITE_SENTRY_DSN as string | undefined;
if (sentryDsn) {
  void import("@sentry/react").then((sentry) => {
    sentry.init({
      dsn: sentryDsn,
      beforeSend(event) {
        if (event.request) {
          delete event.request.data;
        }
        return event;
      },
    });
  });
}

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <BrowserRouter>
          <App />
        </BrowserRouter>
        <Toaster />
      </ToastProvider>
    </QueryClientProvider>
  </React.StrictMode>,
);
