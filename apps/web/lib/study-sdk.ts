/**
 * Study SDK
 *
 * Thin typed wrappers around `/api/v1/notebooks/{id}/study*`, decks, cards and
 * reviews. Spec §23 mandates this module; like notebook-sdk it is intentionally
 * scoped to calls touched in the current pass.
 */

import { apiDelete, apiGet, apiPatch, apiPost } from "@/lib/api";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type StudyAssetStatus = "pending" | "parsing" | "chunked" | "indexed" | "failed";

export interface StudyAsset {
  id: string;
  notebook_id: string;
  title: string;
  asset_type: string;
  status: StudyAssetStatus;
  total_chunks: number;
  created_at: string;
}

export interface StudyAssetChunk {
  id: string;
  asset_id: string;
  index: number;
  text: string;
  token_count?: number | null;
}

export interface Deck {
  id: string;
  notebook_id: string;
  title: string;
  card_count?: number;
  archived?: boolean;
  last_reviewed_at?: string | null;
}

export interface Flashcard {
  id: string;
  deck_id: string;
  front: string;
  back: string;
  review_count?: number;
  next_review_at?: string | null;
}

export interface ReviewInput {
  card_id: string;
  rating: "again" | "hard" | "good" | "easy";
  reviewed_at?: string;
}

// ---------------------------------------------------------------------------
// Study assets
// ---------------------------------------------------------------------------

export function listAssets(notebookId: string): Promise<{ items: StudyAsset[] }> {
  return apiGet<{ items: StudyAsset[] }>(
    `/api/v1/notebooks/${notebookId}/study-assets`,
  );
}

export function listStudyAssetsShort(notebookId: string): Promise<{ items: StudyAsset[] }> {
  return apiGet<{ items: StudyAsset[] }>(
    `/api/v1/notebooks/${notebookId}/study`,
  );
}

export function getAssetChunks(
  notebookId: string,
  assetId: string,
): Promise<{ items: StudyAssetChunk[] }> {
  return apiGet<{ items: StudyAssetChunk[] }>(
    `/api/v1/notebooks/${notebookId}/study-assets/${assetId}/chunks`,
  );
}

// ---------------------------------------------------------------------------
// Decks
// ---------------------------------------------------------------------------

export function listDecks(notebookId: string): Promise<{ items: Deck[] }> {
  return apiGet<{ items: Deck[] }>(`/api/v1/notebooks/${notebookId}/decks`);
}

export function createDeck(
  notebookId: string,
  body: { title: string },
): Promise<Deck> {
  return apiPost<Deck>(`/api/v1/notebooks/${notebookId}/decks`, body);
}

export function archiveDeck(
  notebookId: string,
  deckId: string,
): Promise<Deck> {
  return apiPatch<Deck>(
    `/api/v1/notebooks/${notebookId}/decks/${deckId}`,
    { archived: true },
  );
}

// ---------------------------------------------------------------------------
// Cards
// ---------------------------------------------------------------------------

export function createCard(
  deckId: string,
  body: { front: string; back: string },
): Promise<Flashcard> {
  return apiPost<Flashcard>(`/api/v1/decks/${deckId}/cards`, body);
}

export function deleteCard(cardId: string): Promise<void> {
  return apiDelete<void>(`/api/v1/cards/${cardId}`);
}

export function review(body: ReviewInput): Promise<Flashcard> {
  return apiPost<Flashcard>(`/api/v1/cards/${body.card_id}/review`, body);
}

// ---------------------------------------------------------------------------
// Grouped export
// ---------------------------------------------------------------------------

export const studySDK = {
  listAssets,
  listStudyAssetsShort,
  getAssetChunks,
  listDecks,
  createDeck,
  archiveDeck,
  createCard,
  deleteCard,
  review,
} as const;

export default studySDK;
