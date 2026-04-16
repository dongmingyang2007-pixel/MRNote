"use client";

import { useState } from "react";
import AssetsPanel from "./study/AssetsPanel";
import DecksPanel from "./study/DecksPanel";
import ReviewSession from "./study/ReviewSession";

type StudyTab = "assets" | "decks" | "review";

interface StudyWindowProps {
  notebookId: string;
}

export default function StudyWindow({ notebookId }: StudyWindowProps) {
  const [tab, setTab] = useState<StudyTab>("assets");
  const [reviewingDeckId, setReviewingDeckId] = useState<string | null>(null);

  const handleStartReview = (deckId: string) => {
    setReviewingDeckId(deckId);
    setTab("review");
  };

  return (
    <div className="study-window" data-testid="study-window">
      <div className="study-window__tabs" role="tablist">
        <button
          type="button"
          role="tab"
          aria-selected={tab === "assets"}
          data-testid="study-tab-assets"
          onClick={() => setTab("assets")}
        >
          Assets
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={tab === "decks"}
          data-testid="study-tab-decks"
          onClick={() => setTab("decks")}
        >
          Decks
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={tab === "review"}
          data-testid="study-tab-review"
          onClick={() => setTab("review")}
          disabled={!reviewingDeckId}
          title={reviewingDeckId ? "" : "Start a review from the Decks tab first"}
        >
          Review
        </button>
      </div>
      <div className="study-window__body">
        {tab === "assets" && <AssetsPanel notebookId={notebookId} />}
        {tab === "decks" && (
          <DecksPanel notebookId={notebookId} onStartReview={handleStartReview} />
        )}
        {tab === "review" && reviewingDeckId && (
          <ReviewSession
            deckId={reviewingDeckId}
            onExit={() => setTab("decks")}
          />
        )}
      </div>
    </div>
  );
}
