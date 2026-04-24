"use client";

import { type ReactNode } from "react";
import { AmbientBackground } from "./glass";
import GlobalSidebar from "./GlobalSidebar";

interface ConsoleShellProps {
  children: ReactNode;
}

export function ConsoleShell({ children }: ConsoleShellProps) {
  return (
    <div className="console-shell-v2" style={{ position: "relative", minHeight: "100vh" }}>
      <AmbientBackground />
      <GlobalSidebar />
      <main
        className="console-shell-main"
        style={{
          position: "relative",
          zIndex: 1,
          marginLeft: "var(--console-shell-offset-left, 56px)",
          marginTop: "var(--console-shell-offset-top, 56px)",
          marginBottom: "var(--console-shell-offset-bottom, 28px)",
          minHeight: "calc(100vh - var(--console-shell-offset-top, 56px) - var(--console-shell-offset-bottom, 28px))",
        }}
      >
        {children}
      </main>
    </div>
  );
}
