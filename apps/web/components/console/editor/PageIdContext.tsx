"use client";

import { createContext, useContext, type ReactNode } from "react";

const PageIdContext = createContext<string | null>(null);

export function PageIdProvider({
  pageId,
  children,
}: {
  pageId: string;
  children: ReactNode;
}) {
  return (
    <PageIdContext.Provider value={pageId}>{children}</PageIdContext.Provider>
  );
}

export function useCurrentPageId(): string | null {
  return useContext(PageIdContext);
}
