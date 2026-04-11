"use client";

import { PageTransition } from "@/components/console/PageTransition";
import { WizardShell } from "@/components/console/wizard/WizardShell";

export default function NewAssistantPage() {
  return (
    <PageTransition>
      <WizardShell />
    </PageTransition>
  );
}
