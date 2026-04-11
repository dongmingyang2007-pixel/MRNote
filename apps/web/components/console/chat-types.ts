// Backend already normalises assistant content; no client-side normalisation needed for persisted messages.

export type ChatMode = "standard" | "omni_realtime" | "synthetic_realtime";

export interface SearchSource {
  index: number;
  title: string;
  url: string;
  domain: string;
  site_name?: string | null;
  summary?: string | null;
  icon?: string | null;
  tool_type?: string | null;
  image_url?: string | null;
  thumbnail_url?: string | null;
}

export interface ExtractedFact {
  fact: string;
  category: string;
  importance: number;
  status?: string | null;
  triage_action?: string | null;
  triage_reason?: string | null;
  target_memory_id?: string | null;
}

export interface MemoryWritePreviewItem {
  id: string;
  fact: string;
  category: string;
  importance: number;
  triage_action?: string | null;
  triage_reason?: string | null;
  status?: string | null;
  target_memory_id?: string | null;
  memory_type?: "permanent" | "temporary" | null;
  evidence_count?: number;
}

export interface MemoryWritePreview {
  summary?: string | null;
  item_count?: number | null;
  written_count?: number | null;
  discarded_count?: number | null;
  items: MemoryWritePreviewItem[];
}

export interface RetrievalTraceMemory {
  id: string;
  type?: string;
  category?: string;
  memory_kind?: string | null;
  node_status?: string | null;
  source?: string | null;
  score?: number | null;
  semantic_score?: number | null;
  pinned?: boolean;
  salience?: number | null;
  content: string;
  selection_reason?: string | null;
  why_selected?: string | null;
  suppression_reason?: string | null;
  outcome_weight?: number | null;
  episode_ids?: string[];
  supporting_quote?: string | null;
  supporting_file_excerpt?: string | null;
  supporting_memory_id?: string | null;
}

export interface RetrievalTraceViewHit {
  id: string;
  view_type?: string | null;
  source_subject_id?: string | null;
  score?: number | null;
  content: string;
  snippet?: string | null;
  selection_reason?: string | null;
  why_selected?: string | null;
  suppression_reason?: string | null;
  outcome_weight?: number | null;
  supporting_memory_id?: string | null;
  supporting_quote?: string | null;
}

export interface RetrievalTraceEvidenceHit {
  id: string;
  memory_id?: string | null;
  source_type?: string | null;
  conversation_id?: string | null;
  message_id?: string | null;
  episode_id?: string | null;
  chunk_id?: string | null;
  confidence?: number | null;
  score?: number | null;
  quote_text: string;
  snippet?: string | null;
  selection_reason?: string | null;
  why_selected?: string | null;
  supporting_memory_id?: string | null;
}

export interface RetrievalTraceChunk {
  id?: string | null;
  data_item_id?: string | null;
  filename?: string | null;
  memory_ids?: string[];
  score?: number | null;
  chunk_text: string;
  why_selected?: string | null;
}

export interface RetrievalTraceLayerHits {
  profile?: number;
  durable_facts?: number;
  playbooks?: number;
  episodic_timeline?: number;
  raw_evidence?: number;
}

export type RetrievalContextLevel =
  | "none"
  | "profile_only"
  | "memory_only"
  | "full_rag";

export interface RetrievalTrace {
  strategy?: string | null;
  context_level?: RetrievalContextLevel | null;
  decision_source?: string | null;
  decision_reason?: string | null;
  decision_confidence?: number | null;
  layer_hits?: RetrievalTraceLayerHits;
  view_hits?: RetrievalTraceViewHit[];
  evidence_hits?: RetrievalTraceEvidenceHit[];
  rerank_latency_ms?: number | null;
  policy_flags?: string[];
  suppressed_memory_ids?: string[];
  used_playbook_ids?: string[];
  conflicted_memory_ids?: string[];
  episode_ids?: string[];
  memory_counts?: {
    static?: number;
    relevant?: number;
    graph?: number;
    temporary?: number;
  };
  selected_memories?: RetrievalTraceMemory[];
  memories: RetrievalTraceMemory[];
  knowledge_chunks: RetrievalTraceChunk[];
  linked_file_chunks: RetrievalTraceChunk[];
}

export interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  reasoningContent?: string | null;
  sources?: SearchSource[];
  retrievalTrace?: RetrievalTrace | null;
  audioBase64?: string | null;
  memories_extracted?: string;
  memory_write_preview?: MemoryWritePreview | null;
  extracted_facts?: ExtractedFact[];
  memory_extraction_status?: string | null;
  memory_extraction_attempts?: number | null;
  memory_extraction_error?: string | null;
  metadataJson?: Record<string, unknown> | null;
  animateOnMount?: boolean;
  isStreaming?: boolean;
}

export interface ApiMessage {
  id: string;
  conversation_id?: string;
  role: "user" | "assistant";
  content: string;
  reasoning_content?: string | null;
  metadata_json?: Record<string, unknown> | null;
  created_at?: string;
}

export type InspectorTab = "context" | "memory_write" | "thinking" | "debug";

export type InspectorSection =
  | "sources"
  | "profile"
  | "recent"
  | "knowledge"
  | "files"
  | "raw"
  | null;

export interface InspectorState {
  open: boolean;
  tab: InspectorTab;
  messageId: string | null;
  section?: InspectorSection;
}

export interface MessageInspectorOverride {
  targetMemoryId: string;
  fact?: string;
  hidden?: boolean;
  status?: string | null;
  memoryType?: "permanent" | "temporary" | null;
}

export interface RetrievalSummaryView {
  contextLevel: RetrievalContextLevel | null;
  memoryCount: number;
  materialCount: number;
  label: string | null;
}

export interface MemoryWriteSummaryItem {
  id: string;
  fact: string;
  category: string;
  importance: number;
  triageAction: string | null;
  triageReason: string | null;
  status: string | null;
  targetMemoryId: string | null;
  memoryType: "permanent" | "temporary" | null;
  badgeKey: "long_term" | "temporary" | "merged" | "not_written";
  isActionable: boolean;
  evidenceCount?: number;
}

export interface MemoryWriteSummaryView {
  count: number;
  label: string | null;
  items: MemoryWriteSummaryItem[];
}

export interface ThinkingSummaryView {
  label: string | null;
  content: string | null;
}

export interface ChatMetaRailItem {
  key: "sources" | "context" | "memory_write" | "thinking";
  label: string;
  tab: InspectorTab;
  section?: InspectorSection;
  count?: number;
}

export interface MemoryWriteRunDetail {
  id: string;
  status?: string | null;
  extraction_model?: string | null;
  consolidation_model?: string | null;
  error?: string | null;
  started_at?: string | null;
  completed_at?: string | null;
  created_at?: string | null;
  metadata_json?: Record<string, unknown>;
}

export interface MemoryWriteItemDetail {
  id: string;
  subject_memory_id?: string | null;
  candidate_text: string;
  category: string;
  proposed_memory_kind?: string | null;
  importance: number;
  decision?: string | null;
  target_memory_id?: string | null;
  predecessor_memory_id?: string | null;
  reason?: string | null;
  metadata_json?: Record<string, unknown>;
  created_at?: string | null;
}

export interface MessageMemoryWriteDetail {
  run: MemoryWriteRunDetail | null;
  items: MemoryWriteItemDetail[];
}

function normalizeExtractedFacts(value: unknown): ExtractedFact[] | undefined {
  if (!Array.isArray(value)) {
    return undefined;
  }

  const facts = value
    .filter(
      (f: unknown): f is Record<string, unknown> =>
        typeof f === "object" && f !== null,
    )
    .map((f) => ({
      fact: String(f.fact ?? ""),
      category: String(f.category ?? ""),
      importance: typeof f.importance === "number" ? f.importance : 0,
      status:
        typeof f.status === "string" && f.status.trim()
          ? f.status.trim()
          : null,
      triage_action:
        typeof f.triage_action === "string" && f.triage_action.trim()
          ? f.triage_action.trim()
          : null,
      triage_reason:
        typeof f.triage_reason === "string" && f.triage_reason.trim()
          ? f.triage_reason.trim()
          : null,
      target_memory_id:
        typeof f.target_memory_id === "string" && f.target_memory_id.trim()
          ? f.target_memory_id.trim()
          : null,
    }))
    .filter((fact) => fact.fact.trim().length > 0);

  return facts.length ? facts : undefined;
}

