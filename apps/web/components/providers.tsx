"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ReactNode, useState } from "react";

import { ViewTransition } from "@/components/ViewTransition";

export function Providers({ children }: { children: ReactNode }) {
  const [queryClient] = useState(() => new QueryClient());
  return (
    <QueryClientProvider client={queryClient}>
      <ViewTransition>{children}</ViewTransition>
    </QueryClientProvider>
  );
}
