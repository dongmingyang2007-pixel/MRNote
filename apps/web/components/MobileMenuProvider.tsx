"use client";

import { createContext, useCallback, useContext, useState, type ReactNode } from "react";

type MobileMenuContextValue = {
  open: boolean;
  openMenu: () => void;
  closeMenu: () => void;
};

const MobileMenuContext = createContext<MobileMenuContextValue>({
  open: false,
  openMenu: () => {},
  closeMenu: () => {},
});

export function useMobileMenu() {
  return useContext(MobileMenuContext);
}

export function MobileMenuProvider({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const openMenu = useCallback(() => setOpen(true), []);
  const closeMenu = useCallback(() => setOpen(false), []);

  return (
    <MobileMenuContext.Provider value={{ open, openMenu, closeMenu }}>
      {children}
    </MobileMenuContext.Provider>
  );
}