function normalizeMemoryWritePreview(
  value: unknown,
): MemoryWritePreview | null {
  if (!value || typeof value !== "object") {
    return null;
  }

  const candidate = value as Record<string, unknown>;
  const items = Array.isArray(candidate.items)
    ? candidate.items
        .filter(
          (item: unknown): item is Record<string, unknown> =>
            typeof item === "object" && item !== null,
        )
        .map((item, index): MemoryWritePreviewItem | null => {
          const fact = String(item.fact ?? "").trim();
          if (!fact) {
            return null;
          }
          const memoryType =
            item.memory_type === "permanent" || item.memory_type === "temporary"
              ? item.memory_type
              : null;
          const normalizedItem: MemoryWritePreviewItem = {
            id: String(item.id ?? `preview-${index}`).trim() || `preview-${index}`,
            fact,
            category: String(item.category ?? "").trim(),
            importance:
              typeof item.importance === "number" && Number.isFinite(item.importance)
                ? item.importance
                : 0,
            triage_action:
              typeof item.triage_action === "string" && item.triage_action.trim()
                ? item.triage_action.trim()
                : null,
            triage_reason:
              typeof item.triage_reason === "string" && item.triage_reason.trim()
                ? item.triage_reason.trim()
                : null,
            status:
              typeof item.status === "string" && item.status.trim()
                ? item.status.trim()
                : null,
            target_memory_id:
              typeof item.target_memory_id === "string" && item.target_memory_id.trim()
                ? item.target_memory_id.trim()
                : null,
            memory_type: memoryType,
            evidence_count:
              typeof item.evidence_count === "number" && Number.isFinite(item.evidence_count)
                ? item.evidence_count
                : 0,
          };
          return normalizedItem;
        })
        .filter((item): item is MemoryWritePreviewItem => item !== null)
    : [];

  const summary =
    typeof candidate.summary === "string" && candidate.summary.trim()
      ? candidate.summary.trim()
      : null;
  const itemCount =
    typeof candidate.item_count === "number" && Number.isFinite(candidate.item_count)
      ? candidate.item_count
      : null;
  const writtenCount =
    typeof candidate.written_count === "number" &&
    Number.isFinite(candidate.written_count)
      ? candidate.written_count
      : null;
  const discardedCount =
    typeof candidate.discarded_count === "number" &&
    Number.isFinite(candidate.discarded_count)
      ? candidate.discarded_count
      : null;

  if (!summary && !items.length && itemCount === null && writtenCount === null) {
    return null;
  }

  return {
    summary,
    item_count: itemCount,
    written_count: writtenCount,
    discarded_count: discardedCount,
    items,
  };
}

export interface DictationResponse {
  text_input: string;
}

export interface SpeechResponse {
  audio_response: string | null;
}

export interface ImageMessageResponse {
  message: ApiMessage;
  text_input: string;
  audio_response: string | null;
}

export interface ProjectChatSettings {
  id: string;
  default_chat_mode: ChatMode;
}

export interface PipelineConfigItem {
  model_type:
    | "llm"
    | "asr"
    | "tts"
    | "vision"
    | "realtime"
    | "realtime_asr"
    | "realtime_tts";
  model_id: string;
}

export interface PipelineResponse {
  items: PipelineConfigItem[];
}

export interface CatalogModelItem {
  model_id: string;
  capabilities: string[];
}

export interface LiveTranscriptUpdate {
  role: "user" | "assistant";
  text: string;
  final: boolean;
  action?: "upsert" | "discard";
}

export const VOICE_ACTIVE_STATES = new Set([
  "connecting",
  "ready",
  "listening",
  "ai_speaking",
  "reconnecting",
]);

function isCjkCharacter(value: string): boolean {
  return /[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]/.test(value);
}

function isWordLikeCharacter(value: string): boolean {
  return /[A-Za-z0-9]/.test(value);
}

function startsWithPunctuation(value: string): boolean {
  return /^[\s.,!?;:)\]}，。！？；：、】【》」』、]/.test(value);
}

