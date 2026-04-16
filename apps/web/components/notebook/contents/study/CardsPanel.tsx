"use client";
interface Props {
  deckId: string;
  notebookId: string;
  onBack: () => void;
  onStartReview: (deckId: string) => void;
}
export default function CardsPanel(_: Props) { return <div>CardsPanel (TODO)</div>; }
