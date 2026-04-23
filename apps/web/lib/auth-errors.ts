import { isApiRequestError } from "@/lib/api";

type TranslationFn = (
  key: string,
  values?: Record<string, string | number>,
) => string;

export function getLocalizedAuthError(
  error: unknown,
  t: TranslationFn,
  fallbackKey: string,
): string {
  if (!isApiRequestError(error)) {
    return error instanceof Error ? error.message : t(fallbackKey);
  }

  switch (error.code) {
    case "invalid_credentials":
      return t("common.errors.invalidCredentials");
    case "invalid_code":
      return t("common.errors.invalidCode");
    case "email_exists":
      // Post-audit /register no longer returns this; kept to handle any
      // non-register caller that still surfaces it.
      return t("common.errors.emailExists");
    case "disposable_email":
      return t("common.errors.disposableEmail");
    case "rate_limited":
      return t("common.errors.rateLimited");
    default:
      return error.message || t(fallbackKey);
  }
}
