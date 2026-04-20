"use client";

import { createContext, useContext, type ReactNode } from "react";
import { useRoleSelection, type UseRoleSelection } from "@/hooks/useRoleSelection";
import type { RoleKey } from "@/lib/marketing/role-content";

const RoleContext = createContext<UseRoleSelection | null>(null);

interface RoleProviderProps {
  initialRole: RoleKey | null;
  children: ReactNode;
}

export function RoleProvider({ initialRole, children }: RoleProviderProps) {
  const api = useRoleSelection(initialRole);
  return <RoleContext.Provider value={api}>{children}</RoleContext.Provider>;
}

export function useRoleContext(): UseRoleSelection {
  const ctx = useContext(RoleContext);
  if (!ctx) {
    throw new Error("useRoleContext must be used inside <RoleProvider>");
  }
  return ctx;
}
