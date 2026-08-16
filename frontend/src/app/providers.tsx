"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { StorageMigrations } from "@/components/layout/StorageMigrations";

export function Providers({ children }: { children: ReactNode }) {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            // Prices move; a stale card is a wrong card. Short staleness plus a
            // visible "as of" stamp beats a spinner on every poll.
            staleTime: 20_000,
            refetchInterval: 60_000,
            refetchOnWindowFocus: true,
            retry: 1,
          },
        },
      }),
  );
  return (
    <QueryClientProvider client={client}>
      <StorageMigrations />
      {children}
    </QueryClientProvider>
  );
}
