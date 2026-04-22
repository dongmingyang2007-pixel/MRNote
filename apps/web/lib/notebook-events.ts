"use client";

export const NOTEBOOKS_CHANGED_EVENT = "mrai:notebooks-changed";
export const NOTEBOOK_PAGES_CHANGED_EVENT = "mrai:notebook-pages-changed";
export const NOTEBOOK_STUDY_CHANGED_EVENT = "mrai:notebook-study-changed";

function dispatchNotebookEvent<T>(name: string, detail?: T): void {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new CustomEvent(name, { detail }));
}

export function dispatchNotebooksChanged(): void {
  dispatchNotebookEvent(NOTEBOOKS_CHANGED_EVENT);
}

export function dispatchNotebookPagesChanged(notebookId?: string): void {
  dispatchNotebookEvent(
    NOTEBOOK_PAGES_CHANGED_EVENT,
    notebookId ? { notebookId } : {},
  );
}

export function dispatchNotebookStudyChanged(notebookId: string): void {
  dispatchNotebookEvent(NOTEBOOK_STUDY_CHANGED_EVENT, { notebookId });
}
