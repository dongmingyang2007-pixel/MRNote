"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useParams } from "next/navigation";
import { useTranslations } from "next-intl";

import { ModelPickerModal } from "@/components/console/ModelPickerModal";
import { PageTransition } from "@/components/console/PageTransition";
import { GlassCard, GlassButton } from "@/components/console/glass";
import { StepIdentity } from "@/components/console/wizard/StepIdentity";
import { StepPersonality } from "@/components/console/wizard/StepPersonality";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Link, useRouter } from "@/i18n/navigation";
import { MODEL_PICKER_SELECTION_KEY } from "@/lib/discover-labels";
import { apiGet, apiPatch, apiDelete } from "@/lib/api";
import { uploadKnowledgeFiles } from "@/lib/knowledge-upload";


type ChatMode = "standard" | "omni_realtime" | "synthetic_realtime";
type PipelineType =
  | "llm"
  | "asr"
  | "tts"
  | "vision"
  | "realtime"
  | "realtime_asr"
  | "realtime_tts";

interface ProjectData {
  id: string;
  name: string;
  description: string;
  default_chat_mode: ChatMode;
  created_at: string;
}

interface ConversationItem {
  id: string;
  title: string;
  updated_at: string;
}

interface PipelineConfigItem {
  id: string;
  project_id: string;
  model_type: PipelineType;
  model_id: string;
  config_json: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

interface PipelineResponse {
  items: PipelineConfigItem[];
}

interface DatasetInfo {
  id: string;
  name: string;
  type: string;
}

interface CatalogModelItem {
  id: string;
  model_id: string;
  display_name: string;
  provider: string;
  category: PipelineType;
  description: string;
  capabilities: string[];
}

interface KnowledgeItem {
  id: string;
  dataset_id: string;
  filename: string;
  media_type: string;
  size_bytes: number;
  download_url: string;
  preview_url?: string | null;
  created_at: string;
}

interface ParsedMeta {
  model: string;
  modelTier: string;
  personality: string;
  tags: string[];
  color: string;
  greeting: string;
  plainDescription: string;
}

interface SettingsFormState {
  name: string;
  color: string;
  greeting: string;
  personality: {
    description: string;
    tags: string[];
  };
}

const ACCEPTED_KNOWLEDGE_EXTENSIONS = [".pdf", ".txt", ".docx", ".md"];
const ACCEPTED_KNOWLEDGE_MIME = [
  "application/pdf",
  "text/plain",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  "text/markdown",
];
const DEFAULT_REALTIME_MODEL_ID = "qwen3-omni-flash-realtime";
const DEFAULT_REALTIME_ASR_MODEL_ID = "qwen3-asr-flash-realtime";
const DEFAULT_REALTIME_TTS_MODEL_ID = "qwen3-tts-flash-realtime";

interface PendingModelSelection {
  from: string;
  category: PipelineType;
  modelId: string;
  displayName: string;
}

function parseDescription(description: string): ParsedMeta {
  const meta: ParsedMeta = {
    model: "",
    modelTier: "",
    personality: "",
    tags: [],
    color: "accent",
    greeting: "",
    plainDescription: "",
  };

  if (!description) return meta;

  const modelMatch = description.match(/\[model:([^|]*)\|([^\]]*)\]/);
  if (modelMatch) {
    meta.model = modelMatch[1];
    meta.modelTier = modelMatch[2];
  }

  const personalityMatch = description.match(/\[personality:([\s\S]*?)\]/);
  if (personalityMatch) {
    meta.personality = personalityMatch[1];
  }

  const tagsMatch = description.match(/\[tags:([^\]]*)\]/);
  if (tagsMatch) {
    meta.tags = tagsMatch[1].split(",").filter(Boolean);
  }

  const colorMatch = description.match(/\[color:([^\]]*)\]/);
  if (colorMatch) {
    meta.color = colorMatch[1];
  }

  const greetingMatch = description.match(/\[greeting:([\s\S]*?)\]/);
  if (greetingMatch) {
    meta.greeting = greetingMatch[1];
  }

  meta.plainDescription = description
    .replace(/\[model:[^\]]*\]/g, "")
    .replace(/\[personality:[\s\S]*?\]/g, "")
    .replace(/\[tags:[^\]]*\]/g, "")
    .replace(/\[color:[^\]]*\]/g, "")
    .replace(/\[greeting:[\s\S]*?\]/g, "")
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)
    .join("\n");

  return meta;
}

function buildDescription(meta: ParsedMeta): string {
  const parts: string[] = [];

  if (meta.model) {
    parts.push(`[model:${meta.model}|${meta.modelTier || "custom"}]`);
  }
  if (meta.personality) {
    parts.push(`[personality:${meta.personality}]`);
  }
  if (meta.tags.length > 0) {
    parts.push(`[tags:${meta.tags.join(",")}]`);
  }
  if (meta.color) {
    parts.push(`[color:${meta.color}]`);
  }
  if (meta.greeting) {
    parts.push(`[greeting:${meta.greeting}]`);
  }
  if (meta.plainDescription) {
    parts.push(meta.plainDescription);
  }

  return parts.join("\n");
}

