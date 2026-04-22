import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const markCompleted = vi.fn();
const apiPost = vi.fn();
const dispatchNotebookPagesChanged = vi.fn();
const dispatchNotebooksChanged = vi.fn();

vi.mock("@/hooks/useOnboardingStatus", () => ({
  useOnboardingStatus: () => ({
    completed: false,
    markCompleted,
  }),
}));

vi.mock("@/lib/api", () => ({
  apiPost: (...args: unknown[]) => apiPost(...args),
}));

vi.mock("@/lib/notebook-events", () => ({
  dispatchNotebookPagesChanged: (...args: unknown[]) =>
    dispatchNotebookPagesChanged(...args),
  dispatchNotebooksChanged: () => dispatchNotebooksChanged(),
}));

import OnboardingWizard from "@/components/onboarding/OnboardingWizard";

describe("OnboardingWizard", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    cleanup();
  });

  it("stays on notebook creation when notebook bootstrap fails", async () => {
    apiPost.mockRejectedValueOnce(new Error("create notebook failed"));

    render(<OnboardingWizard />);

    fireEvent.click(screen.getByTestId("onboarding-next"));
    fireEvent.change(screen.getByTestId("onboarding-client-name"), {
      target: { value: "Notebook Alpha" },
    });
    fireEvent.click(screen.getByTestId("onboarding-next"));

    await waitFor(() => {
      expect(screen.getByTestId("onboarding-error").textContent).toContain(
        "notebooks.createFailed",
      );
    });
    expect(screen.getByTestId("onboarding-client-name")).toBeTruthy();
    expect(screen.queryByTestId("onboarding-note-text")).toBeNull();
    expect(markCompleted).not.toHaveBeenCalled();
    expect(dispatchNotebooksChanged).not.toHaveBeenCalled();
  });

  it("stays on page creation when first page bootstrap fails", async () => {
    apiPost
      .mockResolvedValueOnce({ id: "nb-1" })
      .mockRejectedValueOnce(new Error("create page failed"));

    render(<OnboardingWizard />);

    fireEvent.click(screen.getByTestId("onboarding-next"));
    fireEvent.change(screen.getByTestId("onboarding-client-name"), {
      target: { value: "Notebook Alpha" },
    });
    fireEvent.click(screen.getByTestId("onboarding-next"));

    await waitFor(() => {
      expect(screen.getByTestId("onboarding-note-text")).toBeTruthy();
    });

    fireEvent.change(screen.getByTestId("onboarding-note-text"), {
      target: { value: "First real note" },
    });
    fireEvent.click(screen.getByTestId("onboarding-next"));

    await waitFor(() => {
      expect(screen.getByTestId("onboarding-error").textContent).toContain(
        "pages.createFailed",
      );
    });
    expect(screen.getByTestId("onboarding-note-text")).toBeTruthy();
    expect(markCompleted).not.toHaveBeenCalled();
    expect(dispatchNotebookPagesChanged).toHaveBeenCalledTimes(1);
  });
});
