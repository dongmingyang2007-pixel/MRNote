"use client";

import { ProjectProvider } from "@/lib/ProjectContext";
import { DevModeProvider } from "@/lib/developer-mode";
import { MobileMenuProvider } from "@/components/MobileMenuProvider";
import { UnifiedMobileNav } from "@/components/UnifiedMobileNav";
import { ConsoleShell } from "@/components/console/ConsoleShell";
import { MobileTabBar } from "@/components/console/MobileTabBar";
import { CommandPalette } from "@/components/console/CommandPalette";
import { Toaster } from "@/components/ui/toaster";
import { ModalProvider } from "@/components/ui/modal-dialog";
import { AuthSessionGuard } from "@/components/AuthSessionGuard";
import { GlassTopBar, GlassStatusBar } from "@/components/console/glass";
import UpgradeModal from "@/components/billing/UpgradeModal";

export default function ConsoleLayout({ children }: { children: React.ReactNode }) {
  return (
    <ProjectProvider>
      <DevModeProvider>
        <MobileMenuProvider>
          <ModalProvider>
            <div data-theme="console">
              <GlassTopBar />
              <ConsoleShell>
                {children}
              </ConsoleShell>
              <GlassStatusBar />
              <UnifiedMobileNav />
              <MobileTabBar />
              <CommandPalette />
              <AuthSessionGuard />
              <Toaster />
              <UpgradeModal />
            </div>
          </ModalProvider>
        </MobileMenuProvider>
      </DevModeProvider>
    </ProjectProvider>
  );
}