function formatModelName(modelId: string): string {
  const map: Record<string, string> = {
    "qwen3.5-plus": "Qwen 3.5 Plus",
    "qwen3-omni-flash-realtime": "Qwen3-Omni-Flash-Realtime",
    "qwen3-asr-flash": "Qwen3-ASR-Flash",
    "qwen3-asr-flash-realtime": "Qwen3-ASR-Flash-Realtime",
    "qwen3-tts-flash": "Qwen3-TTS-Flash",
    "qwen3-tts-flash-realtime": "Qwen3-TTS-Flash-Realtime",
    "qwen3-vl-plus": "Qwen3-VL-Plus",
    "qwen-plus": "Qwen Plus",
    "qwen-max": "Qwen Max",
    "qwen-turbo": "Qwen Turbo",
    "qwen-vl-plus": "Qwen VL Plus",
    "qwen-vl-max": "Qwen VL Max",
    "paraformer-v2": "Paraformer-v2",
    "cosyvoice-v1": "CosyVoice-v1",
    cosyvoice: "CosyVoice",
  };
  return map[modelId] || modelId || "Qwen 3.5 Plus";
}

function formatDate(iso: string): string {
  if (!iso) return "---";
  const d = new Date(iso);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function isAcceptedKnowledgeFile(file: File): boolean {
  const extension = file.name.substring(file.name.lastIndexOf(".")).toLowerCase();
  return ACCEPTED_KNOWLEDGE_EXTENSIONS.includes(extension) || ACCEPTED_KNOWLEDGE_MIME.includes(file.type);
}

const COLOR_MAP: Record<string, string> = {
  accent: "#c8734a",
  blue: "#3b82f6",
  green: "#22c55e",
  purple: "#a855f7",
  pink: "#ec4899",
  orange: "#f97316",
  red: "#ef4444",
};

function getColorValue(color: string): string {
  return COLOR_MAP[color] || color || "#c8734a";
}

function getPipelineModelId(items: PipelineConfigItem[], modelType: PipelineType, fallback: string): string {
  return items.find((item) => item.model_type === modelType)?.model_id || fallback;
}

function sortKnowledgeItems(items: KnowledgeItem[]): KnowledgeItem[] {
  return [...items].sort((a, b) => {
    const timeA = new Date(a.created_at).getTime();
    const timeB = new Date(b.created_at).getTime();
    return timeB - timeA;
  });
}

function modelSupportsVision(model?: CatalogModelItem | null): boolean {
  if (!model) {
    return false;
  }
  const capabilities = new Set((model.capabilities || []).map((cap) => cap.toLowerCase()));
  return capabilities.has("vision") || capabilities.has("image") || capabilities.has("ocr") || capabilities.has("video");
}

function modelHasCapabilities(model: CatalogModelItem | undefined, ...required: string[]): boolean {
  if (!model) {
    return false;
  }
  const capabilities = new Set((model.capabilities || []).map((cap) => cap.toLowerCase()));
  return required.every((capability) => capabilities.has(capability.toLowerCase()));
}

function SettingsDialog({
  initialState,
  saving,
  errorMessage,
  onOpenChange,
  onSave,
}: {
  initialState: SettingsFormState;
  saving: boolean;
  errorMessage: string;
  onOpenChange: (open: boolean) => void;
  onSave: (state: SettingsFormState) => Promise<void>;
}) {
  const t = useTranslations("console-assistants");
  const [state, setState] = useState<SettingsFormState>(initialState);

  return (
    <Dialog open onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] max-w-[980px] overflow-y-auto border-[var(--border)] bg-[var(--bg-card)]">
        <DialogHeader>
          <DialogTitle>{t("profile.settings")}</DialogTitle>
        </DialogHeader>

        <div className="space-y-8">
          <StepIdentity
            name={state.name}
            color={state.color}
            greeting={state.greeting}
            onNameChange={(name) => setState((current) => ({ ...current, name }))}
            onColorChange={(color) => setState((current) => ({ ...current, color }))}
            onGreetingChange={(greeting) => setState((current) => ({ ...current, greeting }))}
          />

          <StepPersonality
            personality={state.personality}
            onPersonalityChange={(personality) => setState((current) => ({ ...current, personality }))}
          />

          {errorMessage ? (
            <div className="console-inline-notice is-error">{errorMessage}</div>
          ) : null}
        </div>

        <DialogFooter>
          <button
            type="button"
            className="console-button-secondary"
            onClick={() => onOpenChange(false)}
            disabled={saving}
          >
            {t("graph.cancel")}
          </button>
          <button
            type="button"
            className="console-button"
            onClick={() => void onSave(state)}
            disabled={saving || !state.name.trim()}
          >
            {saving ? t("wizard.submitting") : t("graph.save")}
          </button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function KnowledgeDialog({
  loading,
  uploading,
  errorMessage,
  items,
  onOpenChange,
  onUpload,
}: {
  loading: boolean;
  uploading: boolean;
  errorMessage: string;
  items: KnowledgeItem[];
  onOpenChange: (open: boolean) => void;
  onUpload: (files: File[]) => Promise<void>;
}) {
  const t = useTranslations("console-assistants");
  const [selectedFiles, setSelectedFiles] = useState<File[]>([]);
  const [selectionError, setSelectionError] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  const addFiles = useCallback((incoming: FileList | File[]) => {
    const accepted: File[] = [];
    let rejected = false;

    for (const file of Array.from(incoming)) {
      if (isAcceptedKnowledgeFile(file)) {
        accepted.push(file);
      } else {
        rejected = true;
      }
    }

    setSelectedFiles((current) => [...current, ...accepted]);
    setSelectionError(rejected ? t("wizard.uploadHint") : "");
  }, [t]);

  return (
    <Dialog open onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] max-w-[860px] overflow-y-auto border-[var(--border)] bg-[var(--bg-card)]">
        <DialogHeader>
          <DialogTitle>{t("profile.card.knowledge")}</DialogTitle>
        </DialogHeader>

        <div className="space-y-6">
          <div>
            <div className="wizard-step-title">{t("wizard.stepKnowledge")}</div>
            <div className="wizard-step-desc">{t("wizard.stepKnowledgeDesc")}</div>
          </div>

          <div
            className="wizard-upload-area"
            onClick={() => inputRef.current?.click()}
            onDragOver={(event) => {
              event.preventDefault();
            }}
            onDrop={(event) => {
              event.preventDefault();
              if (uploading) return;
              if (event.dataTransfer.files.length > 0) {
                addFiles(event.dataTransfer.files);
              }
            }}
            role="button"
            tabIndex={0}
            onKeyDown={(event) => {
              if ((event.key === "Enter" || event.key === " ") && !uploading) {
                inputRef.current?.click();
              }
            }}
          >
            <input
              ref={inputRef}
              type="file"
              multiple
              accept={ACCEPTED_KNOWLEDGE_EXTENSIONS.join(",")}
              className="hidden"
              disabled={uploading}
              onChange={(event) => {
                if (event.target.files) {
                  addFiles(event.target.files);
                }
                event.target.value = "";
              }}
            />
            <div className="wizard-upload-icon">
              <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                <polyline points="17 8 12 3 7 8" />
                <line x1="12" y1="3" x2="12" y2="15" />
              </svg>
            </div>
            <p className="wizard-upload-text">{t("wizard.uploadText")}</p>
            <p className="wizard-upload-hint">{t("wizard.uploadHint")}</p>
          </div>

          {selectedFiles.length > 0 ? (
            <ul className="wizard-file-list">
              {selectedFiles.map((file, index) => (
                <li key={`${file.name}-${index}`} className="wizard-file-item">
                  <span className="wizard-file-name">{file.name}</span>
                  <span className="wizard-file-size">{formatFileSize(file.size)}</span>
                  <button
                    type="button"
                    className="wizard-file-remove"
                    onClick={() => {
                      setSelectedFiles((current) => current.filter((_, currentIndex) => currentIndex !== index));
                    }}
                    aria-label={`Remove ${file.name}`}
                  >
                    &times;
                  </button>
                </li>
              ))}
            </ul>
          ) : null}

          <div className="space-y-3">
            <div className="text-sm font-semibold text-[var(--text-primary)]">
              {t("profile.card.knowledge")}
            </div>
            {loading ? (
              <div className="text-sm text-[var(--text-secondary)]">{t("versions.loading")}</div>
            ) : items.length === 0 ? (
              <div className="text-sm text-[var(--text-secondary)]">{t("profile.noFiles")}</div>
            ) : (
              <div className="space-y-2">
                {items.map((item) => (
                  <a
                    key={item.id}
                    href={item.download_url}
                    target="_blank"
                    rel="noreferrer"
                    className="flex items-center justify-between rounded-[18px] border border-[var(--border)] bg-[var(--bg-base)] px-4 py-3 no-underline transition-colors hover:border-[var(--accent)]"
                  >
                    <div className="min-w-0">
                      <div className="truncate text-sm font-medium text-[var(--text-primary)]">{item.filename}</div>
                      <div className="text-xs text-[var(--text-secondary)]">{formatFileSize(item.size_bytes)}</div>
                    </div>
                    <span className="text-xs font-medium text-[var(--accent)]">{t("graph.viewDetail")}</span>
                  </a>
                ))}
              </div>
            )}
          </div>

          {selectionError ? (
            <div className="console-inline-notice is-error">{selectionError}</div>
          ) : null}
          {errorMessage ? (
            <div className="console-inline-notice is-error">{errorMessage}</div>
          ) : null}
        </div>

        <DialogFooter>
          <button
            type="button"
            className="console-button-secondary"
            onClick={() => onOpenChange(false)}
            disabled={uploading}
          >
            {t("graph.cancel")}
          </button>
          <button
            type="button"
            className="console-button"
            onClick={() => void onUpload(selectedFiles)}
            disabled={uploading || selectedFiles.length === 0}
          >
            {uploading ? t("wizard.submitting") : t("canvas.save")}
          </button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export default function AssistantDetailPage() {
  const params = useParams<{ id: string }>();
  const projectId = Array.isArray(params.id) ? params.id[0] : params.id;
  const t = useTranslations("console-assistants");
  const router = useRouter();

  /* activeTab and modelsExpanded removed — single-page layout shows everything */
  const [project, setProject] = useState<ProjectData | null>(null);
  const [conversations, setConversations] = useState<ConversationItem[]>([]);
  const [pipelineItems, setPipelineItems] = useState<PipelineConfigItem[]>([]);
  const [catalogModels, setCatalogModels] = useState<CatalogModelItem[]>([]);
  const [knowledgeItems, setKnowledgeItems] = useState<KnowledgeItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [knowledgeLoading, setKnowledgeLoading] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [knowledgeOpen, setKnowledgeOpen] = useState(false);
  const [settingsSaving, setSettingsSaving] = useState(false);
  const [knowledgeUploading, setKnowledgeUploading] = useState(false);
  const [modeSaving, setModeSaving] = useState(false);
  const [settingsError, setSettingsError] = useState("");
  const [knowledgeError, setKnowledgeError] = useState("");
  const [pageError, setPageError] = useState("");
  const [pickerCategory, setPickerCategory] = useState<PipelineType | null>(null);

  const loadKnowledgeItems = useCallback(async () => {
    if (!projectId) {
      setKnowledgeItems([]);
      return;
    }

    setKnowledgeLoading(true);
    try {
      const datasets = await apiGet<DatasetInfo[]>(`/api/v1/datasets?project_id=${projectId}`).catch(() => []);
      if (datasets.length === 0) {
        setKnowledgeItems([]);
        return;
      }

      const itemResults = await Promise.allSettled(
        datasets.map((dataset) => apiGet<KnowledgeItem[]>(`/api/v1/datasets/${dataset.id}/items`)),
      );
      const items = itemResults.flatMap((result) => (result.status === "fulfilled" ? result.value : []));
      setKnowledgeItems(sortKnowledgeItems(items));
    } catch {
      setKnowledgeItems([]);
    } finally {
      setKnowledgeLoading(false);
    }
  }, [projectId]);

  const loadData = useCallback(async (showLoading = false) => {
    if (!projectId) {
      setProject(null);
      setConversations([]);
      setPipelineItems([]);
      setKnowledgeItems([]);
      setLoading(false);
      return;
    }

    if (showLoading) {
      setLoading(true);
    }

    const [projectResult, conversationResult, pipelineResult, catalogResult] = await Promise.allSettled([
      apiGet<ProjectData>(`/api/v1/projects/${projectId}`),
      apiGet<ConversationItem[]>(`/api/v1/chat/conversations?project_id=${projectId}`),
      apiGet<PipelineResponse>(`/api/v1/pipeline?project_id=${projectId}`),
      apiGet<CatalogModelItem[]>("/api/v1/models/catalog"),
    ]);

    if (projectResult.status === "fulfilled") {
      setProject(projectResult.value);
      setPageError("");
    } else {
      setProject(null);
      setPageError(projectResult.reason instanceof Error ? projectResult.reason.message : "");
    }

    setConversations(
      conversationResult.status === "fulfilled" && Array.isArray(conversationResult.value)
        ? conversationResult.value
        : [],
    );
    setPipelineItems(
      pipelineResult.status === "fulfilled" && Array.isArray(pipelineResult.value.items)
        ? pipelineResult.value.items
        : [],
    );
    setCatalogModels(
      catalogResult.status === "fulfilled" && Array.isArray(catalogResult.value)
        ? catalogResult.value
        : [],
    );

    await loadKnowledgeItems();

    if (showLoading) {
      setLoading(false);
    }
  }, [loadKnowledgeItems, projectId]);

  useEffect(() => {
    void loadData(true);
  }, [loadData]);

  const meta = useMemo(() => parseDescription(project?.description || ""), [project?.description]);
  const colorVal = getColorValue(meta.color);
  const conversationCount = conversations.length;
  const personalityExcerpt = meta.personality
    ? meta.personality.length > 100
      ? `${meta.personality.slice(0, 100)}...`
      : meta.personality
    : "";
  const settingsInitialState = useMemo<SettingsFormState>(() => ({
    name: project?.name || "",
    color: meta.color,
    greeting: meta.greeting,
    personality: {
      description: meta.personality,
      tags: meta.tags,
    },
  }), [meta.color, meta.greeting, meta.personality, meta.tags, project?.name]);

  const llmModelId = getPipelineModelId(pipelineItems, "llm", meta.model || "qwen3.5-plus");
  const visionModelId = getPipelineModelId(pipelineItems, "vision", "qwen-vl-plus");
  const asrModelId = getPipelineModelId(pipelineItems, "asr", "paraformer-v2");
  const ttsModelId = getPipelineModelId(pipelineItems, "tts", "cosyvoice-v1");
  const realtimeModelId = getPipelineModelId(pipelineItems, "realtime", DEFAULT_REALTIME_MODEL_ID);
  const realtimeAsrModelId = getPipelineModelId(
    pipelineItems,
    "realtime_asr",
    DEFAULT_REALTIME_ASR_MODEL_ID,
  );
  const realtimeTtsModelId = getPipelineModelId(
    pipelineItems,
    "realtime_tts",
    DEFAULT_REALTIME_TTS_MODEL_ID,
  );
  const catalogModelsById = useMemo(
    () => new Map(catalogModels.map((item) => [item.model_id, item])),
    [catalogModels],
  );
  const llmCatalogModel = catalogModelsById.get(llmModelId);
  const llmSupportsBuiltInVision = modelSupportsVision(llmCatalogModel);
  const llmSupportsAudioInput = modelHasCapabilities(llmCatalogModel, "audio_input");
  const llmSupportsAudioOutput = modelHasCapabilities(llmCatalogModel, "audio_output");
  const llmSupportsVideoInput = modelHasCapabilities(llmCatalogModel, "video");
  const displayModelName = (modelId: string) => {
    const formatted = formatModelName(modelId);
    if (formatted && formatted !== modelId) {
      return formatted;
    }
    return catalogModelsById.get(modelId)?.display_name || formatted;
  };

  const modeOptions: {
    key: ChatMode;
    title: string;
    description: string;
    disabled?: boolean;
    helperText?: string;
  }[] = [
    {
      key: "standard",
      title: t("profile.mode.standard"),
      description: t("profile.mode.standardDesc"),
    },
    {
      key: "omni_realtime",
      title: t("profile.mode.omni"),
      description: t("profile.mode.omniDesc"),
    },
    {
      key: "synthetic_realtime",
      title: t("profile.mode.synthetic"),
      description: t("profile.mode.syntheticDesc"),
      disabled: !llmSupportsBuiltInVision,
      helperText: !llmSupportsBuiltInVision
        ? t("profile.mode.syntheticRequiresVision", {
            model: displayModelName(llmModelId),
          })
        : llmSupportsVideoInput
          ? t("profile.mode.syntheticSupportsVideo", {
              model: displayModelName(llmModelId),
            })
          : t("profile.mode.syntheticImageOnly", {
              model: displayModelName(llmModelId),
            }),
    },
  ];

  const modelRows: {
    key: PipelineType | "realtime";
    changeTargetType?: PipelineType;
    shortLabel: string;
    label: string;
    modelId: string;
    helperText?: string;
    changeable: boolean;
    statusLabel?: string;
  }[] = [
    {
      key: "llm",
      changeTargetType: "llm",
      shortLabel: t("profile.model.llmShort"),
      label: t("profile.model.llm"),
      modelId: llmModelId,
      changeable: true,
    },
    {
      key: "vision",
      changeTargetType: "vision",
      shortLabel: t("profile.model.visionShort"),
      label: t("profile.model.vision"),
      modelId: llmSupportsBuiltInVision ? llmModelId : visionModelId,
      helperText: llmSupportsBuiltInVision
        ? t("profile.model.visionCoveredByLlm", { model: displayModelName(llmModelId) })
        : t("profile.model.visionSelected", { model: displayModelName(visionModelId) }),
      changeable: !llmSupportsBuiltInVision,
      statusLabel: llmSupportsBuiltInVision ? t("profile.model.followChatModel") : undefined,
    },
    {
      key: "asr",
      changeTargetType: "asr",
      shortLabel: t("profile.model.asrShort"),
      label: t("profile.model.asr"),
      modelId: llmSupportsAudioInput ? llmModelId : asrModelId,
      helperText: llmSupportsAudioInput
        ? t("profile.model.audioInputCoveredByLlm", { model: displayModelName(llmModelId) })
        : undefined,
      changeable: !llmSupportsAudioInput,
      statusLabel: llmSupportsAudioInput ? t("profile.model.followChatModel") : undefined,
    },
    {
      key: "tts",
      changeTargetType: "tts",
      shortLabel: t("profile.model.ttsShort"),
      label: t("profile.model.tts"),
      modelId: llmSupportsAudioOutput ? llmModelId : ttsModelId,
      helperText: llmSupportsAudioOutput
        ? t("profile.model.audioOutputCoveredByLlm", { model: displayModelName(llmModelId) })
        : undefined,
      changeable: !llmSupportsAudioOutput,
      statusLabel: llmSupportsAudioOutput ? t("profile.model.followChatModel") : undefined,
    },
    {
      key: "realtime",
      changeTargetType: "realtime",
      shortLabel: t("profile.model.realtimeShort"),
      label: t("profile.model.realtime"),
      modelId: realtimeModelId,
      helperText: t("profile.model.realtimeSelected", { model: displayModelName(realtimeModelId) }),
      changeable: true,
    },
    {
      key: "realtime_asr",
      changeTargetType: "realtime_asr",
      shortLabel: t("profile.model.realtimeAsrShort"),
      label: t("profile.model.realtimeAsr"),
      modelId: realtimeAsrModelId,
      helperText: t("profile.model.realtimeAsrSelected", {
        model: displayModelName(realtimeAsrModelId),
      }),
      changeable: true,
    },
    {
      key: "realtime_tts",
      changeTargetType: "realtime_tts",
      shortLabel: t("profile.model.realtimeTtsShort"),
      label: t("profile.model.realtimeTts"),
      modelId: realtimeTtsModelId,
      helperText: t("profile.model.realtimeTtsSelected", {
        model: displayModelName(realtimeTtsModelId),
      }),
      changeable: true,
    },
  ];

  const standardModeRows = modelRows.filter((row) => ["llm", "vision", "asr", "tts"].includes(row.key));
  const omniModeRows = modelRows.filter((row) => row.key === "realtime");
  const syntheticModeRows = [
    {
      key: "synthetic-llm",
      changeTargetType: "llm" as PipelineType,
      shortLabel: t("profile.model.llmShort"),
      label: t("profile.model.syntheticLlm"),
      modelId: llmModelId,
      helperText: t("profile.model.syntheticLlmHelper", { model: displayModelName(llmModelId) }),
      changeable: true,
      statusLabel: llmSupportsBuiltInVision ? t("profile.model.syntheticVisionReady") : t("profile.model.syntheticVisionMissing"),
    },
    ...modelRows.filter((row) => row.key === "realtime_asr" || row.key === "realtime_tts"),
  ];

  const openKnowledgeManager = useCallback(() => {
    setKnowledgeError("");
    setKnowledgeOpen(true);
    void loadKnowledgeItems();
  }, [loadKnowledgeItems]);

  const saveSettings = useCallback(async (state: SettingsFormState) => {
    if (!projectId) return;

    setSettingsSaving(true);
    setSettingsError("");
    try {
      const nextProject = await apiPatch<ProjectData>(`/api/v1/projects/${projectId}`, {
        name: state.name.trim(),
        description: buildDescription({
          ...meta,
          model: llmModelId,
          modelTier: meta.modelTier || "custom",
          color: state.color,
          greeting: state.greeting,
          personality: state.personality.description,
          tags: state.personality.tags,
        }),
      });
      setProject(nextProject);
      setSettingsOpen(false);
    } catch (error) {
      setSettingsError(error instanceof Error ? error.message : "Save failed");
    } finally {
      setSettingsSaving(false);
    }
  }, [llmModelId, meta, projectId]);

  const handleDefaultChatModeSelect = useCallback(async (nextMode: ChatMode) => {
    if (!projectId || !project) {
      return;
    }
    if (nextMode === project.default_chat_mode) {
      return;
    }
    if (nextMode === "synthetic_realtime" && !llmSupportsBuiltInVision) {
      return;
    }

    setModeSaving(true);
    setPageError("");
    try {
      const nextProject = await apiPatch<ProjectData>(`/api/v1/projects/${projectId}`, {
        default_chat_mode: nextMode,
      });
      setProject(nextProject);

    } catch (error) {
      setPageError(error instanceof Error ? error.message : "Chat mode update failed");
    } finally {
      setModeSaving(false);
    }
  }, [llmSupportsBuiltInVision, project, projectId]);

  const handleModelSelect = useCallback(async (modelId: string, explicitCategory?: PipelineType | null) => {
    const targetCategory = explicitCategory ?? pickerCategory;
    if (!projectId || !targetCategory) return;

    setPageError("");
    try {
      await apiPatch("/api/v1/pipeline", {
        project_id: projectId,
        model_type: targetCategory,
        model_id: modelId,
        config_json: {},
      });

      if (targetCategory === "llm") {
        const selectedModel = catalogModelsById.get(modelId);
        const nextSupportsVision = selectedModel ? modelSupportsVision(selectedModel) : true;
        try {
          const updatedProject = await apiPatch<ProjectData>(`/api/v1/projects/${projectId}`, {
            description: buildDescription({
              ...meta,
              model: modelId,
              modelTier: meta.modelTier || "custom",
            }),
            default_chat_mode:
              project?.default_chat_mode === "synthetic_realtime" && !nextSupportsVision
                ? "standard"
                : project?.default_chat_mode,
          });
          setProject(updatedProject);
        } catch (error) {
          await loadData();
          setPageError(
            error instanceof Error
              ? `${t("profile.modelSyncFailed")} ${error.message}`
              : t("profile.modelSyncFailed"),
          );
          return;
        }
      }

      await loadData();
      setPickerCategory(null);

    } catch (error) {
      await loadData();
      setPageError(error instanceof Error ? error.message : "Model change failed");
    }
  }, [catalogModelsById, loadData, meta, pickerCategory, project?.default_chat_mode, projectId, t]);

  useEffect(() => {
    if (typeof window === "undefined" || !projectId || !project) {
      return;
    }

    const rawPending = window.sessionStorage.getItem(MODEL_PICKER_SELECTION_KEY);
    if (!rawPending) {
      return;
    }

    let pending: PendingModelSelection | null = null;
    try {
      pending = JSON.parse(rawPending) as PendingModelSelection;
    } catch {
      window.sessionStorage.removeItem(MODEL_PICKER_SELECTION_KEY);
      return;
    }

    if (!pending) {
      window.sessionStorage.removeItem(MODEL_PICKER_SELECTION_KEY);
      return;
    }

    const expectedPath = (pending.from || "").split("?")[0];
    if (!expectedPath || expectedPath !== window.location.pathname) {
      return;
    }

    window.sessionStorage.removeItem(MODEL_PICKER_SELECTION_KEY);
    void handleModelSelect(pending.modelId, pending.category);
  }, [handleModelSelect, project, projectId]);

  const handleKnowledgeUpload = useCallback(async (files: File[]) => {
    if (!projectId || files.length === 0) return;

    setKnowledgeUploading(true);
    setKnowledgeError("");
    try {
      await uploadKnowledgeFiles(projectId, files);
      await loadKnowledgeItems();
      setKnowledgeOpen(false);
    } catch (error) {
      setKnowledgeError(error instanceof Error ? error.message : "Upload failed");
    } finally {
      setKnowledgeUploading(false);
    }
  }, [loadKnowledgeItems, projectId]);

  if (loading) {
    return (
      <PageTransition>
        <div className="console-page-shell" style={{ padding: "28px 32px" }}>
          <div style={{ padding: "40px", textAlign: "center", color: "var(--console-text-secondary, var(--text-secondary))" }}>
            Loading...
          </div>
        </div>
      </PageTransition>
    );
  }

  const SLOT_COLOR_MAP: Record<string, string> = {
    llm: "var(--console-slot-brain, #6366f1)",
    asr: "var(--console-slot-asr, #22c55e)",
    tts: "var(--console-slot-tts, #f97316)",
    vision: "var(--console-slot-vision, #3b82f6)",
    realtime: "var(--console-slot-realtime, #a855f7)",
    realtime_asr: "var(--console-slot-realtime-asr, #06b6d4)",
    realtime_tts: "var(--console-slot-realtime-tts, #ec4899)",
  };

  return (
    <PageTransition>
      <div className="console-page-shell" style={{ padding: "24px 24px" }}>
        {/* Compact header bar */}
        <GlassCard className="assistant-detail-hero-compact">
          <div className="assistant-detail-compact-header">
            <div
              style={{
                width: 48,
                height: 48,
                borderRadius: "var(--console-radius-md, 12px)",
                background: `linear-gradient(135deg, ${colorVal}, color-mix(in srgb, ${colorVal} 70%, white))`,
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                flexShrink: 0,
              }}
            >
              <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                <path d="M12 8V4H8" />
                <rect x="8" y="8" width="8" height="8" rx="1" />
                <path d="M2 12h2M20 12h2M12 2v2M12 20v2" />
                <circle cx="12" cy="12" r="2" />
              </svg>
            </div>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <h1 style={{ fontSize: 18, fontWeight: 700, color: "var(--console-text-primary, var(--text-primary))", margin: 0, whiteSpace: "nowrap" }}>
                  {project?.name || "---"}
                </h1>
                <span style={{
                  fontSize: 10,
                  fontWeight: 600,
                  padding: "2px 8px",
                  borderRadius: 20,
                  background: "rgba(34,197,94,0.12)",
                  color: "#16a34a",
                  flexShrink: 0,
                }}>Active</span>
              </div>
              <p style={{ fontSize: 12, color: "var(--console-text-secondary, var(--text-secondary))", lineHeight: 1.4, margin: "2px 0 0", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                {personalityExcerpt || t("canvas.personalityUnset")}
              </p>
              <div className="assistant-detail-hero-stats">
                {t("profile.stat.conversations")}: {conversationCount} &middot; {t("profile.card.knowledge")}: {knowledgeItems.length} &middot; {t("graph.createdAt")}: {formatDate(project?.created_at || "")}
              </div>
            </div>
            <div className="assistant-detail-hero-actions assistant-profile-actions">
              <Link href={`/app/chat?project_id=${projectId}`} style={{ textDecoration: "none" }}>
                <GlassButton variant="primary">
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
                  </svg>
                  {t("profile.startChat")}
                </GlassButton>
              </Link>
              <GlassButton
                variant="secondary"
                onClick={() => {
                  setSettingsError("");
                  setSettingsOpen(true);
                }}
              >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <circle cx="12" cy="12" r="3" />
                  <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
                </svg>
                {t("profile.settings")}
              </GlassButton>
              <GlassButton
                variant="ghost"
                onClick={async () => {
                  if (!window.confirm(t("profile.deleteConfirm"))) return;
                  try {
                    await apiDelete(`/api/v1/projects/${projectId}`);
                    router.push("/app/assistants");
                  } catch {
                    // stay on page if delete fails
                  }
                }}
                style={{ color: "#ef4444" }}
              >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <polyline points="3 6 5 6 21 6" />
                  <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
                </svg>
                {t("profile.delete")}
              </GlassButton>
            </div>
          </div>
        </GlassCard>

        {pageError ? (
          <div className="console-inline-notice is-error" style={{ marginTop: 16 }}>
            {pageError}
          </div>
        ) : null}

        {/* Two-column body: info | models */}
        <div className="assistant-detail-grid-2col" style={{ marginTop: 16 }}>
          {/* Left column: Personality + Knowledge combined */}
          <div className="assistant-detail-combined-card">
            {/* Personality section */}
            <div style={{ padding: 16 }}>
              <div className="assistant-detail-section-header">
                <h3 className="assistant-detail-section-title">{t("profile.card.personality")}</h3>
                <button type="button" className="assistant-detail-action-link" onClick={() => { setSettingsError(""); setSettingsOpen(true); }}>
                  {t("profile.edit")}
                </button>
              </div>
              <div style={{ marginTop: 8 }}>
                <div style={{ fontSize: 11, fontWeight: 600, color: "var(--console-accent, #6366f1)", textTransform: "uppercase", letterSpacing: "0.5px", marginBottom: 6 }}>
                  {meta.tags.length > 0 ? meta.tags.join(", ") : t("profile.customPersonality")}
                </div>
                <div style={{ fontSize: 13, color: "var(--console-text-secondary, var(--text-secondary))", lineHeight: 1.6, whiteSpace: "pre-wrap" }}>
                  {meta.personality || t("canvas.personalityUnset")}
                </div>
              </div>
            </div>

            <div className="assistant-detail-combined-divider" />

            {/* Knowledge section */}
            <div style={{ padding: 16 }}>
              <div className="assistant-detail-section-header">
                <h3 className="assistant-detail-section-title">{t("profile.card.knowledge")}</h3>
                <button type="button" className="assistant-detail-action-link" onClick={openKnowledgeManager}>
                  {t("profile.manage")}
                </button>
              </div>
              <div style={{ marginTop: 8 }}>
                {knowledgeItems.length === 0 ? (
                  <div style={{ fontSize: 13, color: "var(--console-text-secondary, var(--text-secondary))", textAlign: "center", padding: "12px 0" }}>
                    {t("profile.noFiles")}
                  </div>
                ) : (
                  <div className="assistant-knowledge-list">
                    {knowledgeItems.slice(0, 5).map((item) => (
                      <a key={item.id} href={item.download_url} target="_blank" rel="noreferrer" className="assistant-knowledge-item">
                        <span className="assistant-knowledge-name">{item.filename}</span>
                        <span className="assistant-knowledge-size">{formatFileSize(item.size_bytes)}</span>
                      </a>
                    ))}
                  </div>
                )}
              </div>
            </div>
          </div>

          {/* Right column: Model configuration with segmented mode tabs */}
          <GlassCard>
            <div className="assistant-detail-section-header" style={{ marginBottom: 12 }}>
              <h3 className="assistant-detail-section-title">{t("profile.card.models")}</h3>
              {modeSaving ? <span style={{ fontSize: 11, color: "var(--console-text-faint)" }}>{t("wizard.submitting")}</span> : null}
            </div>

            {/* Segmented mode switcher */}
            <div style={{ display: "flex", background: "rgba(0,0,0,0.04)", borderRadius: 10, padding: 3, marginBottom: 16, gap: 2 }}>
              {modeOptions.map((option) => (
                <button
                  key={option.key}
                  type="button"
                  disabled={modeSaving || option.disabled}
                  onClick={() => void handleDefaultChatModeSelect(option.key)}
                  style={{
                    flex: 1,
                    padding: "7px 8px",
                    borderRadius: 8,
                    border: "none",
                    fontSize: 11,
                    fontWeight: project?.default_chat_mode === option.key ? 600 : 400,
                    color: project?.default_chat_mode === option.key ? "var(--console-accent, #6366f1)" : "var(--console-text-muted, #6b7280)",
                    background: project?.default_chat_mode === option.key ? "rgba(255,255,255,0.85)" : "transparent",
                    boxShadow: project?.default_chat_mode === option.key ? "0 1px 3px rgba(0,0,0,0.08)" : "none",
                    cursor: option.disabled ? "not-allowed" : "pointer",
                    opacity: option.disabled ? 0.5 : 1,
                    transition: "all 150ms",
                  }}
                >
                  {option.title}
                </button>
              ))}
            </div>

            {/* Current mode's model rows */}
            {(project?.default_chat_mode === "omni_realtime"
              ? omniModeRows
              : project?.default_chat_mode === "synthetic_realtime"
                ? syntheticModeRows
                : standardModeRows
            ).map((row) => (
              <div
                key={row.key}
                className="profile-model-row assistant-model-row"
                data-testid={`assistant-model-row-${row.key}`}
              >
                <span className="dashboard-glass-slot-dot" style={{ background: SLOT_COLOR_MAP[row.key] || "#6366f1" }} />
                <div className="profile-model-info">
                  <div className="profile-model-label">{row.shortLabel || row.label}</div>
                  <div className="profile-model-name-row">
                    <div className="profile-model-name">{displayModelName(row.modelId)}</div>
                    {!row.changeable && row.statusLabel ? <span className="profile-model-badge">{row.statusLabel}</span> : null}
                  </div>
                  {row.helperText ? <div className="profile-model-helper">{row.helperText}</div> : null}
                </div>
                {row.changeable ? (
                  <button type="button" className="assistant-detail-action-link" data-testid={`assistant-model-change-${row.key}`} onClick={() => setPickerCategory(row.changeTargetType || null)}>
                    {t("profile.change")}
                  </button>
                ) : null}
              </div>
            ))}
          </GlassCard>

        </div>

        {settingsOpen ? (
          <SettingsDialog
            initialState={settingsInitialState}
            saving={settingsSaving}
            errorMessage={settingsError}
            onOpenChange={setSettingsOpen}
            onSave={saveSettings}
          />
        ) : null}

        {knowledgeOpen ? (
          <KnowledgeDialog
            loading={knowledgeLoading}
            uploading={knowledgeUploading}
            errorMessage={knowledgeError}
            items={knowledgeItems}
            onOpenChange={setKnowledgeOpen}
            onUpload={handleKnowledgeUpload}
          />
        ) : null}

        <ModelPickerModal
          open={pickerCategory !== null}
          category={pickerCategory || "llm"}
          currentModelId={
            pickerCategory
              ? getPipelineModelId(
                  pipelineItems,
                  pickerCategory,
                  pickerCategory === "vision"
                    ? "qwen-vl-plus"
                    : pickerCategory === "tts"
                      ? "cosyvoice-v1"
                      : pickerCategory === "asr"
                        ? "paraformer-v2"
                        : pickerCategory === "realtime"
                          ? DEFAULT_REALTIME_MODEL_ID
                          : pickerCategory === "realtime_asr"
                            ? DEFAULT_REALTIME_ASR_MODEL_ID
                            : pickerCategory === "realtime_tts"
                              ? DEFAULT_REALTIME_TTS_MODEL_ID
                          : "qwen3.5-plus",
                )
              : undefined
          }
          onClose={() => setPickerCategory(null)}
          onSelect={(modelId) => {
            void handleModelSelect(modelId, pickerCategory);
          }}
        />
      </div>
    </PageTransition>
  );
}
