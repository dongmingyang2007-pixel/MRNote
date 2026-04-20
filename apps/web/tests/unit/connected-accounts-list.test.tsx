import { render, screen, waitFor, fireEvent, cleanup } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("next-intl", () => ({
  useTranslations: () => (key: string, values?: Record<string, string>) => {
    if (values?.date) return `${key}:${values.date}`;
    return key;
  },
}));

vi.mock("@/lib/api", () => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
  apiPut: vi.fn(),
  apiDelete: vi.fn(),
  ApiRequestError: class extends Error {
    status: number;
    code?: string;
    constructor(message: string, opts: { status: number; code?: string }) {
      super(message);
      this.status = opts.status;
      this.code = opts.code;
    }
  },
  isApiRequestError: (e: unknown): e is { status: number; code?: string } =>
    e instanceof Error && "status" in e,
}));

import { apiGet, apiPost, apiPut, ApiRequestError } from "@/lib/api";
import ConnectedAccountsList from "@/components/settings/ConnectedAccountsList";

beforeEach(() => {
  vi.mocked(apiGet).mockReset();
  vi.mocked(apiPost).mockReset();
  vi.mocked(apiPut).mockReset();
});
afterEach(() => cleanup());

describe("ConnectedAccountsList", () => {
  it("renders Connect button when no identities", async () => {
    vi.mocked(apiGet).mockResolvedValue([]);
    render(<ConnectedAccountsList />);
    await waitFor(() => {
      expect(screen.getByTestId("oauth-connect-google")).toBeDefined();
    });
  });

  it("renders Disconnect row when Google is linked", async () => {
    vi.mocked(apiGet).mockResolvedValue([
      {
        id: "oid1",
        provider: "google",
        provider_email: "x@y.com",
        linked_at: "2026-04-18T10:00:00Z",
      },
    ]);
    render(<ConnectedAccountsList />);
    await waitFor(() => {
      expect(screen.getByTestId("oauth-disconnect-google")).toBeDefined();
      expect(screen.getByText("x@y.com")).toBeDefined();
    });
  });

  it("shows set-password inline form when disconnect returns password_required", async () => {
    vi.mocked(apiGet).mockResolvedValue([
      {
        id: "oid1",
        provider: "google",
        provider_email: "x@y.com",
        linked_at: "2026-04-18T10:00:00Z",
      },
    ]);
    vi.mocked(apiPost).mockRejectedValueOnce(
      new (ApiRequestError as unknown as typeof Error)(
        "Please set a password",
        // @ts-expect-error test helper ctor
        { status: 409, code: "password_required" },
      ),
    );

    render(<ConnectedAccountsList />);
    await waitFor(() => screen.getByTestId("oauth-disconnect-google"));
    fireEvent.click(screen.getByTestId("oauth-disconnect-google"));

    await waitFor(() => screen.getByTestId("oauth-disconnect-confirm"));
    fireEvent.click(screen.getByTestId("oauth-disconnect-confirm"));

    await waitFor(() => {
      expect(screen.getByTestId("oauth-set-password-form")).toBeDefined();
    });
  });
});
