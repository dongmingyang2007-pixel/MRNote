"use client";

import { type ReactNode } from "react";
import { AmbientBackground } from "./glass";
import { Sidebar } from "./Sidebar";

interface ConsoleShellProps {
  children: ReactNode;
}

export function ConsoleShell({ children }: ConsoleShellProps) {
  return (
    <div className="console-shell-v2" style={{ position: "relative", minHeight: "100vh" }}>
      <AmbientBackground />
      <Sidebar />
      <main
        className="console-shell-main"
        style={{
          position: "relative",
          zIndex: 1,
          marginLeft: 56,
          marginTop: 48,
          marginBottom: 28,
          minHeight: "calc(100vh - 48px - 28px)",
        }}
      >
        {children}
      </main>
    </div>
  );
}
