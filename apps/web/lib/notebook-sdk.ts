/**
 * Notebook SDK
 *
 * Centralized typed wrappers around `/api/v1/notebooks` + `/api/v1/pages`
 * endpoints. Spec §23 lists this module as mandatory. Components should prefer
 * importing from here over hand-rolling `apiGet("/api/v1/notebooks/...")`.
 *
 * Scope is intentionally narrow: the calls currently used by the components we
 * touched in this pass. Other callers still use raw `apiGet/apiPost` and can be
 * migrated incrementally.
 */

import { apiDelete, apiGet, apiPatch, apiPost } from "@/lib/api";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type NotebookType = "personal" | "work" | "study" | "scratch";
export type NotebookVisibility = "private" | "workspace";

export interface NotebookInfo {
  id: string;
  title: string;
  description: string;
  notebook_type: string;
  icon?: string | null;
  visibility?: string | null;
  project_id: string | null;
  updated_at?: string;
  page_count?: number;
  study_asset_count?: number;
  ai_action_count?: number;
}

export interface CreateNotebookInput {
  title: string;
  notebook_type: NotebookType;
  icon?: string | null;
  description?: string | null;
  visibility?: NotebookVisibility | null;
}

export interface UpdateNotebookInput {
  title?: string;
  description?: string;
  notebook_type?: NotebookType;
  icon?: string | null;
  visibility?: NotebookVisibility;
}

export interface PageItem {
  id: string;
  notebook_id?: string;
  title: string;
  page_type?: string;
  updated_at?: string;
  last_edited_at?: string | null;
  plain_text_preview?: string;
  content_json?: Record<string, unknown>;
}

export interface PageListResponse {
  items: PageItem[];
}

export interface MemoryCandidateItem {
  id: string;
  content: string;
  status: string;
  confidence?: number | null;
  source?: Record<string, unknown> | null;
}

export interface MemoryLinksResponse {
  items: MemoryCandidateItem[];
}

export interface RelatedPagesItem {
  id: string;
  title: string;
  preview?: string;
  score?: number | null;
}

export interface RelatedPagesResponse {
  items: RelatedPagesItem[];
}

export interface GlobalSearchItem {
  id: string;
  title: string;
  type: string;
  snippet?: string;
  notebook_id?: string | null;
  page_id?: string | null;
}

export interface GlobalSearchResponse {
  items: GlobalSearchItem[];
}

// ---------------------------------------------------------------------------
// Notebook CRUD
// ---------------------------------------------------------------------------

export function listNotebooks(): Promise<{ items: NotebookInfo[] }> {
  return apiGet<{ items: NotebookInfo[] }>("/api/v1/notebooks");
}

export function getNotebook(notebookId: string): Promise<NotebookInfo> {
  return apiGet<NotebookInfo>(`/api/v1/notebooks/${notebookId}`);
}

export function createNotebook(input: CreateNotebookInput): Promise<NotebookInfo> {
  const payload: Record<string, unknown> = {
    title: input.title,
    notebook_type: input.notebook_type,
  };
  if (input.description !== undefined && input.description !== null) {
    payload.description = input.description;
  }
  if (input.icon !== undefined && input.icon !== null) {
    payload.icon = input.icon;
  }
  if (input.visibility !== undefined && input.visibility !== null) {
    payload.visibility = input.visibility;
  }
  return apiPost<NotebookInfo>("/api/v1/notebooks", payload);
}

export function updateNotebook(
  notebookId: string,
  input: UpdateNotebookInput,
): Promise<NotebookInfo> {
  return apiPatch<NotebookInfo>(`/api/v1/notebooks/${notebookId}`, input);
}

export function deleteNotebook(notebookId: string): Promise<void> {
  return apiDelete<void>(`/api/v1/notebooks/${notebookId}`);
}

// ---------------------------------------------------------------------------
// Pages
// ---------------------------------------------------------------------------

export function listPages(notebookId: string): Promise<PageListResponse> {
  return apiGet<PageListResponse>(`/api/v1/notebooks/${notebookId}/pages`);
}

export function getPage(pageId: string): Promise<PageItem> {
  return apiGet<PageItem>(`/api/v1/pages/${pageId}`);
}

export function updatePage(
  pageId: string,
  body: Partial<PageItem> & {
    content_json?: Record<string, unknown>;
    title?: string;
  },
  init?: RequestInit,
): Promise<PageItem> {
  return apiPatch<PageItem>(`/api/v1/pages/${pageId}`, body, init);
}

export function createPage(
  notebookId: string,
  body: { title?: string; page_type?: string },
): Promise<PageItem> {
  return apiPost<PageItem>(`/api/v1/notebooks/${notebookId}/pages`, body);
}

export function deletePage(pageId: string): Promise<void> {
  return apiDelete<void>(`/api/v1/pages/${pageId}`);
}

// ---------------------------------------------------------------------------
// Page memory
// ---------------------------------------------------------------------------

export function getPageMemoryLinks(pageId: string): Promise<MemoryLinksResponse> {
  return apiGet<MemoryLinksResponse>(`/api/v1/pages/${pageId}/memory/links`);
}

export function extractPageMemory(
  pageId: string,
  body: { selected_text?: string } = {},
): Promise<Record<string, unknown>> {
  return apiPost<Record<string, unknown>>(
    `/api/v1/pages/${pageId}/memory/extract`,
    body,
  );
}

export function confirmPageMemory(
  pageId: string,
  itemId: string,
): Promise<Record<string, unknown>> {
  return apiPost<Record<string, unknown>>(
    `/api/v1/pages/${pageId}/memory/confirm`,
    { item_id: itemId },
  );
}

export function rejectPageMemory(
  pageId: string,
  itemId: string,
): Promise<Record<string, unknown>> {
  return apiPost<Record<string, unknown>>(
    `/api/v1/pages/${pageId}/memory/reject`,
    { item_id: itemId },
  );
}

// ---------------------------------------------------------------------------
// Related pages / global search (used by selection AI actions)
// ---------------------------------------------------------------------------

export function getRelatedPages(
  pageId: string,
  params: { text?: string; limit?: number } = {},
): Promise<RelatedPagesResponse> {
  const url = new URLSearchParams();
  if (params.text) url.set("text", params.text);
  if (params.limit !== undefined) url.set("limit", String(params.limit));
  const qs = url.toString();
  return apiGet<RelatedPagesResponse>(
    `/api/v1/pages/${pageId}/related${qs ? `?${qs}` : ""}`,
  );
}

export function searchGlobal(
  query: string,
  params: { scope?: string; limit?: number } = {},
): Promise<GlobalSearchResponse> {
  const url = new URLSearchParams();
  url.set("q", query);
  if (params.scope) url.set("scope", params.scope);
  if (params.limit !== undefined) url.set("limit", String(params.limit));
  return apiGet<GlobalSearchResponse>(
    `/api/v1/search/global?${url.toString()}`,
  );
}

// ---------------------------------------------------------------------------
// Grouped export (spec §23 naming)
// ---------------------------------------------------------------------------

export const notebookSDK = {
  list: listNotebooks,
  get: getNotebook,
  create: createNotebook,
  patch: updateNotebook,
  delete: deleteNotebook,
  listPages,
  getPage,
  createPage,
  updatePage,
  deletePage,
  getPageMemoryLinks,
  extractPageMemory,
  confirmPageMemory,
  rejectPageMemory,
  getRelatedPages,
  searchGlobal,
} as const;

export default notebookSDK;
