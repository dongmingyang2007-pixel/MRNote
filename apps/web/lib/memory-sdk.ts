import { apiGet, apiPost } from "@/lib/api";

export interface MemorySdkSearchRequest {
  project_id: string;
  query: string;
  top_k?: number;
  category?: string | null;
  type?: "permanent" | "temporary" | null;
}

export interface MemorySdkExplainRequest {
  project_id: string;
  query: string;
  top_k?: number;
  conversation_id?: string | null;
  include_subgraph?: boolean;
}

export interface MemorySdkOutcomeRequest {
  project_id: string;
  status: "success" | "partial" | "failure";
  feedback_source?: "system" | "user" | "tool";
  summary?: string | null;
  root_cause?: string | null;
  tags?: string[];
  task_id?: string | null;
  conversation_id?: string | null;
  message_id?: string | null;
  memory_ids?: string[];
  playbook_view_id?: string | null;
  learning_run_id?: string | null;
  metadata_json?: Record<string, unknown>;
}

export interface MemorySdkPlaybookFeedbackRequest {
  project_id: string;
  status: "success" | "partial" | "failure";
  root_cause?: string | null;
  task_id?: string | null;
  conversation_id?: string | null;
  message_id?: string | null;
  memory_ids?: string[];
  learning_run_id?: string | null;
  tags?: string[];
  metadata_json?: Record<string, unknown>;
}

export interface MemorySdkSubgraphRequest {
  query?: string;
  depth?: number;
  edge_types?: string[];
}

export interface MemorySdkSearchHit {
  result_type: string;
  score: number;
  snippet: string;
  selection_reason?: string | null;
  suppression_reason?: string | null;
  outcome_weight?: number | null;
  episode_id?: string | null;
  supporting_memory_id?: string | null;
  memory?: Record<string, unknown> | null;
  view?: Record<string, unknown> | null;
  evidence?: Record<string, unknown> | null;
}

export interface MemorySdkExplainResponse {
  hits: MemorySdkSearchHit[];
  trace: Record<string, unknown>;
  suppressed_candidates: Array<Record<string, unknown>>;
  subgraph?: {
    nodes: Array<Record<string, unknown>>;
    edges: Array<Record<string, unknown>>;
  } | null;
}

export function searchMemory(payload: MemorySdkSearchRequest): Promise<MemorySdkSearchHit[]> {
  return apiPost<MemorySdkSearchHit[]>("/api/v1/memory/search", payload);
}

export function explainMemorySelection(
  payload: MemorySdkExplainRequest,
): Promise<MemorySdkExplainResponse> {
  return apiPost<MemorySdkExplainResponse>("/api/v1/memory/search/explain", payload);
}

export function recordOutcome(
  payload: MemorySdkOutcomeRequest,
): Promise<Record<string, unknown>> {
  return apiPost<Record<string, unknown>>("/api/v1/memory/outcomes", payload);
}

export function submitPlaybookFeedback(
  viewId: string,
  payload: MemorySdkPlaybookFeedbackRequest,
): Promise<Record<string, unknown>> {
  return apiPost<Record<string, unknown>>(`/api/v1/memory/playbooks/${viewId}/feedback`, payload);
}

export function getMemorySubgraph(
  memoryId: string,
  payload: MemorySdkSubgraphRequest = {},
): Promise<Record<string, unknown>> {
  return apiPost<Record<string, unknown>>(`/api/v1/memory/${memoryId}/subgraph`, payload);
}

export function getMemoryLearningRuns(projectId: string): Promise<Array<Record<string, unknown>>> {
  return apiGet<Array<Record<string, unknown>>>(
    `/api/v1/memory/learning-runs?project_id=${encodeURIComponent(projectId)}`,
  );
}

export function getMemoryHealth(projectId: string): Promise<Record<string, unknown>> {
  return apiGet<Record<string, unknown>>(
    `/api/v1/memory/health?project_id=${encodeURIComponent(projectId)}`,
  );
}
