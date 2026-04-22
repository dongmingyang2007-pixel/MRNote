import { act, render, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const apiGet = vi.fn();
const apiPost = vi.fn();

vi.mock("@/lib/api", () => ({
  apiGet: (...args: unknown[]) => apiGet(...args),
  apiPost: (...args: unknown[]) => apiPost(...args),
}));

import {
  getScopedOnboardingKey,
  useOnboardingStatus,
} from "@/hooks/useOnboardingStatus";

function Harness({
  onReady,
}: {
  onReady: (api: ReturnType<typeof useOnboardingStatus>) => void;
}) {
  const api = useOnboardingStatus();
  onReady(api);
  return null;
}

function clearAllCookies() {
  document.cookie
    .split(";")
    .map((cookie) => cookie.trim().split("=")[0])
    .filter(Boolean)
    .forEach((name) => {
      document.cookie = `${name}=; Max-Age=0; Path=/`;
    });
}

describe("useOnboardingStatus", () => {
  beforeEach(() => {
    clearAllCookies();
    window.localStorage.clear();
    vi.clearAllMocks();
  });

  it("does not reuse onboarding completion across users in the same browser", async () => {
    document.cookie = "mingrun_workspace_id=ws-1; Path=/";
    window.localStorage.setItem(
      getScopedOnboardingKey("user-1", "ws-1"),
      "1",
    );
    apiGet.mockResolvedValue({
      id: "user-2",
      onboarding_completed_at: null,
    });

    let latest: ReturnType<typeof useOnboardingStatus> | null = null;
    render(<Harness onReady={(api) => (latest = api)} />);

    await waitFor(() => {
      expect(latest?.completed).toBe(false);
    });
  });

  it("persists onboarding completion to a user+workspace scoped key", async () => {
    document.cookie = "mingrun_workspace_id=ws-9; Path=/";
    apiGet.mockResolvedValue({
      id: "user-9",
      onboarding_completed_at: null,
    });
    apiPost.mockResolvedValue({});

    let latest: ReturnType<typeof useOnboardingStatus> | null = null;
    render(<Harness onReady={(api) => (latest = api)} />);

    await waitFor(() => {
      expect(latest?.completed).toBe(false);
    });

    await act(async () => {
      await latest?.markCompleted();
    });

    expect(
      window.localStorage.getItem(getScopedOnboardingKey("user-9", "ws-9")),
    ).toBe("1");
    expect(apiPost).toHaveBeenCalledWith(
      "/api/v1/auth/onboarding/complete",
      {},
    );
  });
});
