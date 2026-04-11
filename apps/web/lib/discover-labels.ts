/**
 * Shared label maps and helpers for the Discover pages.
 *
 * Every helper that needs translated strings accepts a plain
 * `t: (key: string) => string` so callers can pass the scoped
 * `useTranslations("console")` value without coupling this module
 * to next-intl.
 */

/* ------------------------------------------------------------------ */
/*  Session-storage key used by the model-picker flow                 */
/* ------------------------------------------------------------------ */

export const MODEL_PICKER_SELECTION_KEY = "model_picker_pending_selection";

/* ------------------------------------------------------------------ */
/*  Taxonomy category map  (15 entries)                               */
/* ------------------------------------------------------------------ */

const TAXONOMY_CATEGORY_MAP: Record<string, string> = {
  omni: "discover.taxonomy.omni",
  deep_thinking: "discover.taxonomy.deepThinking",
  text_generation: "discover.taxonomy.textGeneration",
  vision: "discover.taxonomy.vision",
  image_generation: "discover.taxonomy.imageGeneration",
  video_generation: "discover.taxonomy.videoGeneration",
  speech_recognition: "discover.taxonomy.speechRecognition",
  speech_synthesis: "discover.taxonomy.speechSynthesis",
  multimodal_embedding: "discover.taxonomy.multimodalEmbedding",
  text_embedding: "discover.taxonomy.textEmbedding",
  realtime_omni: "discover.taxonomy.realtimeOmni",
  realtime_tts: "discover.taxonomy.realtimeTts",
  realtime_asr: "discover.taxonomy.realtimeAsr",
  realtime_translate: "discover.taxonomy.realtimeTranslate",
  rerank: "discover.taxonomy.rerank",
};

/**
 * Translate a category key.
 * When `locale` does not start with "en" the `fallback` is returned as-is.
 */
export function categoryLabel(
  categoryKey: string | null | undefined,
  fallback: string | null | undefined,
  locale: string,
  t: (key: string) => string,
): string {
  if (!locale.startsWith("en")) {
    return fallback || "";
  }
  return categoryKey && TAXONOMY_CATEGORY_MAP[categoryKey]
    ? t(TAXONOMY_CATEGORY_MAP[categoryKey])
    : (fallback || "");
}

/* ------------------------------------------------------------------ */
/*  Group label map                                                   */
/* ------------------------------------------------------------------ */

const GROUP_MAP: Record<string, string> = {
  multimodal: "discover.group.multimodal",
  text: "discover.group.text",
  vision: "discover.group.vision",
  speech: "discover.group.speech",
  embedding: "discover.group.embedding",
  realtime: "discover.group.realtime",
};

/**
 * Translate a group key.
 */
export function groupLabel(
  groupKey: string | null | undefined,
  fallback: string | null | undefined,
  locale: string,
  t: (key: string) => string,
): string {
  if (!locale.startsWith("en")) {
    return fallback || "";
  }
  return groupKey && GROUP_MAP[groupKey]
    ? t(GROUP_MAP[groupKey])
    : (fallback || "");
}

/* ------------------------------------------------------------------ */
/*  Capability / tool label map                                       */
/* ------------------------------------------------------------------ */

const CAPABILITY_MAP: Record<string, string> = {
  function_calling: "modelDetail.tool.functionCalling",
  web_search: "modelDetail.tool.webSearch",
  deep_thinking: "modelDetail.feature.deepThinking",
  streaming: "modelDetail.feature.streaming",
  structured_output: "modelDetail.feature.structuredOutput",
  cache: "modelDetail.feature.cache",
  ranking: "modelDetail.feature.ranking",
};

/**
 * Translate a capability / tool / feature token.
 */
export function capabilityLabel(
  token: string,
  t: (key: string) => string,
): string {
  return CAPABILITY_MAP[token] ? t(CAPABILITY_MAP[token]) : token;
}

/* ------------------------------------------------------------------ */
/*  Modality label map (used only by the detail page's labelForToken) */
/* ------------------------------------------------------------------ */

const MODALITY_MAP: Record<string, string> = {
  text: "modelDetail.text",
  image: "modelDetail.image",
  audio: "modelDetail.audio",
  video: "modelDetail.video",
};

/**
 * Translate a modality or capability token (union of both maps).
 */
export function labelForToken(
  token: string,
  t: (key: string) => string,
): string {
  if (MODALITY_MAP[token]) {
    return t(MODALITY_MAP[token]);
  }
  if (CAPABILITY_MAP[token]) {
    return t(CAPABILITY_MAP[token]);
  }
  return token;
}

/* ------------------------------------------------------------------ */
/*  Pipeline slot → scene label map                                   */
/* ------------------------------------------------------------------ */

const SCENE_MAP: Record<string, string> = {
  llm: "discover.scene.llm",
  asr: "discover.scene.asr",
  tts: "discover.scene.tts",
  vision: "discover.scene.vision",
  realtime: "discover.scene.realtime",
  realtime_asr: "discover.scene.realtime_asr",
  realtime_tts: "discover.scene.realtime_tts",
};

/**
 * Translate a pipeline_slot key to a user-friendly scene name.
 */
export function sceneLabel(
  slot: string,
  t: (key: string) => string,
): string {
  return SCENE_MAP[slot] ? t(SCENE_MAP[slot]) : slot;
}

/* ------------------------------------------------------------------ */
/*  Allowed tokens for discover page model cards                      */
/* ------------------------------------------------------------------ */

/**
 * Tokens allowed on discover page model cards.
 * Technical tokens (streaming, structured_output, cache, ranking) are excluded.
 */
const ALLOWED_CARD_TOKENS = new Set([
  "text",
  "image",
  "audio",
  "video",
  "function_calling",
  "web_search",
  "deep_thinking",
]);

/**
 * Filter tokens to only those appropriate for consumer-facing cards.
 */
export function filterCardTokens(tokens: string[]): string[] {
  return tokens.filter((token) => ALLOWED_CARD_TOKENS.has(token));
}

/* ------------------------------------------------------------------ */
/*  Provider display label                                            */
/* ------------------------------------------------------------------ */

/**
 * Return a human-friendly provider name.
 * For English locales certain providers get special treatment;
 * otherwise the API-supplied `fallback` is used.
 */
export function providerDisplayLabel(
  provider: string,
  fallback: string,
  locale: string,
  t: (key: string) => string,
): string {
  if (!locale.startsWith("en")) {
    return fallback || provider;
  }
  if (provider.includes("qwen") || provider.includes("alibaba")) {
    return t("discover.provider.qwen");
  }
  if (provider.includes("deepseek")) {
    return "DeepSeek";
  }
  return fallback || provider;
}
