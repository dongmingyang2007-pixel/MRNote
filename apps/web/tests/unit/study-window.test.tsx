import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import StudyWindow from "@/components/notebook/contents/StudyWindow";

const openWindow = vi.fn();

vi.mock("@/components/notebook/WindowManager", () => ({
  useWindowManager: () => ({ openWindow }),
}));

vi.mock("@/lib/api-stream", () => ({
  apiStream: vi.fn(),
}));

vi.mock("@/lib/study-upload", () => ({
  STUDY_UPLOAD_ACCEPT: ".pdf,.py,image/*",
  uploadStudyAssets: vi.fn(),
}));

describe("StudyWindow", () => {
  beforeEach(() => {
    openWindow.mockReset();
  });

  afterEach(() => {
    cleanup();
  });

  it("derives generated pages from notebook page slugs when asset metadata is missing", async () => {
    global.fetch = vi.fn(async (url: RequestInfo | URL) => {
      const urlStr = String(url);
      if (urlStr.includes("/api/v1/notebooks/nb1/study-assets")) {
        return {
          ok: true,
          status: 200,
          json: async () => ({
            items: [
              {
                id: "asset1",
                notebook_id: "nb1",
                title: "Systems Design",
                asset_type: "pdf",
                status: "indexed",
                total_chunks: 12,
                created_at: "2026-04-21T00:00:00Z",
                updated_at: "2026-04-21T00:05:00Z",
                metadata_json: null,
              },
            ],
            total: 1,
          }),
        } as Response;
      }
      if (urlStr.includes("/api/v1/notebooks/nb1/pages")) {
        return {
          ok: true,
          status: 200,
          json: async () => ({
            items: [
              {
                id: "p-overview",
                notebook_id: "nb1",
                title: "Systems Design - Overview",
                slug: "study-asset-asset1-overview",
                page_type: "document",
              },
              {
                id: "p-notes",
                notebook_id: "nb1",
                title: "Systems Design - Notes",
                slug: "study-asset-asset1-notes",
                page_type: "document",
              },
              {
                id: "p-ch1",
                notebook_id: "nb1",
                title: "Systems Design - Chapter 1",
                slug: "study-asset-asset1-chapter-1",
                page_type: "document",
              },
            ],
          }),
        } as Response;
      }
      if (urlStr.includes("/api/v1/study-assets/asset1/chunks")) {
        return {
          ok: true,
          status: 200,
          json: async () => ({
            items: [
              {
                id: "chunk1",
                chunk_index: 0,
                heading: "Intro",
                content: "Hello world",
                page_number: 1,
              },
            ],
            total: 1,
          }),
        } as Response;
      }
      throw new Error(`unexpected fetch ${urlStr}`);
    }) as typeof fetch;

    render(<StudyWindow notebookId="nb1" initialAssetId="asset1" />);

    await waitFor(() => {
      expect(screen.getByText("study.workspace.pages.overview")).toBeTruthy();
      expect(screen.getByText("study.workspace.pages.notes")).toBeTruthy();
      expect(screen.getByText("study.workspace.pages.chapter")).toBeTruthy();
    });
  });

  it("renders the progress workspace with weekly study metrics", async () => {
    global.fetch = vi.fn(async (url: RequestInfo | URL) => {
      const urlStr = String(url);
      if (urlStr.includes("/api/v1/notebooks/nb1/study-assets")) {
        return {
          ok: true,
          status: 200,
          json: async () => ({
            items: [],
            total: 0,
          }),
        } as Response;
      }
      if (urlStr.includes("/api/v1/notebooks/nb1/pages")) {
        return {
          ok: true,
          status: 200,
          json: async () => ({
            items: [],
          }),
        } as Response;
      }
      if (urlStr.includes("/api/v1/notebooks/nb1/study/insights")) {
        return {
          ok: true,
          status: 200,
          json: async () => ({
            period_start: "2026-04-16T00:00:00Z",
            period_end: "2026-04-22T00:00:00Z",
            active_days: 3,
            totals: {
              assets: 1,
              indexed_assets: 1,
              generated_pages: 3,
              chunks: 24,
              decks: 1,
              cards: 12,
              new_cards: 2,
              due_cards: 4,
              weak_cards: 2,
              reviewed_this_week: 9,
              ai_actions_this_week: 3,
              confusions_logged: 1,
            },
            action_counts: [
              { action_type: "study.ask", count: 1 },
              { action_type: "study.flashcards", count: 1 },
              { action_type: "study.quiz", count: 1 },
              { action_type: "study.review_card", count: 9 },
            ],
            daily_activity: [
              { date: "2026-04-16", review_count: 0, ai_action_count: 0 },
              { date: "2026-04-17", review_count: 1, ai_action_count: 0 },
              { date: "2026-04-18", review_count: 2, ai_action_count: 1 },
              { date: "2026-04-19", review_count: 0, ai_action_count: 0 },
              { date: "2026-04-20", review_count: 3, ai_action_count: 1 },
              { date: "2026-04-21", review_count: 3, ai_action_count: 1 },
              { date: "2026-04-22", review_count: 0, ai_action_count: 0 },
            ],
            deck_pressure: [
              {
                deck_id: "deck1",
                deck_name: "Core ideas",
                total_cards: 12,
                due_cards: 4,
                last_review_at: "2026-04-21T12:00:00Z",
                next_due_at: "2026-04-22T12:00:00Z",
              },
            ],
            weak_cards: [
              {
                card_id: "card1",
                deck_id: "deck1",
                deck_name: "Core ideas",
                front: "What is a quorum?",
                review_count: 2,
                lapse_count: 1,
                consecutive_failures: 1,
                next_review_at: "2026-04-22T12:00:00Z",
              },
            ],
            recent_actions: [
              {
                id: "log1",
                action_type: "study.ask",
                summary: "Asked about quorum tradeoffs",
                created_at: "2026-04-21T12:30:00Z",
              },
            ],
          }),
        } as Response;
      }
      throw new Error(`unexpected fetch ${urlStr}`);
    }) as typeof fetch;

    render(<StudyWindow notebookId="nb1" />);

    screen.getByTestId("study-tab-progress").click();

    await waitFor(() => {
      expect(screen.getByTestId("study-progress-panel")).toBeTruthy();
      expect(screen.getByText("study.progress.metrics.due_cards")).toBeTruthy();
      expect(screen.getByText("study.progress.headline.active")).toBeTruthy();
      expect(screen.getByText("study.progress.actions.reviewDue")).toBeTruthy();
    });
  });
});