function endsWithOpeningPunctuation(value: string): boolean {
  return /[\s([{'"“‘（【《「『-]$/.test(value);
}

export function appendNaturalText(base: string, addition: string): string {
  const trimmedAddition = addition.trim();
  if (!trimmedAddition) {
    return base.trimEnd();
  }

  const trimmedBase = base.trimEnd();
  if (!trimmedBase) {
    return trimmedAddition;
  }

  const lastChar = trimmedBase.slice(-1);
  const firstChar = trimmedAddition[0] ?? "";
  const shouldInsertSpace =
    isWordLikeCharacter(lastChar) &&
    isWordLikeCharacter(firstChar) &&
    !isCjkCharacter(lastChar) &&
    !isCjkCharacter(firstChar) &&
    !endsWithOpeningPunctuation(trimmedBase) &&
    !startsWithPunctuation(trimmedAddition);

  return shouldInsertSpace
    ? `${trimmedBase} ${trimmedAddition}`
    : `${trimmedBase}${trimmedAddition}`;
}

export function joinNaturalText(segments: string[]): string {
  return segments.reduce((acc, segment) => appendNaturalText(acc, segment), "");
}

export function createAudioPlayer(base64Audio: string) {
  const audioBytes = Uint8Array.from(atob(base64Audio), (c) => c.charCodeAt(0));
  const blob = new Blob([audioBytes], { type: "audio/mp3" });
  const url = URL.createObjectURL(blob);
  return {
    audio: new Audio(url),
    url,
  };
}

function normalizeContextLevel(value: unknown): RetrievalContextLevel | null {
  if (typeof value !== "string") {
    return null;
  }
  if (
    value === "none" ||
    value === "profile_only" ||
    value === "memory_only" ||
    value === "full_rag"
  ) {
    return value;
  }
  return null;
}

export function getPipelineModelId(
  items: PipelineConfigItem[],
  modelType: PipelineConfigItem["model_type"],
  fallback: string,
) {
  return (
    items.find((item) => item.model_type === modelType)?.model_id || fallback
  );
}

export function modelSupportsCapability(
  catalogItems: CatalogModelItem[],
  modelId: string,
  ...required: string[]
) {
  const entry = catalogItems.find((item) => item.model_id === modelId);
  if (!entry) {
    return false;
  }
  const capabilities = new Set(
    (entry.capabilities || []).map((value) => value.toLowerCase()),
  );
  return required.every((value) => capabilities.has(value.toLowerCase()));
}

export function normalizeSearchSources(value: unknown): SearchSource[] {
  if (!Array.isArray(value)) {
    return [];
  }

  return value.flatMap((item) => {
    if (!item || typeof item !== "object") {
      return [];
    }
    const candidate = item as Record<string, unknown>;
    const title =
      typeof candidate.title === "string" ? candidate.title.trim() : "";
    const url = typeof candidate.url === "string" ? candidate.url.trim() : "";
    if (!title || !url) {
      return [];
    }
    const index =
      typeof candidate.index === "number" && Number.isFinite(candidate.index)
        ? candidate.index
        : 0;
    const domain =
      typeof candidate.domain === "string" && candidate.domain.trim()
        ? candidate.domain.trim()
        : (() => {
            try {
              return new URL(url).hostname;
            } catch {
              return "";
            }
          })();

    return [
      {
        index,
        title,
        url,
        domain,
        site_name:
          typeof candidate.site_name === "string" && candidate.site_name.trim()
            ? candidate.site_name.trim()
            : null,
        summary:
          typeof candidate.summary === "string" && candidate.summary.trim()
            ? candidate.summary.trim()
            : null,
        icon:
          typeof candidate.icon === "string" && candidate.icon.trim()
            ? candidate.icon.trim()
            : null,
        tool_type:
          typeof candidate.tool_type === "string" && candidate.tool_type.trim()
            ? candidate.tool_type.trim()
            : null,
        image_url:
          typeof candidate.image_url === "string" && candidate.image_url.trim()
            ? candidate.image_url.trim()
            : null,
        thumbnail_url:
          typeof candidate.thumbnail_url === "string" &&
          candidate.thumbnail_url.trim()
            ? candidate.thumbnail_url.trim()
            : null,
      },
    ];
  });
}

function normalizeOptionalString(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function normalizeOptionalNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function normalizeStringArray(value: unknown): string[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value.flatMap((item) => {
    if (typeof item !== "string" || item.trim().length === 0) {
      return [];
    }
    return [item.trim()];
  });
}

function normalizeTraceMemory(value: unknown): RetrievalTraceMemory | null {
  if (!value || typeof value !== "object") {
    return null;
  }
  const candidate = value as Record<string, unknown>;
  const id = typeof candidate.id === "string" ? candidate.id : "";
  const content =
    typeof candidate.content === "string" ? candidate.content.trim() : "";
  if (!id || !content) {
    return null;
  }
  const selectionReason =
    normalizeOptionalString(candidate.selection_reason) ??
    normalizeOptionalString(candidate.why_selected);
  return {
    id,
    type: typeof candidate.type === "string" ? candidate.type : undefined,
    category:
      typeof candidate.category === "string" ? candidate.category : undefined,
    memory_kind:
      typeof candidate.memory_kind === "string" ? candidate.memory_kind : null,
    node_status:
      typeof candidate.node_status === "string" ? candidate.node_status : null,
    source: typeof candidate.source === "string" ? candidate.source : null,
    score:
      typeof candidate.score === "number" && Number.isFinite(candidate.score)
        ? candidate.score
        : null,
    semantic_score:
      normalizeOptionalNumber(candidate.semantic_score),
    pinned: candidate.pinned === true,
    salience: normalizeOptionalNumber(candidate.salience),
    content,
    selection_reason: selectionReason,
    why_selected: selectionReason,
    suppression_reason: normalizeOptionalString(candidate.suppression_reason),
    outcome_weight: normalizeOptionalNumber(candidate.outcome_weight),
    episode_ids: normalizeStringArray(candidate.episode_ids),
    supporting_quote: normalizeOptionalString(candidate.supporting_quote),
    supporting_file_excerpt: normalizeOptionalString(
      candidate.supporting_file_excerpt,
    ),
    supporting_memory_id: normalizeOptionalString(candidate.supporting_memory_id),
  };
}

function normalizeTraceView(value: unknown): RetrievalTraceViewHit | null {
  if (!value || typeof value !== "object") {
    return null;
  }
  const candidate = value as Record<string, unknown>;
  const id = typeof candidate.id === "string" ? candidate.id.trim() : "";
  const content =
    typeof candidate.content === "string" ? candidate.content.trim() : "";
  if (!id || !content) {
    return null;
  }
  const selectionReason =
    normalizeOptionalString(candidate.selection_reason) ??
    normalizeOptionalString(candidate.why_selected);
  return {
    id,
    view_type:
      typeof candidate.view_type === "string" ? candidate.view_type : null,
    source_subject_id:
      typeof candidate.source_subject_id === "string"
        ? candidate.source_subject_id
        : null,
    score:
      typeof candidate.score === "number" && Number.isFinite(candidate.score)
        ? candidate.score
        : null,
    content,
    snippet: normalizeOptionalString(candidate.snippet),
    selection_reason: selectionReason,
    why_selected: selectionReason,
    suppression_reason: normalizeOptionalString(candidate.suppression_reason),
    outcome_weight: normalizeOptionalNumber(candidate.outcome_weight),
    supporting_memory_id: normalizeOptionalString(candidate.supporting_memory_id),
    supporting_quote: normalizeOptionalString(candidate.supporting_quote),
  };
}

function normalizeTraceEvidence(value: unknown): RetrievalTraceEvidenceHit | null {
  if (!value || typeof value !== "object") {
    return null;
  }
  const candidate = value as Record<string, unknown>;
  const id = typeof candidate.id === "string" ? candidate.id.trim() : "";
  const quoteText =
    typeof candidate.quote_text === "string"
      ? candidate.quote_text.trim()
      : "";
  if (!id || !quoteText) {
    return null;
  }
  const selectionReason =
    normalizeOptionalString(candidate.selection_reason) ??
    normalizeOptionalString(candidate.why_selected);
  return {
    id,
    memory_id:
      typeof candidate.memory_id === "string" ? candidate.memory_id : null,
    source_type:
      typeof candidate.source_type === "string" ? candidate.source_type : null,
    conversation_id:
      typeof candidate.conversation_id === "string"
        ? candidate.conversation_id
        : null,
    message_id:
      typeof candidate.message_id === "string" ? candidate.message_id : null,
    episode_id:
      typeof candidate.episode_id === "string" ? candidate.episode_id : null,
    chunk_id: typeof candidate.chunk_id === "string" ? candidate.chunk_id : null,
    confidence:
      typeof candidate.confidence === "number" &&
      Number.isFinite(candidate.confidence)
        ? candidate.confidence
        : null,
    score:
      typeof candidate.score === "number" && Number.isFinite(candidate.score)
        ? candidate.score
        : null,
    quote_text: quoteText,
    snippet: normalizeOptionalString(candidate.snippet),
    selection_reason: selectionReason,
    why_selected: selectionReason,
    supporting_memory_id: normalizeOptionalString(candidate.supporting_memory_id),
  };
}

function normalizeTraceChunk(value: unknown): RetrievalTraceChunk | null {
  if (!value || typeof value !== "object") {
    return null;
  }
  const candidate = value as Record<string, unknown>;
  const chunkText =
    typeof candidate.chunk_text === "string" ? candidate.chunk_text.trim() : "";
  if (!chunkText) {
    return null;
  }
  return {
    id: typeof candidate.id === "string" ? candidate.id : null,
    data_item_id:
      typeof candidate.data_item_id === "string"
        ? candidate.data_item_id
        : null,
    filename:
      typeof candidate.filename === "string" ? candidate.filename : null,
    memory_ids: Array.isArray(candidate.memory_ids)
      ? candidate.memory_ids.filter(
          (item): item is string => typeof item === "string" && item.trim().length > 0,
        )
      : [],
    score:
      typeof candidate.score === "number" && Number.isFinite(candidate.score)
        ? candidate.score
        : null,
    chunk_text: chunkText,
    why_selected:
      typeof candidate.why_selected === "string" &&
      candidate.why_selected.trim()
        ? candidate.why_selected.trim()
        : null,
  };
}

export function normalizeRetrievalTrace(value: unknown): RetrievalTrace | null {
  if (!value || typeof value !== "object") {
    return null;
  }
  const candidate = value as Record<string, unknown>;
  const contextLevel = normalizeContextLevel(candidate.context_level);
  const memories = Array.isArray(candidate.memories)
    ? candidate.memories
        .map((item) => normalizeTraceMemory(item))
        .filter((item): item is RetrievalTraceMemory => item !== null)
    : [];
  const knowledgeChunks = Array.isArray(candidate.knowledge_chunks)
    ? candidate.knowledge_chunks
        .map((item) => normalizeTraceChunk(item))
        .filter((item): item is RetrievalTraceChunk => item !== null)
    : [];
  const linkedFileChunks = Array.isArray(candidate.linked_file_chunks)
    ? candidate.linked_file_chunks
        .map((item) => normalizeTraceChunk(item))
        .filter((item): item is RetrievalTraceChunk => item !== null)
    : [];
  const selectedMemories = Array.isArray(candidate.selected_memories)
    ? candidate.selected_memories
        .map((item) => normalizeTraceMemory(item))
        .filter((item): item is RetrievalTraceMemory => item !== null)
    : [];
  const viewHits = Array.isArray(candidate.view_hits)
    ? candidate.view_hits
        .map((item) => normalizeTraceView(item))
        .filter((item): item is RetrievalTraceViewHit => item !== null)
    : [];
  const evidenceHits = Array.isArray(candidate.evidence_hits)
    ? candidate.evidence_hits
        .map((item) => normalizeTraceEvidence(item))
        .filter((item): item is RetrievalTraceEvidenceHit => item !== null)
    : [];
  const memoryCounts =
    candidate.memory_counts && typeof candidate.memory_counts === "object"
      ? {
          static:
            typeof (candidate.memory_counts as Record<string, unknown>)
              .static === "number"
              ? ((candidate.memory_counts as Record<string, unknown>)
                  .static as number)
              : undefined,
          relevant:
            typeof (candidate.memory_counts as Record<string, unknown>)
              .relevant === "number"
              ? ((candidate.memory_counts as Record<string, unknown>)
                  .relevant as number)
              : undefined,
          graph:
            typeof (candidate.memory_counts as Record<string, unknown>)
              .graph === "number"
              ? ((candidate.memory_counts as Record<string, unknown>)
                  .graph as number)
              : undefined,
          temporary:
            typeof (candidate.memory_counts as Record<string, unknown>)
              .temporary === "number"
              ? ((candidate.memory_counts as Record<string, unknown>)
                  .temporary as number)
              : undefined,
        }
      : undefined;
  const layerHits =
    candidate.layer_hits && typeof candidate.layer_hits === "object"
      ? {
          profile:
            typeof (candidate.layer_hits as Record<string, unknown>).profile ===
            "number"
              ? ((candidate.layer_hits as Record<string, unknown>)
                  .profile as number)
              : undefined,
          durable_facts:
            typeof (candidate.layer_hits as Record<string, unknown>)
              .durable_facts === "number"
              ? ((candidate.layer_hits as Record<string, unknown>)
                  .durable_facts as number)
              : undefined,
          playbooks:
            typeof (candidate.layer_hits as Record<string, unknown>).playbooks ===
            "number"
              ? ((candidate.layer_hits as Record<string, unknown>)
                  .playbooks as number)
              : undefined,
          episodic_timeline:
            typeof (candidate.layer_hits as Record<string, unknown>)
              .episodic_timeline === "number"
              ? ((candidate.layer_hits as Record<string, unknown>)
                  .episodic_timeline as number)
              : undefined,
          raw_evidence:
            typeof (candidate.layer_hits as Record<string, unknown>)
              .raw_evidence === "number"
              ? ((candidate.layer_hits as Record<string, unknown>)
                  .raw_evidence as number)
              : undefined,
        }
      : undefined;

  if (
    !memories.length &&
    !selectedMemories.length &&
    !viewHits.length &&
    !evidenceHits.length &&
    !knowledgeChunks.length &&
    !linkedFileChunks.length &&
    !contextLevel
  ) {
    return null;
  }

  return {
    strategy:
      typeof candidate.strategy === "string" ? candidate.strategy : null,
    context_level: contextLevel,
    decision_source:
      typeof candidate.decision_source === "string"
        ? candidate.decision_source
        : null,
    decision_reason:
      typeof candidate.decision_reason === "string"
        ? candidate.decision_reason
        : null,
    decision_confidence:
      typeof candidate.decision_confidence === "number" &&
      Number.isFinite(candidate.decision_confidence)
        ? candidate.decision_confidence
        : null,
    layer_hits: layerHits,
    view_hits: viewHits,
    evidence_hits: evidenceHits,
    rerank_latency_ms:
      typeof candidate.rerank_latency_ms === "number" &&
      Number.isFinite(candidate.rerank_latency_ms)
        ? candidate.rerank_latency_ms
        : null,
    policy_flags: Array.isArray(candidate.policy_flags)
      ? candidate.policy_flags.filter(
          (item): item is string => typeof item === "string" && item.trim().length > 0,
        )
      : [],
    suppressed_memory_ids: Array.isArray(candidate.suppressed_memory_ids)
      ? candidate.suppressed_memory_ids.filter(
          (item): item is string => typeof item === "string" && item.trim().length > 0,
        )
      : [],
    used_playbook_ids: normalizeStringArray(candidate.used_playbook_ids),
    conflicted_memory_ids: normalizeStringArray(candidate.conflicted_memory_ids),
    episode_ids: normalizeStringArray(candidate.episode_ids),
    memory_counts: memoryCounts,
    selected_memories: selectedMemories,
    memories,
    knowledge_chunks: knowledgeChunks,
    linked_file_chunks: linkedFileChunks,
  };
}

export function toMessage(message: ApiMessage): Message {
  const meta = message.metadata_json ?? null;
  const normalizedAssistantContent = message.content;
  const normalizedAssistantReasoning =
    typeof message.reasoning_content === "string" &&
    message.reasoning_content.trim()
      ? message.reasoning_content
      : message.reasoning_content;
  const memoryWritePreview = normalizeMemoryWritePreview(meta?.memory_write_preview);
  const extractedFacts = normalizeExtractedFacts(meta?.extracted_facts);
  const memoriesExtracted =
    typeof meta?.memories_extracted === "string" &&
    meta.memories_extracted.trim()
      ? meta.memories_extracted
      : undefined;
  const memoryExtractionStatus =
    typeof meta?.memory_extraction_status === "string" &&
    meta.memory_extraction_status.trim()
      ? meta.memory_extraction_status.trim()
      : null;
  const memoryExtractionAttempts =
    typeof meta?.memory_extraction_attempts === "number" &&
    Number.isFinite(meta.memory_extraction_attempts)
      ? meta.memory_extraction_attempts
      : null;
  const memoryExtractionError =
    typeof meta?.memory_extraction_error === "string" &&
    meta.memory_extraction_error.trim()
      ? meta.memory_extraction_error.trim()
      : null;

  return {
    id: message.id,
    role: message.role,
    content: normalizedAssistantContent,
    reasoningContent: normalizedAssistantReasoning,
    sources: normalizeSearchSources(meta?.sources),
    retrievalTrace: normalizeRetrievalTrace(meta?.retrieval_trace),
    memories_extracted: memoriesExtracted,
    memory_write_preview: memoryWritePreview,
    extracted_facts: extractedFacts,
    memory_extraction_status: memoryExtractionStatus,
    memory_extraction_attempts: memoryExtractionAttempts,
    memory_extraction_error: memoryExtractionError,
    metadataJson: meta,
    animateOnMount: false,
    isStreaming: false,
  };
}

export function mergeAssistantMetadataPatch(
  message: Message,
  metadata: unknown,
): Message {
  if (!metadata || typeof metadata !== "object") {
    return message;
  }

  const candidate = metadata as Record<string, unknown>;
  const metadataJson = {
    ...(message.metadataJson ?? {}),
    ...candidate,
  };
  const memoryWritePreview = normalizeMemoryWritePreview(
    metadataJson.memory_write_preview,
  );
  const extractedFacts = normalizeExtractedFacts(metadataJson.extracted_facts);
  const sources = normalizeSearchSources(metadataJson.sources);
  const retrievalTrace = normalizeRetrievalTrace(metadataJson.retrieval_trace);
  const memoriesExtracted =
    typeof metadataJson.memories_extracted === "string" &&
    metadataJson.memories_extracted.trim()
      ? metadataJson.memories_extracted
      : undefined;
  const memoryExtractionStatus =
    typeof metadataJson.memory_extraction_status === "string" &&
    metadataJson.memory_extraction_status.trim()
      ? metadataJson.memory_extraction_status.trim()
      : null;
  const memoryExtractionAttempts =
    typeof metadataJson.memory_extraction_attempts === "number" &&
    Number.isFinite(metadataJson.memory_extraction_attempts)
      ? metadataJson.memory_extraction_attempts
      : null;
  const memoryExtractionError =
    typeof metadataJson.memory_extraction_error === "string" &&
    metadataJson.memory_extraction_error.trim()
      ? metadataJson.memory_extraction_error.trim()
      : null;

  return {
    ...message,
    metadataJson,
    sources,
    retrievalTrace,
    memory_write_preview: memoryWritePreview,
    extracted_facts: extractedFacts,
    memories_extracted: memoriesExtracted,
    memory_extraction_status: memoryExtractionStatus,
    memory_extraction_attempts: memoryExtractionAttempts,
    memory_extraction_error: memoryExtractionError,
  };
}

export function getApiErrorMessage(
  error: { code?: string; message?: string },
  t: (key: string) => string,
): string {
  if (error.code === "inference_timeout") {
    return t("errors.inferenceTimeout");
  }
  if (error.code === "model_api_unconfigured") {
    return t("errors.modelUnconfigured");
  }
  if (error.code === "model_api_unavailable") {
    return t("errors.modelUnavailable");
  }
  return t("errors.generic");
}

export function cycleState(
  current: "auto" | "on" | "off",
): "auto" | "on" | "off" {
  if (current === "auto") return "on";
  if (current === "on") return "off";
  return "auto";
}
