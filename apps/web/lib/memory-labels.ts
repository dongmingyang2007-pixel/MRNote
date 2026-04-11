"use client";

type TranslationScope = "graph" | "memory";

const MEMORY_KIND_KEYS: Record<string, string> = {
  profile: "kindProfile",
  preference: "kindPreference",
  goal: "kindGoal",
  episodic: "kindEpisodic",
  fact: "kindFact",
  summary: "kindSummary",
};

const SUBJECT_KIND_KEYS: Record<string, string> = {
  user: "subjectKindUser",
  custom: "subjectKindCustom",
  book: "subjectKindBook",
  course: "subjectKindCourse",
  project: "subjectKindProject",
  theory: "subjectKindTheory",
  paper: "subjectKindPaper",
  device: "subjectKindDevice",
  person: "subjectKindPerson",
  domain: "subjectKindDomain",
  assistant: "subjectKindAssistant",
  group: "subjectKindGroup",
  place: "subjectKindPlace",
};

type Translator = (key: string) => string;

export function formatLocalizedMemoryKindLabel(
  kind: string | null | undefined,
  t: Translator,
  scope: TranslationScope,
): string {
  const normalized = String(kind || "").trim().toLowerCase();
  if (!normalized) {
    return t(`${scope}.kindUnknown`);
  }
  const key = MEMORY_KIND_KEYS[normalized];
  return key ? t(`${scope}.${key}`) : String(kind);
}

export function formatLocalizedSubjectKindLabel(
  kind: string | null | undefined,
  t: Translator,
  scope: TranslationScope,
): string {
  const normalized = String(kind || "").trim().toLowerCase();
  if (!normalized) {
    return "";
  }
  const key = SUBJECT_KIND_KEYS[normalized];
  return key ? t(`${scope}.${key}`) : String(kind);
}

export function formatLocalizedCategorySegmentLabel(
  segment: string,
  t: Translator,
  scope: TranslationScope,
): string {
  const subjectKindLabel = formatLocalizedSubjectKindLabel(segment, t, scope);
  if (subjectKindLabel) {
    return subjectKindLabel;
  }
  return formatLocalizedMemoryKindLabel(segment, t, scope);
}

export function dedupeDisplayLabels<T extends { label: string }>(items: T[]): T[] {
  const seen = new Set<string>();
  return items.filter((item) => {
    const key = item.label.trim().toLowerCase();
    if (!key || seen.has(key)) {
      return false;
    }
    seen.add(key);
    return true;
  });
}
