"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ThemeProvider } from "next-themes";
import { useState, type ReactNode } from "react";

import { TradeUpdateNotifier } from "@/components/trade-update-notifier";
import { TooltipProvider } from "@/components/ui/tooltip";
import { Toaster } from "@/components/ui/sonner";

// ReactQueryDevtools is intentionally NOT mounted. @tanstack/query-devtools
// has a getDefaultLocale() bug (in build/dev.cjs at the time of writing,
// v5.100.10) that throws RangeError: "invalid language tag: 'undefined'"
// when navigator.language resolves to the literal string "undefined" —
// which it does in some browser/extension combinations on Windows. The
// crash propagates up to the React tree and blanks the whole page.
// Re-enable only after upstream ships a fix; verify by searching for
// getDefaultLocale in the installed package and checking the precedence
// of the navigator.language || navigator.userLanguage || "en-US" chain.
export function Providers({ children }: { children: ReactNode }) {
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            // The API endpoints are local; fail fast and retry only once
            // so a downed Docker stack surfaces immediately in the UI.
            retry: 1,
            staleTime: 30_000,
            refetchOnWindowFocus: false,
          },
        },
      }),
  );

  return (
    <ThemeProvider attribute="class" defaultTheme="dark" enableSystem>
      <QueryClientProvider client={queryClient}>
        <TooltipProvider>
          {children}
          <TradeUpdateNotifier />
          <Toaster richColors closeButton />
        </TooltipProvider>
      </QueryClientProvider>
    </ThemeProvider>
  );
}
