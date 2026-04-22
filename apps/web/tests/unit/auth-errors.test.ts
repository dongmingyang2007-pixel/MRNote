import { describe, expect, it } from "vitest";
import { ApiRequestError } from "@/lib/api";
import { getLocalizedAuthError } from "@/lib/auth-errors";

const t = (key: string) => key;

describe("getLocalizedAuthError", () => {
  it("maps known auth error codes to localized keys", () => {
    const error = new ApiRequestError("Invalid email or password", {
      status: 401,
      code: "invalid_credentials",
    });
    expect(getLocalizedAuthError(error, t, "login.error")).toBe(
      "common.errors.invalidCredentials",
    );
  });

  it("falls back to the original message for unknown API errors", () => {
    const error = new ApiRequestError("Something else", {
      status: 400,
      code: "other_error",
    });
    expect(getLocalizedAuthError(error, t, "login.error")).toBe("Something else");
  });
});
