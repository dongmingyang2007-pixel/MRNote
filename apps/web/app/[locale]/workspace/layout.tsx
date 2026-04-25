"use client";

import { useSyncExternalStore } from "react";
import { usePathname } from "next/navigation";

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
import OnboardingWizard from "@/components/onboarding/OnboardingWizard";
import DigestDrawer from "@/components/app/DigestDrawer";
import {
  getAuthStateClientSnapshot,
  getAuthStateHydrationSnapshot,
  subscribeAuthState,
} from "@/lib/auth-state";

function isPublicDraftPath(pathname: string | null): boolean {
  if (!pathname) return false;
  const normalizedPath = pathname.replace(/\/$/, "");
  return (
    normalizedPath === "/app/notebooks" ||
    normalizedPath === "/app/notebooks/guest" ||
    normalizedPath === "/en/app/notebooks" ||
    normalizedPath === "/en/app/notebooks/guest" ||
    normalizedPath === "/zh/app/notebooks" ||
    normalizedPath === "/zh/app/notebooks/guest" ||
    normalizedPath === "/workspace/notebooks" ||
    normalizedPath === "/workspace/notebooks/guest" ||
    normalizedPath === "/en/workspace/notebooks" ||
    normalizedPath === "/en/workspace/notebooks/guest" ||
    normalizedPath === "/zh/workspace/notebooks" ||
    normalizedPath === "/zh/workspace/notebooks/guest"
  );
}

export default function ConsoleLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const pathname = usePathname();
  const isAuthenticated = useSyncExternalStore(
    subscribeAuthState,
    getAuthStateClientSnapshot,
    getAuthStateHydrationSnapshot,
  );

  if (isPublicDraftPath(pathname) && isAuthenticated !== true) {
    return (
      <MobileMenuProvider>
        <ModalProvider>
          <div data-theme="console">
            <GlassTopBar guestMode />
            <ConsoleShell>{children}</ConsoleShell>
            <Toaster />
          </div>
        </ModalProvider>
      </MobileMenuProvider>
    );
  }

  return (
    <ProjectProvider>
      <DevModeProvider>
        <MobileMenuProvider>
          <ModalProvider>
            <div data-theme="console">
              <DigestDrawer />
              <GlassTopBar />
              <ConsoleShell>{children}</ConsoleShell>
              <GlassStatusBar />
              <UnifiedMobileNav />
              <MobileTabBar />
              <CommandPalette />
              <AuthSessionGuard />
              <Toaster />
              <UpgradeModal />
              <OnboardingWizard />
            </div>
          </ModalProvider>
        </MobileMenuProvider>
      </DevModeProvider>
    </ProjectProvider>
  );
}
