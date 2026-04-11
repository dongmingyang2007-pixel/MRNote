"use client";

import {
  createContext,
  useContext,
  useSyncExternalStore,
  type ReactNode,
} from "react";

interface DevModeContextType {
  isDeveloperMode: boolean;
  toggleDeveloperMode: () => void;
}

const DevModeContext = createContext<DevModeContextType>({
  isDeveloperMode: false,
  toggleDeveloperMode: () => {},
});

const DEV_MODE_KEY = "developer-mode";
const DEV_MODE_EVENT = "developer-mode-change";

function readDeveloperMode(): boolean {
  if (typeof window === "undefined") {
    return false;
  }
  return localStorage.getItem(DEV_MODE_KEY) === "true";
}

function subscribeDeveloperMode(onStoreChange: () => void): () => void {
  if (typeof window === "undefined") {
    return () => {};
  }
  const handleStorage = (event: Event) => {
    if (event instanceof StorageEvent && event.key === DEV_MODE_KEY) {
      onStoreChange();
    }
  };
  window.addEventListener("storage", handleStorage);
  window.addEventListener(DEV_MODE_EVENT, onStoreChange);
  return () => {
    window.removeEventListener("storage", handleStorage);
    window.removeEventListener(DEV_MODE_EVENT, onStoreChange);
  };
}

export function DevModeProvider({ children }: { children: ReactNode }) {
  const isDeveloperMode = useSyncExternalStore(
    subscribeDeveloperMode,
    readDeveloperMode,
    () => false,
  );

  const toggleDeveloperMode = () => {
    const next = !isDeveloperMode;
    localStorage.setItem(DEV_MODE_KEY, String(next));
    window.dispatchEvent(new Event(DEV_MODE_EVENT));
  };

  return (
    <DevModeContext.Provider value={{ isDeveloperMode, toggleDeveloperMode }}>
      {children}
    </DevModeContext.Provider>
  );
}

export const useDeveloperMode = () => useContext(DevModeContext);
