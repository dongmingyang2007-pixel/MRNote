"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";

import "@/styles/onboarding.css";

import { useOnboardingStatus } from "@/hooks/useOnboardingStatus";
import { apiPost } from "@/lib/api";

import WelcomeStep from "./steps/WelcomeStep";
import CreateNotebookStep from "./steps/CreateNotebookStep";
import PasteNoteStep from "./steps/PasteNoteStep";
import MemoryPreviewStep from "./steps/MemoryPreviewStep";
import NextStepsStep from "./steps/NextStepsStep";

const TOTAL_STEPS = 5;

interface NotebookCreateResponse {
  id: string;
}

interface PageCreateResponse {
  id: string;
}

export default function OnboardingWizard() {
  const t = useTranslations("onboarding");
  const { completed, markCompleted } = useOnboardingStatus();

  const [currentStep, setCurrentStep] = useState(0);
  const [clientName, setClientName] = useState("");
  const [whatTheyDo, setWhatTheyDo] = useState("");
  const [noteText, setNoteText] = useState("");
  const [busy, setBusy] = useState(false);
  const [notebookId, setNotebookId] = useState<string | null>(null);

  if (completed !== false) {
    // null → still loading; true → already onboarded → render nothing.
    return null;
  }

  const goNext = async () => {
    if (busy) return;

    // Step-specific side effects before advancing.
    if (currentStep === 1) {
      // Create notebook when leaving Step 1 (if user entered a name).
      const title = clientName.trim();
      if (title.length === 0) {
        // Let user advance anyway — wizard is guidance, not validation.
        setCurrentStep(2);
        return;
      }
      try {
        setBusy(true);
        const description = whatTheyDo.trim();
        const nb = await apiPost<NotebookCreateResponse>(
          "/api/v1/notebooks",
          {
            title,
            description,
            notebook_type: "personal",
            visibility: "private",
          },
        );
        setNotebookId(nb.id);
      } catch {
        // Non-fatal; continue.
      } finally {
        setBusy(false);
      }
      setCurrentStep(2);
      return;
    }

    if (currentStep === 2) {
      // Create a page if the note textarea has content and we have a notebook.
      const text = noteText.trim();
      if (text.length > 0 && notebookId) {
        try {
          setBusy(true);
          await apiPost<PageCreateResponse>(
            `/api/v1/notebooks/${notebookId}/pages`,
            {
              title: text.slice(0, 60) || "First note",
              plain_text: text,
            },
          );
        } catch {
          // Non-fatal.
        } finally {
          setBusy(false);
        }
      }
      setCurrentStep(3);
      return;
    }

    if (currentStep === TOTAL_STEPS - 1) {
      setBusy(true);
      await markCompleted();
      setBusy(false);
      return;
    }

    setCurrentStep((s) => Math.min(s + 1, TOTAL_STEPS - 1));
  };

  const goBack = () => {
    if (busy) return;
    setCurrentStep((s) => Math.max(0, s - 1));
  };

  const primaryLabel = (() => {
    if (busy) {
      if (currentStep === 1) return t("createNotebook.creating");
      if (currentStep === 2) return t("pasteNote.saving");
      if (currentStep === TOTAL_STEPS - 1) return t("nextSteps.completing");
      return t("common.next");
    }
    switch (currentStep) {
      case 0:
        return t("welcome.cta");
      case 1:
        return t("createNotebook.cta");
      case 2:
        return t("pasteNote.cta");
      case 3:
        return t("memoryPreview.cta");
      case 4:
        return t("nextSteps.cta");
      default:
        return t("common.next");
    }
  })();

  return (
    <div
      className="onboarding-overlay"
      role="dialog"
      aria-modal="true"
      aria-labelledby="onboarding-title"
      data-testid="onboarding-wizard"
    >
      <div className="onboarding-card">
        <div className="onboarding-card__header">
          <div className="onboarding-card__dots">
            {Array.from({ length: TOTAL_STEPS }).map((_, idx) => (
              <span
                key={idx}
                className={
                  "onboarding-card__dot" +
                  (idx === currentStep
                    ? " onboarding-card__dot--active"
                    : idx < currentStep
                      ? " onboarding-card__dot--done"
                      : "")
                }
              />
            ))}
          </div>
          <span className="onboarding-card__step-label">
            {t("common.step", {
              current: currentStep + 1,
              total: TOTAL_STEPS,
            })}
          </span>
        </div>

        <div className="onboarding-card__body" id="onboarding-title">
          {currentStep === 0 && <WelcomeStep />}
          {currentStep === 1 && (
            <CreateNotebookStep
              clientName={clientName}
              onClientNameChange={setClientName}
              whatTheyDo={whatTheyDo}
              onWhatTheyDoChange={setWhatTheyDo}
            />
          )}
          {currentStep === 2 && (
            <PasteNoteStep
              noteText={noteText}
              onNoteTextChange={setNoteText}
            />
          )}
          {currentStep === 3 && <MemoryPreviewStep />}
          {currentStep === 4 && <NextStepsStep />}
        </div>

        <div className="onboarding-card__footer">
          <button
            type="button"
            className="onboarding-btn onboarding-btn--secondary"
            onClick={goBack}
            disabled={currentStep === 0 || busy}
            data-testid="onboarding-back"
          >
            {t("common.back")}
          </button>
          <button
            type="button"
            className="onboarding-btn onboarding-btn--primary"
            onClick={goNext}
            disabled={busy}
            data-testid="onboarding-next"
          >
            {primaryLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
