"use client";

import { useRef, useState } from "react";
import { useTranslations } from "next-intl";

import "@/styles/onboarding.css";

import { useOnboardingStatus } from "@/hooks/useOnboardingStatus";
import { apiPost } from "@/lib/api";
import {
  dispatchNotebookPagesChanged,
  dispatchNotebooksChanged,
} from "@/lib/notebook-events";

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
  const tn = useTranslations("console-notebooks");
  const { completed, markCompleted } = useOnboardingStatus();

  const [currentStep, setCurrentStep] = useState(0);
  const [clientName, setClientName] = useState("");
  const [whatTheyDo, setWhatTheyDo] = useState("");
  const [noteText, setNoteText] = useState("");
  const [busy, setBusy] = useState(false);
  const [stepError, setStepError] = useState("");
  const [notebookId, setNotebookId] = useState<string | null>(null);
  const [pageId, setPageId] = useState<string | null>(null);

  // Track direction so children can optionally animate correctly.
  const directionRef = useRef<"forward" | "back">("forward");

  if (completed !== false) {
    // null → still loading; true → already onboarded → render nothing.
    return null;
  }

  const goNext = async () => {
    if (busy) return;
    directionRef.current = "forward";
    setStepError("");

    // Step-specific side effects before advancing.
    if (currentStep === 1) {
      if (notebookId) {
        setCurrentStep(2);
        return;
      }
      try {
        setBusy(true);
        const title = clientName.trim();
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
        dispatchNotebooksChanged();
        dispatchNotebookPagesChanged(nb.id);
        setCurrentStep(2);
      } catch {
        setStepError(tn("notebooks.createFailed"));
        return;
      } finally {
        setBusy(false);
      }
      return;
    }

    if (currentStep === 2) {
      if (pageId) {
        setCurrentStep(3);
        return;
      }
      if (!notebookId) {
        setStepError(tn("notebooks.createFailed"));
        return;
      }

      const text = noteText.trim();
      try {
        setBusy(true);
        const page = await apiPost<PageCreateResponse>(
          `/api/v1/notebooks/${notebookId}/pages`,
          {
            title: text.slice(0, 60) || t("pasteNote.defaultPageTitle"),
            content_json:
              text.length > 0
                ? {
                    type: "doc",
                    content: [
                      {
                        type: "paragraph",
                        content: [{ type: "text", text }],
                      },
                    ],
                  }
                : { type: "doc", content: [] },
          },
        );
        setPageId(page.id);
        dispatchNotebookPagesChanged(notebookId);
        setCurrentStep(3);
      } catch {
        setStepError(tn("pages.createFailed"));
        return;
      } finally {
        setBusy(false);
      }
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
    directionRef.current = "back";
    setStepError("");
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

  // Determine animation class based on direction.
  const stepAnimClass =
    directionRef.current === "back"
      ? "onboarding-step-enter-back"
      : "onboarding-step-enter";

  return (
    <div
      className="onboarding-overlay"
      role="dialog"
      aria-modal="true"
      aria-labelledby="onboarding-title"
      data-testid="onboarding-wizard"
    >
      <div className="onboarding-card">
        {/* Header: brand wordmark (left) + step dots (right) */}
        <div className="onboarding-card__header">
          <span className="onboarding-card__wordmark">MRNote</span>
          <div className="onboarding-card__dots" aria-hidden="true">
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

        {/* Body — key remount drives enter animation */}
        <div className="onboarding-card__body" id="onboarding-title">
          <div key={currentStep} className={stepAnimClass}>
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
        </div>

        {/* Footer */}
        <div className="onboarding-card__footer">
          {stepError ? (
            <div
              role="alert"
              aria-live="polite"
              data-testid="onboarding-error"
              style={{
                flexBasis: "100%",
                marginBottom: 12,
                borderRadius: 12,
                border: "1px solid rgba(239, 68, 68, 0.18)",
                background: "rgba(254, 242, 242, 0.92)",
                color: "#b91c1c",
                padding: "10px 12px",
                fontSize: 13,
                lineHeight: 1.45,
              }}
            >
              {stepError}
            </div>
          ) : null}
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
