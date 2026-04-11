"use client";

import { useTranslations } from "next-intl";
import { useCallback, useState } from "react";

import { useRouter } from "@/i18n/navigation";
import { apiPatch, apiPost } from "@/lib/api";
import { uploadKnowledgeFiles } from "@/lib/knowledge-upload";

import { StepIdentity } from "./StepIdentity";
import { StepKnowledge } from "./StepKnowledge";
import { StepPersonality } from "./StepPersonality";

interface PipelineChoices {
  asrModelId?: string;
  asrModelName?: string;
  ttsModelId?: string;
  ttsModelName?: string;
}

interface WizardData {
  pipeline: PipelineChoices;
  knowledgeFiles: File[];
  personality: { description: string; tags: string[] };
  name: string;
  color: string;
  greeting: string;
}

const STEP_COUNT = 3;

const STEP_KEYS = [
  "wizard.stepPersonalityLabel",
  "wizard.stepIdentityLabel",
  "wizard.stepKnowledgeLabel",
] as const;

export function WizardShell() {
  const t = useTranslations("console-assistants");
  const router = useRouter();

  const [step, setStep] = useState(0);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [data, setData] = useState<WizardData>({
    pipeline: {
      asrModelId: "paraformer-v2",
      asrModelName: "Paraformer V2",
      ttsModelId: "cosyvoice-v1",
      ttsModelName: "CosyVoice V1",
    },
    knowledgeFiles: [],
    personality: { description: "", tags: [] },
    name: "",
    color: "accent",
    greeting: "",
  });

  const canNext = useCallback(() => {
    if (step === 0) return data.personality.description.trim().length > 0;
    if (step === 1) return data.name.trim().length > 0;
    return true;
  }, [step, data.personality.description, data.name]);

  const goNext = useCallback(() => {
    if (step < STEP_COUNT - 1) setStep((s) => s + 1);
  }, [step]);

  const goBack = useCallback(() => {
    if (step > 0) setStep((s) => s - 1);
  }, [step]);

  const handleSubmit = useCallback(async () => {
    if (!data.name.trim()) return;
    setIsSubmitting(true);

    try {
      const defaultModel = { id: "qwen3.5-plus", name: "Qwen 3.5 Plus", tier: "custom" as const };

      // Build description from personality choices
      const parts: string[] = [];
      parts.push(`[model:${defaultModel.id}|${defaultModel.tier}]`);
      if (data.personality.description) {
        parts.push(`[personality:${data.personality.description}]`);
      }
      if (data.personality.tags.length > 0) {
        parts.push(`[tags:${data.personality.tags.join(",")}]`);
      }
      if (data.color) {
        parts.push(`[color:${data.color}]`);
      }
      if (data.greeting) {
        parts.push(`[greeting:${data.greeting}]`);
      }
      const description = parts.join("\n");

      const result = await apiPost<{ id: string }>("/api/v1/projects", {
        name: data.name.trim(),
        description,
      });

      // Set pipeline configs after project creation
      const pipelinePromises: Promise<unknown>[] = [];

      // Always set the default LLM
      pipelinePromises.push(
        apiPatch("/api/v1/pipeline", {
          project_id: result.id,
          model_type: "llm",
          model_id: defaultModel.id,
          config_json: {},
        }),
      );

      if (data.pipeline.asrModelId) {
        pipelinePromises.push(
          apiPatch("/api/v1/pipeline", {
            project_id: result.id,
            model_type: "asr",
            model_id: data.pipeline.asrModelId,
            config_json: {},
          }),
        );
      }

      if (data.pipeline.ttsModelId) {
        pipelinePromises.push(
          apiPatch("/api/v1/pipeline", {
            project_id: result.id,
            model_type: "tts",
            model_id: data.pipeline.ttsModelId,
            config_json: {},
          }),
        );
      }

      // Fire all pipeline config calls concurrently
      await Promise.all(pipelinePromises);
      await uploadKnowledgeFiles(result.id, data.knowledgeFiles);

      router.push(`/app/assistants/${result.id}`);
    } catch {
      setIsSubmitting(false);
    }
  }, [data, router]);

  const isLastStep = step === STEP_COUNT - 1;

  return (
    <div className="wizard-shell">
      {/* Progress bar */}
      <div className="wizard-progress">
        {Array.from({ length: STEP_COUNT }).map((_, i) => (
          <div key={i} className="wizard-progress-step">
            {i > 0 && (
              <div
                className={`wizard-progress-line ${i <= step ? "wizard-progress-line--active" : ""}`}
              />
            )}
            <div
              className={`wizard-progress-circle ${
                i === step
                  ? "wizard-progress-circle--current"
                  : i < step
                    ? "wizard-progress-circle--done"
                    : ""
              }`}
            >
              {i < step ? (
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                  <polyline points="20 6 9 17 4 12" />
                </svg>
              ) : (
                i + 1
              )}
            </div>
            <span
              className={`wizard-progress-label ${
                i === step ? "wizard-progress-label--current" : ""
              }`}
            >
              {t(STEP_KEYS[i] as "wizard.stepPersonalityLabel")}
            </span>
          </div>
        ))}
      </div>

      {/* Step content */}
      <div className="wizard-content">
        {step === 0 && (
          <StepPersonality
            personality={data.personality}
            onPersonalityChange={(personality) =>
              setData((d) => ({ ...d, personality }))
            }
          />
        )}
        {step === 1 && (
          <StepIdentity
            name={data.name}
            color={data.color}
            greeting={data.greeting}
            onNameChange={(name) => setData((d) => ({ ...d, name }))}
            onColorChange={(color) => setData((d) => ({ ...d, color }))}
            onGreetingChange={(greeting) => setData((d) => ({ ...d, greeting }))}
          />
        )}
        {step === 2 && (
          <StepKnowledge
            files={data.knowledgeFiles}
            onFilesChange={(knowledgeFiles) =>
              setData((d) => ({ ...d, knowledgeFiles }))
            }
            onSubmit={handleSubmit}
            isSubmitting={isSubmitting}
          />
        )}
      </div>

      {/* Bottom navigation bar */}
      <div className="wizard-nav">
        {step > 0 ? (
          <button type="button" className="wizard-nav-btn wizard-nav-btn--back" onClick={goBack}>
            {t("wizard.back")}
          </button>
        ) : (
          <div />
        )}

        <div className="wizard-nav-right">
          {!isLastStep && (
            <button
              type="button"
              className="wizard-nav-btn wizard-nav-btn--next"
              onClick={goNext}
              disabled={!canNext()}
            >
              {t("wizard.next")}
            </button>
          )}
          {isLastStep && (
            <button
              type="button"
              className="wizard-nav-btn wizard-nav-btn--next"
              onClick={handleSubmit}
              disabled={isSubmitting}
            >
              {isSubmitting ? t("wizard.submitting") : t("wizard.finish")}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
