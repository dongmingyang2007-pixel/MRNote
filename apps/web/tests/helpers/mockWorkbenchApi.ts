import type { Page, Route } from "@playwright/test";

const APP_ORIGIN = process.env.PLAYWRIGHT_BASE_URL || "http://localhost:3100";
const COOKIE_ORIGINS = expandLoopbackOrigins(APP_ORIGIN);
const DEBUG_API_MOCK = process.env.PLAYWRIGHT_DEBUG_API_MOCK === "1";

function expandLoopbackOrigins(origin: string): string[] {
  try {
    const url = new URL(origin);
    if (url.hostname !== "localhost" && url.hostname !== "127.0.0.1") {
      return [origin];
    }
    const variants = ["localhost", "127.0.0.1"].map((hostname) => {
      const next = new URL(origin);
      next.hostname = hostname;
      return next.origin;
    });
    return Array.from(new Set(variants));
  } catch {
    return [origin];
  }
}

type Project = {
  id: string;
  name: string;
  description?: string;
  default_chat_mode: "standard" | "omni_realtime" | "synthetic_realtime";
  assistant_root_memory_id?: string | null;
  created_at: string;
};

type Dataset = {
  id: string;
  project_id: string;
  name: string;
  type: string;
  created_at: string;
};

type DatasetVersion = {
  id: string;
  dataset_id: string;
  version: number;
};

type DataItem = {
  id: string;
  dataset_id: string;
  filename: string;
  media_type: string;
  size_bytes: number;
  download_url: string;
  preview_url?: string | null;
  created_at: string;
};

type Job = {
  id: string;
  project_id: string;
  dataset_version_id: string;
  recipe: string;
  status: "pending" | "running" | "succeeded" | "failed" | "canceled";
  created_at: string;
};

type Model = {
  id: string;
  project_id: string;
  name: string;
  task_type: string;
  created_at: string;
};

type ModelAlias = {
  alias: "prod" | "staging" | "dev";
  model_version_id: string;
};

type ModelVersion = {
  id: string;
  version: number;
};

type Conversation = {
  id: string;
  project_id: string;
  title: string;
  updated_at: string;
};

type PipelineConfigItem = {
  id: string;
  project_id: string;
  model_type:
    | "llm"
    | "asr"
    | "tts"
    | "vision"
    | "realtime"
    | "realtime_asr"
    | "realtime_tts";
  model_id: string;
  config_json: Record<string, unknown>;
  created_at: string;
  updated_at: string;
};

type CatalogModel = {
  id: string;
  model_id: string;
  canonical_model_id?: string;
  display_name: string;
  provider: string;
  provider_display?: string;
  official_group_key?: string;
  category:
    | "llm"
    | "asr"
    | "tts"
    | "vision"
    | "realtime"
    | "realtime_asr"
    | "realtime_tts";
  description: string;
  capabilities: string[];
  official_group?: string;
  official_category_key?: string;
  official_category?: string;
  official_order?: number;
  official_url?: string;
  aliases?: string[];
  pipeline_slot?:
    | "llm"
    | "asr"
    | "tts"
    | "vision"
    | "realtime"
    | "realtime_asr"
    | "realtime_tts"
    | null;
  is_selectable_in_console?: boolean;
  supported_tools?: string[];
  supported_features?: string[];
  input_price: number;
  output_price: number;
  context_window: number;
  max_output: number;
  input_modalities?: string[];
  output_modalities?: string[];
  supports_function_calling?: boolean;
  supports_web_search?: boolean;
  supports_structured_output?: boolean;
  supports_cache?: boolean;
  batch_input_price?: number | null;
  batch_output_price?: number | null;
  cache_read_price?: number | null;
  cache_write_price?: number | null;
  price_unit?: string;
  price_note?: string | null;
};

type MemoryNode = {
  id: string;
  workspace_id: string;
  project_id: string;
  content: string;
  category: string;
  type: "permanent" | "temporary";
  source_conversation_id: string | null;
  parent_memory_id: string | null;
  position_x: number | null;
  position_y: number | null;
  metadata_json: Record<string, unknown>;
  created_at: string;
  updated_at: string;
};

type MemoryWorkbenchView = {
  id: string;
  source_subject_id?: string | null;
  view_type: string;
  content: string;
  metadata_json?: {
    source_memory_ids?: string[];
    memory_count?: number;
  } | null;
  created_at: string;
  updated_at: string;
};

type MemoryEvidenceItem = {
  id: string;
  memory_id: string;
  source_type: string;
  message_role?: string | null;
  quote_text: string;
  confidence?: number | null;
  created_at: string;
};

type MemoryLearningRun = {
  id: string;
  trigger: string;
  status: string;
  stages?: string[];
  used_memory_ids?: string[];
  promoted_memory_ids?: string[];
  degraded_memory_ids?: string[];
  outcome_id?: string | null;
  error?: string | null;
  task_id?: string | null;
  message_id?: string | null;
  started_at?: string | null;
  completed_at?: string | null;
  metadata_json?: Record<string, unknown>;
};

type MemoryHealthEntry = {
  kind: string;
  reason: string;
  memory?: MemoryNode | null;
  view?: {
    id: string;
    view_type: string;
    content: string;
    source_subject_id?: string | null;
    metadata_json?: Record<string, unknown> | null;
    updated_at?: string | null;
  } | null;
};

type MemoryHealthPayload = {
  counts?: Record<string, number>;
  entries?: MemoryHealthEntry[];
};

type MemoryDetailPayload = Record<string, unknown>;

type ChatMessage = {
  id: string;
  conversation_id: string;
  role: "user" | "assistant";
  content: string;
  reasoning_content?: string | null;
  metadata_json?: Record<string, unknown>;
  created_at: string;
};

type MockDb = {
  workspaceId: string;
  projects: Project[];
  conversationsByProjectId: Record<string, Conversation[]>;
  messagesByConversationId: Record<string, ChatMessage[]>;
  datasets: Dataset[];
  dataItemsByDatasetId: Record<string, DataItem[]>;
  datasetVersions: DatasetVersion[];
  jobs: Job[];
  models: Model[];
  modelAliasesById: Record<string, ModelAlias[]>;
  modelVersionsById: Record<string, ModelVersion[]>;
  pipelineConfigs: PipelineConfigItem[];
  modelCatalog: CatalogModel[];
  memoryNodesByProjectId: Record<string, MemoryNode[]>;
  memoryViewsByProjectId: Record<string, MemoryWorkbenchView[]>;
  memoryEvidencesByProjectId: Record<string, MemoryEvidenceItem[]>;
  memoryLearningRunsByProjectId: Record<string, MemoryLearningRun[]>;
  memoryHealthByProjectId: Record<string, MemoryHealthPayload>;
  memoryDetailsById: Record<string, MemoryDetailPayload>;
  counters: Record<string, number>;
};

export type MockWorkbenchHandle = {
  workspaceId: string;
  seedProjectId: string;
};

function nowIso(): string {
  return "2026-03-14T12:00:00.000Z";
}

function nextId(db: MockDb, prefix: string): string {
  db.counters[prefix] = (db.counters[prefix] || 0) + 1;
  return `${prefix}-${String(db.counters[prefix]).padStart(3, "0")}`;
}

function createMockDb(): MockDb {
  const workspaceId = "ws-playwright";
  const seedProjectId = "proj-seed";
  const seedRootMemoryId = "memory-root-seed";
  const seedDatasetId = "dataset-seed";
  const seedVersionId = "dsv-seed";
  const seedModelId = "model-seed";
  const seedModelVersionId = "model-version-seed";

  return {
    workspaceId,
    projects: [
      {
        id: seedProjectId,
        name: "Seed Console Project",
        description: "Default workspace project",
        default_chat_mode: "standard",
        assistant_root_memory_id: seedRootMemoryId,
        created_at: nowIso(),
      },
    ],
    conversationsByProjectId: {
      [seedProjectId]: [],
    },
    messagesByConversationId: {},
    datasets: [
      {
        id: seedDatasetId,
        project_id: seedProjectId,
        name: "Seed Dataset",
        type: "images",
        created_at: nowIso(),
      },
    ],
    dataItemsByDatasetId: {
      [seedDatasetId]: [],
    },
    datasetVersions: [
      {
        id: seedVersionId,
        dataset_id: seedDatasetId,
        version: 1,
      },
    ],
    jobs: [
      {
        id: "job-seed",
        project_id: seedProjectId,
        dataset_version_id: seedVersionId,
        recipe: "baseline",
        status: "succeeded",
        created_at: nowIso(),
      },
    ],
    models: [
      {
        id: seedModelId,
        project_id: seedProjectId,
        name: "Seed Model",
        task_type: "general",
        created_at: nowIso(),
      },
    ],
    modelAliasesById: {
      [seedModelId]: [{ alias: "prod", model_version_id: seedModelVersionId }],
    },
    modelVersionsById: {
      [seedModelId]: [{ id: seedModelVersionId, version: 3 }],
    },
    pipelineConfigs: [
      {
        id: "pipe-llm-seed",
        project_id: seedProjectId,
        model_type: "llm",
        model_id: "qwen3.5-plus",
        config_json: {},
        created_at: nowIso(),
        updated_at: nowIso(),
      },
      {
        id: "pipe-asr-seed",
        project_id: seedProjectId,
        model_type: "asr",
        model_id: "paraformer-v2",
        config_json: {},
        created_at: nowIso(),
        updated_at: nowIso(),
      },
      {
        id: "pipe-tts-seed",
        project_id: seedProjectId,
        model_type: "tts",
        model_id: "cosyvoice",
        config_json: {},
        created_at: nowIso(),
        updated_at: nowIso(),
      },
      {
        id: "pipe-vision-seed",
        project_id: seedProjectId,
        model_type: "vision",
        model_id: "qwen-vl-plus",
        config_json: {},
        created_at: nowIso(),
        updated_at: nowIso(),
      },
      {
        id: "pipe-realtime-seed",
        project_id: seedProjectId,
        model_type: "realtime",
        model_id: "qwen3-omni-flash-realtime",
        config_json: {},
        created_at: nowIso(),
        updated_at: nowIso(),
      },
      {
        id: "pipe-realtime-asr-seed",
        project_id: seedProjectId,
        model_type: "realtime_asr",
        model_id: "qwen3-asr-flash-realtime",
        config_json: {},
        created_at: nowIso(),
        updated_at: nowIso(),
      },
      {
        id: "pipe-realtime-tts-seed",
        project_id: seedProjectId,
        model_type: "realtime_tts",
        model_id: "qwen3-tts-flash-realtime",
        config_json: {},
        created_at: nowIso(),
        updated_at: nowIso(),
      },
    ],
    modelCatalog: [
      {
        id: "catalog-qwen3.5-plus",
        model_id: "qwen3.5-plus",
        canonical_model_id: "qwen3.5-plus",
        display_name: "Qwen3.5-Plus",
        provider: "qwen",
        provider_display: "千问 · 阿里云",
        category: "llm",
        description: "均衡的旗舰级通用模型，支持视觉、视频理解、函数调用和联网搜索。",
        capabilities: ["chat", "vision", "video", "function_calling", "web_search"],
        official_group_key: "text",
        official_group: "文本",
        official_category_key: "text_generation",
        official_category: "文本生成",
        official_order: 3002,
        official_url: "https://help.aliyun.com/zh/model-studio/text-generation",
        aliases: ["qwen3-plus"],
        pipeline_slot: "llm",
        is_selectable_in_console: true,
        supported_tools: ["function_calling", "web_search"],
        supported_features: ["streaming", "deep_thinking", "structured_output", "cache"],
        input_price: 0.004,
        output_price: 0.012,
        context_window: 131072,
        max_output: 8192,
        input_modalities: ["text", "image", "video"],
        output_modalities: ["text"],
        supports_function_calling: true,
        supports_web_search: true,
        supports_structured_output: true,
        supports_cache: true,
        batch_input_price: null,
        batch_output_price: null,
        cache_read_price: null,
        cache_write_price: null,
        price_unit: "tokens",
        price_note: null,
      },
      {
        id: "catalog-qwen-max",
        model_id: "qwen-max",
        canonical_model_id: "qwen-max",
        display_name: "Qwen Max",
        provider: "qwen",
        provider_display: "千问 · 阿里云",
        category: "llm",
        description: "更强的推理与更长上下文能力。",
        capabilities: ["chat", "vision", "function_calling"],
        official_group_key: "text",
        official_group: "文本",
        official_category_key: "text_generation",
        official_category: "文本生成",
        official_order: 3001,
        official_url: "https://help.aliyun.com/zh/model-studio/text-generation",
        aliases: [],
        pipeline_slot: "llm",
        is_selectable_in_console: true,
        supported_tools: ["function_calling", "web_search"],
        supported_features: ["streaming", "deep_thinking", "structured_output", "cache"],
        input_price: 0.008,
        output_price: 0.024,
        context_window: 262144,
        max_output: 16384,
        input_modalities: ["text", "image"],
        output_modalities: ["text"],
        supports_function_calling: true,
        supports_web_search: true,
        supports_structured_output: true,
        supports_cache: true,
        batch_input_price: null,
        batch_output_price: null,
        cache_read_price: null,
        cache_write_price: null,
        price_unit: "tokens",
        price_note: null,
      },
      {
        id: "catalog-qwen3-omni-flash-realtime",
        model_id: "qwen3-omni-flash-realtime",
        canonical_model_id: "qwen3-omni-flash-realtime",
        display_name: "Qwen3-Omni-Flash-Realtime",
        provider: "qwen",
        provider_display: "千问 · 阿里云",
        category: "llm",
        description: "端到端全模态实时模型，直接接收语音并直接输出语音与文本。",
        capabilities: ["chat", "vision", "audio_input", "audio_output", "realtime"],
        official_group_key: "realtime",
        official_group: "Realtime",
        official_category_key: "realtime_omni",
        official_category: "实时全模态",
        official_order: 11001,
        official_url: "https://help.aliyun.com/zh/model-studio/qwen-omni",
        aliases: [],
        pipeline_slot: "realtime",
        is_selectable_in_console: true,
        supported_tools: [],
        supported_features: ["streaming"],
        input_price: 0.0022,
        output_price: 0.0083,
        context_window: 131072,
        max_output: 8192,
        input_modalities: ["text", "image", "audio"],
        output_modalities: ["text", "audio"],
        supports_function_calling: false,
        supports_web_search: false,
        supports_structured_output: false,
        supports_cache: false,
        batch_input_price: null,
        batch_output_price: null,
        cache_read_price: null,
        cache_write_price: null,
        price_unit: "tokens",
        price_note: null,
      },
      {
        id: "catalog-qwen3-asr-flash-realtime",
        model_id: "qwen3-asr-flash-realtime",
        canonical_model_id: "qwen3-asr-flash-realtime",
        display_name: "Qwen3-ASR-Flash-Realtime",
        provider: "qwen",
        provider_display: "千问 · 阿里云",
        category: "realtime_asr",
        description: "实时语音识别模型，适合持续语音流输入。",
        capabilities: ["asr", "realtime_asr"],
        official_group_key: "realtime",
        official_group: "Realtime",
        official_category_key: "realtime_asr",
        official_category: "实时语音识别",
        official_order: 11011,
        official_url: "https://help.aliyun.com/zh/model-studio/models",
        aliases: [],
        pipeline_slot: "realtime_asr",
        is_selectable_in_console: true,
        supported_tools: [],
        supported_features: ["streaming"],
        input_price: 0,
        output_price: 0,
        context_window: 0,
        max_output: 0,
        input_modalities: ["audio"],
        output_modalities: ["text"],
        supports_function_calling: false,
        supports_web_search: false,
        supports_structured_output: false,
        supports_cache: false,
        batch_input_price: null,
        batch_output_price: null,
        cache_read_price: null,
        cache_write_price: null,
        price_unit: "audio",
        price_note: "按音频时长计费",
      },
      {
        id: "catalog-qwen3-tts-flash-realtime",
        model_id: "qwen3-tts-flash-realtime",
        canonical_model_id: "qwen3-tts-flash-realtime",
        display_name: "Qwen3-TTS-Flash-Realtime",
        provider: "qwen",
        provider_display: "千问 · 阿里云",
        category: "realtime_tts",
        description: "实时语音合成模型，适合低延迟分段播放。",
        capabilities: ["tts", "realtime_tts"],
        official_group_key: "realtime",
        official_group: "Realtime",
        official_category_key: "realtime_tts",
        official_category: "实时语音合成",
        official_order: 11012,
        official_url: "https://help.aliyun.com/zh/model-studio/models",
        aliases: [],
        pipeline_slot: "realtime_tts",
        is_selectable_in_console: true,
        supported_tools: [],
        supported_features: ["streaming"],
        input_price: 0,
        output_price: 0,
        context_window: 0,
        max_output: 0,
        input_modalities: ["text"],
        output_modalities: ["audio"],
        supports_function_calling: false,
        supports_web_search: false,
        supports_structured_output: false,
        supports_cache: false,
        batch_input_price: null,
        batch_output_price: null,
        cache_read_price: null,
        cache_write_price: null,
        price_unit: "characters",
        price_note: "按字符计费",
      },
      {
        id: "catalog-qwen-vl-plus",
        model_id: "qwen-vl-plus",
        canonical_model_id: "qwen-vl-plus",
        display_name: "Qwen VL Plus",
        provider: "qwen",
        provider_display: "千问 · 阿里云",
        category: "vision",
        description: "通用视觉理解模型。",
        capabilities: ["vision"],
        official_group_key: "vision",
        official_group: "视觉",
        official_category_key: "vision",
        official_category: "视觉理解",
        official_order: 4002,
        official_url: "https://help.aliyun.com/zh/model-studio/models",
        aliases: [],
        pipeline_slot: "vision",
        is_selectable_in_console: true,
        supported_tools: [],
        supported_features: ["streaming"],
        input_price: 0,
        output_price: 0,
        context_window: 32768,
        max_output: 4096,
        input_modalities: ["image", "text"],
        output_modalities: ["text"],
        supports_function_calling: false,
        supports_web_search: false,
        supports_structured_output: false,
        supports_cache: false,
        batch_input_price: null,
        batch_output_price: null,
        cache_read_price: null,
        cache_write_price: null,
        price_unit: "tokens",
        price_note: null,
      },
      {
        id: "catalog-qwen3-vl-plus",
        model_id: "qwen3-vl-plus",
        canonical_model_id: "qwen3-vl-plus",
        display_name: "Qwen3-VL-Plus",
        provider: "qwen",
        provider_display: "千问 · 阿里云",
        category: "vision",
        description: "新一代视觉理解模型，支持图像、OCR、视频与更强的视觉推理能力。",
        capabilities: ["vision", "ocr", "video", "thinking"],
        official_group_key: "vision",
        official_group: "视觉",
        official_category_key: "vision",
        official_category: "视觉理解",
        official_order: 4003,
        official_url: "https://help.aliyun.com/zh/model-studio/models",
        aliases: [],
        pipeline_slot: "vision",
        is_selectable_in_console: true,
        supported_tools: [],
        supported_features: ["streaming", "deep_thinking"],
        input_price: 0.001,
        output_price: 0.01,
        context_window: 32768,
        max_output: 4096,
        input_modalities: ["image", "video"],
        output_modalities: ["text"],
        supports_function_calling: false,
        supports_web_search: false,
        supports_structured_output: false,
        supports_cache: false,
        batch_input_price: null,
        batch_output_price: null,
        cache_read_price: null,
        cache_write_price: null,
        price_unit: "tokens",
        price_note: null,
      },
      {
        id: "catalog-paraformer-v2",
        model_id: "paraformer-v2",
        display_name: "Paraformer-v2",
        provider: "alibaba",
        provider_display: "千问 · 阿里云",
        category: "asr",
        description: "实时语音识别模型，支持中英文混合输入。",
        capabilities: ["asr"],
        input_price: 0,
        output_price: 0,
        context_window: 0,
        max_output: 0,
        input_modalities: ["audio"],
        output_modalities: ["text"],
        supports_function_calling: false,
        supports_web_search: false,
        supports_structured_output: false,
        supports_cache: false,
        batch_input_price: null,
        batch_output_price: null,
        cache_read_price: null,
        cache_write_price: null,
        price_unit: "audio",
        price_note: "免费额度",
      },
      {
        id: "catalog-cosyvoice",
        model_id: "cosyvoice",
        display_name: "CosyVoice",
        provider: "alibaba",
        provider_display: "千问 · 阿里云",
        category: "tts",
        description: "自然风格语音合成模型，支持多音色和情绪表达。",
        capabilities: ["tts"],
        input_price: 0,
        output_price: 0,
        context_window: 0,
        max_output: 0,
        input_modalities: ["text"],
        output_modalities: ["audio"],
        supports_function_calling: false,
        supports_web_search: false,
        supports_structured_output: false,
        supports_cache: false,
        batch_input_price: null,
        batch_output_price: null,
        cache_read_price: null,
        cache_write_price: null,
        price_unit: "characters",
        price_note: "按字符计费",
      },
    ],
    memoryNodesByProjectId: {
      [seedProjectId]: [
        {
          id: seedRootMemoryId,
          workspace_id: workspaceId,
          project_id: seedProjectId,
          content: "Seed Console Project",
          category: "assistant",
          type: "permanent",
          source_conversation_id: null,
          parent_memory_id: null,
          position_x: 0,
          position_y: 0,
          metadata_json: {
            node_kind: "assistant-root",
            assistant_name: "Seed Console Project",
            system_managed: true,
          },
          created_at: nowIso(),
          updated_at: nowIso(),
        },
      ],
    },
    memoryViewsByProjectId: {
      [seedProjectId]: [],
    },
    memoryEvidencesByProjectId: {
      [seedProjectId]: [],
    },
    memoryLearningRunsByProjectId: {
      [seedProjectId]: [],
    },
    memoryHealthByProjectId: {
      [seedProjectId]: { counts: {}, entries: [] },
    },
    memoryDetailsById: {},
    counters: {
      proj: 1,
      conv: 0,
      msg: 0,
      dataset: 1,
      dsv: 1,
      job: 1,
      model: 1,
      "model-version": 1,
      memory: 0,
    },
  };
}

async function fulfillJson(route: Route, payload: unknown, status = 200): Promise<void> {
  const request = route.request();
  const origin = request.headers()["origin"] || APP_ORIGIN;
  await route.fulfill({
    status,
    contentType: "application/json",
    headers: {
      "access-control-allow-origin": origin,
      "access-control-allow-credentials": "true",
      "access-control-allow-methods": "GET,POST,PUT,PATCH,DELETE,OPTIONS",
      "access-control-allow-headers": request.headers()["access-control-request-headers"] || "content-type,x-csrf-token,x-workspace-id",
      vary: "Origin",
    },
    body: JSON.stringify(payload),
  });
}

async function setAuthenticatedCookies(page: Page, workspaceId: string): Promise<void> {
  await page.context().addCookies(
    COOKIE_ORIGINS.flatMap((origin) => [
      {
        name: "auth_state",
        value: "1",
        url: origin,
        sameSite: "Lax" as const,
      },
      {
        name: "access_token",
        value: "playwright-access-token",
        url: origin,
        httpOnly: true,
        sameSite: "Lax" as const,
      },
      {
        name: "mingrun_workspace_id",
        value: workspaceId,
        url: origin,
        sameSite: "Lax" as const,
      },
    ]),
  );
}

function readJsonBody<T>(route: Route): T {
  const data = route.request().postDataJSON();
  return (data || {}) as T;
}

export async function installWorkbenchApiMock(
  page: Page,
  options: {
    authenticated?: boolean;
    seedConversations?: Array<{
      id: string;
      project_id?: string;
      title?: string;
      updated_at?: string;
    }>;
    seedMessagesByConversationId?: Record<string, ChatMessage[]>;
    seedMemoryNodes?: Array<Partial<MemoryNode> & {
      id: string;
      content: string;
      category: string;
      project_id?: string;
    }>;
    seedMemoryViews?: Array<Partial<MemoryWorkbenchView> & {
      id: string;
      content: string;
      view_type: string;
      project_id?: string;
    }>;
    seedMemoryEvidences?: Array<Partial<MemoryEvidenceItem> & {
      id: string;
      memory_id: string;
      source_type: string;
      quote_text: string;
      project_id?: string;
    }>;
    seedMemoryLearningRuns?: Array<Partial<MemoryLearningRun> & {
      id: string;
      trigger: string;
      status: string;
      project_id?: string;
    }>;
    seedMemoryHealth?: Record<string, MemoryHealthPayload>;
    seedMemoryDetails?: Record<string, MemoryDetailPayload>;
  } = {},
): Promise<MockWorkbenchHandle> {
  const db = createMockDb();
  if (Array.isArray(options.seedConversations)) {
    for (const conversation of options.seedConversations) {
      const projectId = conversation.project_id || db.projects[0]?.id || "";
      const seededConversation: Conversation = {
        id: conversation.id,
        project_id: projectId,
        title: conversation.title || "Seeded Conversation",
        updated_at: conversation.updated_at || nowIso(),
      };
      db.conversationsByProjectId[projectId] = [
        seededConversation,
        ...(db.conversationsByProjectId[projectId] || []).filter(
          (item) => item.id !== seededConversation.id,
        ),
      ];
      db.messagesByConversationId[seededConversation.id] =
        db.messagesByConversationId[seededConversation.id] || [];
    }
  }
  if (options.seedMessagesByConversationId) {
    for (const [conversationId, messages] of Object.entries(
      options.seedMessagesByConversationId,
    )) {
      db.messagesByConversationId[conversationId] = Array.isArray(messages)
        ? [...messages]
        : [];
    }
  }
  if (Array.isArray(options.seedMemoryNodes)) {
    for (const node of options.seedMemoryNodes) {
      const projectId = node.project_id || db.projects[0]?.id || "";
      const project = db.projects.find((item) => item.id === projectId);
      const seededNode: MemoryNode = {
        id: node.id,
        workspace_id: node.workspace_id || db.workspaceId,
        project_id: projectId,
        content: node.content,
        category: node.category,
        type: node.type || "permanent",
        source_conversation_id:
          node.source_conversation_id !== undefined
            ? node.source_conversation_id
            : null,
        parent_memory_id:
          node.parent_memory_id !== undefined
            ? node.parent_memory_id
            : (project?.assistant_root_memory_id || null),
        position_x: node.position_x !== undefined ? node.position_x : null,
        position_y: node.position_y !== undefined ? node.position_y : null,
        metadata_json: node.metadata_json || {},
        created_at: node.created_at || nowIso(),
        updated_at: node.updated_at || nowIso(),
      };
      db.memoryNodesByProjectId[projectId] = [
        ...(db.memoryNodesByProjectId[projectId] || []).filter(
          (item) => item.id !== seededNode.id,
        ),
        seededNode,
      ];
    }
  }
  if (Array.isArray(options.seedMemoryViews)) {
    for (const view of options.seedMemoryViews) {
      const projectId = view.project_id || db.projects[0]?.id || "";
      const seededView: MemoryWorkbenchView = {
        id: view.id,
        source_subject_id: view.source_subject_id ?? null,
        view_type: view.view_type,
        content: view.content,
        metadata_json: view.metadata_json ?? null,
        created_at: view.created_at || nowIso(),
        updated_at: view.updated_at || nowIso(),
      };
      db.memoryViewsByProjectId[projectId] = [
        ...(db.memoryViewsByProjectId[projectId] || []).filter(
          (item) => item.id !== seededView.id,
        ),
        seededView,
      ];
    }
  }
  if (Array.isArray(options.seedMemoryEvidences)) {
    for (const evidence of options.seedMemoryEvidences) {
      const projectId = evidence.project_id || db.projects[0]?.id || "";
      const seededEvidence: MemoryEvidenceItem = {
        id: evidence.id,
        memory_id: evidence.memory_id,
        source_type: evidence.source_type,
        message_role: evidence.message_role ?? null,
        quote_text: evidence.quote_text,
        confidence: evidence.confidence ?? null,
        created_at: evidence.created_at || nowIso(),
      };
      db.memoryEvidencesByProjectId[projectId] = [
        ...(db.memoryEvidencesByProjectId[projectId] || []).filter(
          (item) => item.id !== seededEvidence.id,
        ),
        seededEvidence,
      ];
    }
  }
  if (Array.isArray(options.seedMemoryLearningRuns)) {
    for (const run of options.seedMemoryLearningRuns) {
      const projectId = run.project_id || db.projects[0]?.id || "";
      const seededRun: MemoryLearningRun = {
        id: run.id,
        trigger: run.trigger,
        status: run.status,
        stages: run.stages || [],
        used_memory_ids: run.used_memory_ids || [],
        promoted_memory_ids: run.promoted_memory_ids || [],
        degraded_memory_ids: run.degraded_memory_ids || [],
        outcome_id: run.outcome_id ?? null,
        error: run.error ?? null,
        task_id: run.task_id ?? null,
        message_id: run.message_id ?? null,
        started_at: run.started_at || nowIso(),
        completed_at: run.completed_at || nowIso(),
        metadata_json: run.metadata_json || {},
      };
      db.memoryLearningRunsByProjectId[projectId] = [
        ...(db.memoryLearningRunsByProjectId[projectId] || []).filter(
          (item) => item.id !== seededRun.id,
        ),
        seededRun,
      ];
    }
  }
  if (options.seedMemoryHealth) {
    db.memoryHealthByProjectId = {
      ...db.memoryHealthByProjectId,
      ...options.seedMemoryHealth,
    };
  }
  if (options.seedMemoryDetails) {
    db.memoryDetailsById = {
      ...db.memoryDetailsById,
      ...options.seedMemoryDetails,
    };
  }
  const seedProjects = db.projects.map((project) => ({
    id: project.id,
    name: project.name,
  }));
  if (options.authenticated) {
    await setAuthenticatedCookies(page, db.workspaceId);
  }

  await page.addInitScript(({ projects }) => {
    const resolveProjects = () => {
      const overriddenProjects = (
        window as Window & {
          __PLAYWRIGHT_PROJECTS__?: Array<{
            id: string;
            name: string;
            default_chat_mode?: string;
          }>;
        }
      ).__PLAYWRIGHT_PROJECTS__;
      return Array.isArray(overriddenProjects) && overriddenProjects.length > 0
        ? overriddenProjects
        : projects;
    };
    const firstProjectId = resolveProjects()[0]?.id || "";
    if (firstProjectId) {
      (window as Window & { __PLAYWRIGHT_FORCE_PROJECT_ID__?: string })
        .__PLAYWRIGHT_FORCE_PROJECT_ID__ = firstProjectId;
    }
    const originalFetch = window.fetch.bind(window);
    window.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
      const request = input instanceof Request ? input : null;
      const method = (init?.method || request?.method || "GET").toUpperCase();
      const rawUrl =
        typeof input === "string"
          ? input
          : input instanceof URL
            ? input.toString()
            : request?.url || String(input);
      const url = new URL(rawUrl, window.location.origin);

      if (method === "GET" && url.pathname === "/api/v1/projects") {
        return new Response(JSON.stringify({ items: resolveProjects() }), {
          status: 200,
          headers: {
            "Content-Type": "application/json",
          },
        });
      }

      return originalFetch(input, init);
    };
  }, { projects: seedProjects });

  page.on("domcontentloaded", () => {
    const url = page.url();
    if (!url.includes("/app/chat")) {
      return;
    }
    void (async () => {
      try {
        await page.locator(".inline-topbar-project-select").waitFor({ state: "visible", timeout: 5000 });
        await page.evaluate(({ projectId, projectName }) => {
          const select = document.querySelector<HTMLSelectElement>(".inline-topbar-project-select");
          if (!select) {
            return;
          }
          if (!Array.from(select.options).some((option) => option.value === projectId)) {
            const option = document.createElement("option");
            option.value = projectId;
            option.textContent = projectName;
            select.appendChild(option);
          }
          if (select.value !== projectId) {
            select.value = projectId;
            select.dispatchEvent(new Event("change", { bubbles: true }));
          }
        }, {
          projectId: db.projects[0]?.id || "",
          projectName: db.projects[0]?.name || "",
        });
      } catch {
        // Ignore pages that do not render the console chat sidebar.
      }
    })();
  });

  const handleApiRoute = async (route: Route) => {
    const request = route.request();
    const url = new URL(request.url());
    const { pathname, searchParams } = url;
    const method = request.method().toUpperCase();

    if (DEBUG_API_MOCK && (
      pathname === "/api/v1/projects" ||
      pathname === "/api/v1/chat/conversations" ||
      pathname === "/api/v1/auth/csrf"
    )) {
      console.log("[mock-api]", method, url.href);
    }

    if (method === "OPTIONS") {
      const origin = request.headers()["origin"] || APP_ORIGIN;
      await route.fulfill({
        status: 204,
        headers: {
          "access-control-allow-origin": origin,
          "access-control-allow-credentials": "true",
          "access-control-allow-methods": "GET,POST,PUT,PATCH,DELETE,OPTIONS",
          "access-control-allow-headers": request.headers()["access-control-request-headers"] || "content-type,x-csrf-token,x-workspace-id",
          "access-control-max-age": "600",
          vary: "Origin",
        },
        body: "",
      });
      return;
    }

    if (pathname === "/api/v1/auth/csrf" && method === "GET") {
      await fulfillJson(route, { csrf_token: "csrf-playwright-token" });
      return;
    }

    if (pathname === "/api/v1/realtime/ws-ticket" && method === "GET") {
      await fulfillJson(route, { ticket: "mock-realtime-ticket", expires_in_seconds: 60 });
      return;
    }

    if (pathname === "/api/v1/auth/send-code" && method === "POST") {
      await fulfillJson(route, { ok: true, sent: true });
      return;
    }

    if (pathname === "/api/v1/auth/register" && method === "POST") {
      const body = readJsonBody<{ code?: string }>(route);
      if (!body.code) {
        await fulfillJson(route, { error: { message: "missing code" } }, 422);
        return;
      }
      await setAuthenticatedCookies(page, db.workspaceId);
      await fulfillJson(route, {
        workspace: { id: db.workspaceId },
        access_token_expires_in_seconds: 3600,
      });
      return;
    }

    if (pathname === "/api/v1/auth/login" && method === "POST") {
      await setAuthenticatedCookies(page, db.workspaceId);
      await fulfillJson(route, {
        workspace: { id: db.workspaceId },
        access_token_expires_in_seconds: 3600,
      });
      return;
    }

    if (pathname === "/api/v1/auth/reset-password" && method === "POST") {
      const body = readJsonBody<{ code?: string; password?: string }>(route);
      if (!body.code || !body.password) {
        await fulfillJson(route, { error: { message: "missing reset fields" } }, 422);
        return;
      }
      await fulfillJson(route, { ok: true });
      return;
    }

    if (pathname === "/api/v1/auth/logout" && method === "POST") {
      await fulfillJson(route, { ok: true });
      return;
    }

    if (pathname === "/api/v1/auth/me" && method === "PATCH") {
      const body = readJsonBody<{ persona?: string | null }>(route);
      await fulfillJson(route, {
        id: "user-playwright",
        email: "playwright@example.com",
        display_name: "Playwright User",
        persona: body.persona ?? null,
      });
      return;
    }

    if (pathname === "/api/v1/projects" && method === "GET") {
      await fulfillJson(route, { items: db.projects });
      return;
    }

    if (pathname === "/api/v1/projects" && method === "POST") {
      const body = readJsonBody<{
        name?: string;
        description?: string;
        default_chat_mode?: "standard" | "omni_realtime" | "synthetic_realtime";
      }>(route);
      const project: Project = {
        id: nextId(db, "proj"),
        name: body.name || "Untitled project",
        description: body.description || "",
        default_chat_mode: body.default_chat_mode || "standard",
        assistant_root_memory_id: null,
        created_at: nowIso(),
      };
      const rootMemoryId = `memory-root-${project.id}`;
      project.assistant_root_memory_id = rootMemoryId;
      db.projects.unshift(project);
      db.conversationsByProjectId[project.id] = [];
      db.pipelineConfigs.push(
        {
          id: `pipe-llm-${project.id}`,
          project_id: project.id,
          model_type: "llm",
          model_id: "qwen3.5-plus",
          config_json: {},
          created_at: nowIso(),
          updated_at: nowIso(),
        },
        {
          id: `pipe-asr-${project.id}`,
          project_id: project.id,
          model_type: "asr",
          model_id: "paraformer-v2",
          config_json: {},
          created_at: nowIso(),
          updated_at: nowIso(),
        },
        {
          id: `pipe-tts-${project.id}`,
          project_id: project.id,
          model_type: "tts",
          model_id: "cosyvoice",
          config_json: {},
          created_at: nowIso(),
          updated_at: nowIso(),
        },
        {
          id: `pipe-vision-${project.id}`,
          project_id: project.id,
          model_type: "vision",
          model_id: "qwen-vl-plus",
          config_json: {},
          created_at: nowIso(),
          updated_at: nowIso(),
        },
        {
          id: `pipe-realtime-${project.id}`,
          project_id: project.id,
          model_type: "realtime",
          model_id: "qwen3-omni-flash-realtime",
          config_json: {},
          created_at: nowIso(),
          updated_at: nowIso(),
        },
        {
          id: `pipe-realtime-asr-${project.id}`,
          project_id: project.id,
          model_type: "realtime_asr",
          model_id: "qwen3-asr-flash-realtime",
          config_json: {},
          created_at: nowIso(),
          updated_at: nowIso(),
        },
        {
          id: `pipe-realtime-tts-${project.id}`,
          project_id: project.id,
          model_type: "realtime_tts",
          model_id: "qwen3-tts-flash-realtime",
          config_json: {},
          created_at: nowIso(),
          updated_at: nowIso(),
        },
      );
      db.memoryNodesByProjectId[project.id] = [
        {
          id: rootMemoryId,
          workspace_id: db.workspaceId,
          project_id: project.id,
          content: project.name,
          category: "assistant",
          type: "permanent",
          source_conversation_id: null,
          parent_memory_id: null,
          position_x: 0,
          position_y: 0,
          metadata_json: {
            node_kind: "assistant-root",
            assistant_name: project.name,
            system_managed: true,
          },
          created_at: nowIso(),
          updated_at: nowIso(),
        },
      ];
      await fulfillJson(route, project, 201);
      return;
    }

    const projectDetailMatch = pathname.match(/^\/api\/v1\/projects\/([^/]+)$/);
    if (projectDetailMatch && method === "GET") {
      const projectId = projectDetailMatch[1];
      const project = db.projects.find((item) => item.id === projectId);
      if (!project) {
        await fulfillJson(route, { error: { message: "project not found" } }, 404);
        return;
      }
      await fulfillJson(route, project);
      return;
    }

    if (projectDetailMatch && method === "PATCH") {
      const projectId = projectDetailMatch[1];
      const body = readJsonBody<{
        name?: string;
        description?: string;
        default_chat_mode?: "standard" | "omni_realtime" | "synthetic_realtime";
      }>(route);
      const index = db.projects.findIndex((item) => item.id === projectId);
      if (index < 0) {
        await fulfillJson(route, { error: { message: "project not found" } }, 404);
        return;
      }

      const current = db.projects[index]!;
      const updated: Project = {
        ...current,
        name: body.name ?? current.name,
        description: body.description ?? current.description,
        default_chat_mode: body.default_chat_mode ?? current.default_chat_mode,
      };
      db.projects[index] = updated;
      const rootMemoryId = updated.assistant_root_memory_id;
      if (rootMemoryId) {
        db.memoryNodesByProjectId[projectId] = (db.memoryNodesByProjectId[projectId] || []).map((node) =>
          node.id === rootMemoryId
            ? {
                ...node,
                content: updated.name,
                metadata_json: {
                  ...node.metadata_json,
                  node_kind: "assistant-root",
                  assistant_name: updated.name,
                  system_managed: true,
                },
                updated_at: nowIso(),
              }
            : node,
        );
      }
      await fulfillJson(route, updated);
      return;
    }

    if (pathname === "/api/v1/chat/conversations" && method === "GET") {
      const projectId = searchParams.get("project_id") || "";
      await fulfillJson(route, db.conversationsByProjectId[projectId] || []);
      return;
    }

    if (pathname === "/api/v1/chat/conversations" && method === "POST") {
      const body = readJsonBody<{ project_id?: string; title?: string }>(route);
      const projectId = body.project_id || db.projects[0]?.id || "";
      const conversation: Conversation = {
        id: nextId(db, "conv"),
        project_id: projectId,
        title: body.title || "New Conversation",
        updated_at: nowIso(),
      };
      db.conversationsByProjectId[projectId] = [
        conversation,
        ...(db.conversationsByProjectId[projectId] || []),
      ];
      db.messagesByConversationId[conversation.id] = [];
      await fulfillJson(route, conversation);
      return;
    }

    const conversationDictateMatch = pathname.match(/^\/api\/v1\/chat\/conversations\/([^/]+)\/dictate$/);
    if (conversationDictateMatch && method === "POST") {
      await fulfillJson(route, {
        text_input: "这是听写结果",
      });
      return;
    }

    const conversationSpeechMatch = pathname.match(/^\/api\/v1\/chat\/conversations\/([^/]+)\/speech$/);
    if (conversationSpeechMatch && method === "POST") {
      await fulfillJson(route, {
        audio_response: "AQID",
      });
      return;
    }

    const conversationImageMatch = pathname.match(/^\/api\/v1\/chat\/conversations\/([^/]+)\/image$/);
    if (conversationImageMatch && method === "POST") {
      const conversationId = conversationImageMatch[1];
      const now = nowIso();
      const userMessage: ChatMessage = {
        id: nextId(db, "msg"),
        conversation_id: conversationId,
        role: "user",
        content: "请描述这张图片",
        metadata_json: {},
        created_at: now,
      };
      const assistantMessage: ChatMessage = {
        id: nextId(db, "msg"),
        conversation_id: conversationId,
        role: "assistant",
        content: "Mock image response",
        metadata_json: {},
        created_at: now,
      };
      db.messagesByConversationId[conversationId] = [
        ...(db.messagesByConversationId[conversationId] || []),
        userMessage,
        assistantMessage,
      ];
      await fulfillJson(route, {
        message: assistantMessage,
        text_input: userMessage.content,
        audio_response: "AQID",
      });
      return;
    }

    const conversationMessagesMatch = pathname.match(/^\/api\/v1\/chat\/conversations\/([^/]+)\/messages$/);
    if (conversationMessagesMatch && method === "GET") {
      const conversationId = conversationMessagesMatch[1];
      await fulfillJson(route, db.messagesByConversationId[conversationId] || []);
      return;
    }

    if (conversationMessagesMatch && method === "POST") {
      const conversationId = conversationMessagesMatch[1];
      const body = readJsonBody<{ content?: string; enable_thinking?: boolean }>(route);
      const now = nowIso();
      const userMessage: ChatMessage = {
        id: nextId(db, "msg"),
        conversation_id: conversationId,
        role: "user",
        content: body.content || "",
        metadata_json: {},
        created_at: now,
      };
      const assistantMessage: ChatMessage = {
        id: nextId(db, "msg"),
        conversation_id: conversationId,
        role: "assistant",
        content: "Mock assistant response",
        reasoning_content: body.enable_thinking ? "Mock reasoning trace" : null,
        metadata_json: {},
        created_at: now,
      };
      db.messagesByConversationId[conversationId] = [
        ...(db.messagesByConversationId[conversationId] || []),
        userMessage,
        assistantMessage,
      ];
      await fulfillJson(route, assistantMessage);
      return;
    }

    if (pathname === "/api/v1/memory" && method === "GET") {
      const projectId = searchParams.get("project_id") || "";
      await fulfillJson(route, { nodes: db.memoryNodesByProjectId[projectId] || [], edges: [] });
      return;
    }

    if (pathname === "/api/v1/memory" && method === "POST") {
      const body = readJsonBody<{ project_id?: string; content?: string; category?: string }>(route);
      const projectId = body.project_id || db.projects[0]?.id || "";
      const project = db.projects.find((item) => item.id === projectId);
      const node: MemoryNode = {
        id: nextId(db, "memory"),
        workspace_id: db.workspaceId,
        project_id: projectId,
        content: body.content || "",
        category: body.category || "",
        type: "permanent",
        source_conversation_id: null,
        parent_memory_id: project?.assistant_root_memory_id || null,
        position_x: null,
        position_y: null,
        metadata_json: {},
        created_at: nowIso(),
        updated_at: nowIso(),
      };
      db.memoryNodesByProjectId[projectId] = [...(db.memoryNodesByProjectId[projectId] || []), node];
      await fulfillJson(route, node);
      return;
    }

    if (pathname === "/api/v1/memory/views" && method === "GET") {
      const projectId = searchParams.get("project_id") || "";
      await fulfillJson(route, db.memoryViewsByProjectId[projectId] || []);
      return;
    }

    if (pathname === "/api/v1/memory/evidences" && method === "GET") {
      const projectId = searchParams.get("project_id") || "";
      await fulfillJson(route, db.memoryEvidencesByProjectId[projectId] || []);
      return;
    }

    if (pathname === "/api/v1/memory/learning-runs" && method === "GET") {
      const projectId = searchParams.get("project_id") || "";
      await fulfillJson(route, db.memoryLearningRunsByProjectId[projectId] || []);
      return;
    }

    if (pathname === "/api/v1/memory/health" && method === "GET") {
      const projectId = searchParams.get("project_id") || "";
      await fulfillJson(route, db.memoryHealthByProjectId[projectId] || { counts: {}, entries: [] });
      return;
    }

    const memoryDetailMatch = pathname.match(/^\/api\/v1\/memory\/([^/]+)$/);
    if (memoryDetailMatch && method === "GET") {
      const memoryId = memoryDetailMatch[1];
      const node = Object.values(db.memoryNodesByProjectId)
        .flat()
        .find((item) => item.id === memoryId);
      if (!node) {
        await fulfillJson(route, { error: { message: "memory not found" } }, 404);
        return;
      }
      await fulfillJson(route, db.memoryDetailsById[memoryId] || node);
      return;
    }

    if (memoryDetailMatch && method === "PATCH") {
      const memoryId = memoryDetailMatch[1];
      const node = Object.values(db.memoryNodesByProjectId)
        .flat()
        .find((item) => item.id === memoryId);
      if (!node) {
        await fulfillJson(route, { error: { message: "memory not found" } }, 404);
        return;
      }
      const body = readJsonBody<{ content?: string; category?: string }>(route);
      if (typeof body.content === "string") {
        node.content = body.content;
      }
      if (typeof body.category === "string") {
        node.category = body.category;
      }
      node.updated_at = nowIso();
      await fulfillJson(route, node);
      return;
    }

    if (memoryDetailMatch && method === "DELETE") {
      const memoryId = memoryDetailMatch[1];
      let removed = false;
      for (const [projectId, nodes] of Object.entries(db.memoryNodesByProjectId)) {
        const nextNodes = nodes.filter((item) => item.id !== memoryId);
        if (nextNodes.length !== nodes.length) {
          db.memoryNodesByProjectId[projectId] = nextNodes;
          removed = true;
        }
      }
      if (!removed) {
        await fulfillJson(route, { error: { message: "memory not found" } }, 404);
        return;
      }
      await route.fulfill({
        status: 204,
        headers: {
          "access-control-allow-origin": route.request().headers().origin || COOKIE_ORIGINS[0] || APP_ORIGIN,
          "access-control-allow-credentials": "true",
        },
        body: "",
      });
      return;
    }

    const memoryPromoteMatch = pathname.match(/^\/api\/v1\/memory\/([^/]+)\/promote$/);
    if (memoryPromoteMatch && method === "POST") {
      const memoryId = memoryPromoteMatch[1];
      const node = Object.values(db.memoryNodesByProjectId)
        .flat()
        .find((item) => item.id === memoryId);
      if (!node) {
        await fulfillJson(route, { error: { message: "memory not found" } }, 404);
        return;
      }
      node.type = "permanent";
      node.updated_at = nowIso();
      await fulfillJson(route, node);
      return;
    }

    const projectStreamMatch = pathname.match(/^\/api\/v1\/memory\/([^/]+)\/stream$/);
    if (projectStreamMatch && method === "GET") {
      await route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        body: "",
      });
      return;
    }

    const conversationStreamMatch = pathname.match(/^\/api\/v1\/chat\/conversations\/([^/]+)\/memory-stream$/);
    if (conversationStreamMatch && method === "GET") {
      await route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        body: "",
      });
      return;
    }

    const conversationEventsMatch = pathname.match(/^\/api\/v1\/chat\/conversations\/([^/]+)\/events$/);
    if (conversationEventsMatch && method === "GET") {
      await route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        body: "",
      });
      return;
    }

    if (pathname === "/api/v1/datasets" && method === "GET") {
      const projectId = searchParams.get("project_id") || "";
      await fulfillJson(
        route,
        db.datasets.filter((dataset) => dataset.project_id === projectId),
      );
      return;
    }

    if (pathname === "/api/v1/datasets" && method === "POST") {
      const body = readJsonBody<{ project_id?: string; name?: string; type?: string }>(route);
      const dataset: Dataset = {
        id: nextId(db, "dataset"),
        project_id: body.project_id || db.projects[0]?.id || "",
        name: body.name || "Untitled dataset",
        type: body.type || "images",
        created_at: nowIso(),
      };
      db.datasets.unshift(dataset);
      db.datasetVersions.unshift({
        id: nextId(db, "dsv"),
        dataset_id: dataset.id,
        version: 1,
      });
      await fulfillJson(route, dataset, 201);
      return;
    }

    const datasetVersionMatch = pathname.match(/^\/api\/v1\/datasets\/([^/]+)\/versions$/);
    if (datasetVersionMatch && method === "GET") {
      const datasetId = datasetVersionMatch[1];
      await fulfillJson(
        route,
        db.datasetVersions.filter((version) => version.dataset_id === datasetId),
      );
      return;
    }

    const datasetItemsMatch = pathname.match(/^\/api\/v1\/datasets\/([^/]+)\/items$/);
    if (datasetItemsMatch && method === "GET") {
      const datasetId = datasetItemsMatch[1];
      await fulfillJson(route, db.dataItemsByDatasetId[datasetId] || []);
      return;
    }

    if (pathname === "/api/v1/models" && method === "GET") {
      const projectId = searchParams.get("project_id") || "";
      await fulfillJson(
        route,
        { items: db.models.filter((model) => model.project_id === projectId) },
      );
      return;
    }

    if (pathname === "/api/v1/models" && method === "POST") {
      const body = readJsonBody<{ project_id?: string; name?: string; task_type?: string }>(route);
      const model: Model = {
        id: nextId(db, "model"),
        project_id: body.project_id || db.projects[0]?.id || "",
        name: body.name || "Untitled model",
        task_type: body.task_type || "general",
        created_at: nowIso(),
      };
      db.models.unshift(model);
      const versionId = nextId(db, "model-version");
      db.modelAliasesById[model.id] = [{ alias: "prod", model_version_id: versionId }];
      db.modelVersionsById[model.id] = [{ id: versionId, version: 1 }];
      await fulfillJson(route, model, 201);
      return;
    }

    if (pathname === "/api/v1/models/catalog" && method === "GET") {
      const category = searchParams.get("category");
      const view = searchParams.get("view");
      const supportsRealtime = (model: CatalogModel) => {
        const capabilities = new Set((model.capabilities || []).map((item) => item.toLowerCase()));
        return capabilities.has("realtime") && capabilities.has("audio_input") && capabilities.has("audio_output");
      };
      if (view === "discover") {
        const items = db.modelCatalog
          .filter((model) => model.provider === "qwen" && model.official_category)
          .map((model) => ({
            canonical_model_id: model.canonical_model_id || model.model_id,
            model_id: model.model_id,
            display_name: model.display_name,
            provider: model.provider,
            provider_display: model.provider_display || "千问 · 阿里云",
            official_group_key: model.official_group_key || null,
            official_group: model.official_group || "文本",
            official_category_key: model.official_category_key || null,
            official_category: model.official_category || "文本生成",
            official_order: model.official_order || 0,
            description: model.description,
            input_modalities: model.input_modalities || [],
            output_modalities: model.output_modalities || [],
            supported_tools: model.supported_tools || [],
            supported_features: model.supported_features || [],
            official_url: model.official_url || "https://help.aliyun.com/zh/model-studio/models",
            aliases: model.aliases || [],
            pipeline_slot: model.pipeline_slot || null,
            is_selectable_in_console: model.is_selectable_in_console ?? true,
          }));
        const taxonomyMap = new Map<string, { key: string; label: string; group_key: string | null; group_label: string; group: string; order: number; count: number }>();
        items.forEach((item) => {
          const key = item.official_category_key || item.official_category;
          const current = taxonomyMap.get(key);
          if (current) {
            current.count += 1;
            return;
          }
          taxonomyMap.set(key, {
            key,
            label: item.official_category,
            group_key: item.official_group_key,
            group_label: item.official_group,
            group: item.official_group,
            order: item.official_order,
            count: 1,
          });
        });
        await fulfillJson(route, {
          taxonomy: Array.from(taxonomyMap.values()).sort((a, b) => a.order - b.order),
          items: items.sort((a, b) => a.official_order - b.official_order),
        });
        return;
      }
      await fulfillJson(
        route,
        category === "realtime"
          ? db.modelCatalog
            .filter((model) => supportsRealtime(model))
            .map((model) => ({ ...model, category: "realtime" as const }))
          : category === "llm"
            ? db.modelCatalog.filter((model) => model.category === "llm" && !supportsRealtime(model))
            : category === "realtime_asr"
              ? db.modelCatalog.filter((model) => model.category === "realtime_asr")
              : category === "realtime_tts"
                ? db.modelCatalog.filter((model) => model.category === "realtime_tts")
            : category
              ? db.modelCatalog.filter((model) => model.category === category)
              : db.modelCatalog,
      );
      return;
    }

    const modelCatalogDetailMatch = pathname.match(/^\/api\/v1\/models\/catalog\/([^/]+)$/);
    if (modelCatalogDetailMatch && method === "GET") {
      const modelId = modelCatalogDetailMatch[1];
      const aliases: Record<string, string[]> = {
        "qwen3-plus": ["qwen3.5-plus"],
      };
      const candidateIds = [modelId, ...(aliases[modelId] || [])];
      const model = candidateIds
        .map((candidateId) => db.modelCatalog.find((item) => item.model_id === candidateId))
        .find(Boolean);
      if (!model) {
        await fulfillJson(route, { error: { message: "catalog model not found" } }, 404);
        return;
      }
      await fulfillJson(route, model);
      return;
    }

    if (pathname === "/api/v1/pipeline" && method === "GET") {
      const projectId = searchParams.get("project_id") || "";
      await fulfillJson(route, {
        items: db.pipelineConfigs.filter((item) => item.project_id === projectId),
      });
      return;
    }

    if (pathname === "/api/v1/pipeline" && method === "PATCH") {
      const body = readJsonBody<{
        project_id?: string;
        model_type?:
          | "llm"
          | "asr"
          | "tts"
          | "vision"
          | "realtime"
          | "realtime_asr"
          | "realtime_tts";
        model_id?: string;
        config_json?: Record<string, unknown>;
      }>(route);
      const projectId = body.project_id || db.projects[0]?.id || "";
      const modelType = body.model_type || "llm";
      const current = db.pipelineConfigs.find(
        (item) => item.project_id === projectId && item.model_type === modelType,
      );
      if (current) {
        current.model_id = body.model_id || current.model_id;
        current.config_json = body.config_json || current.config_json;
        current.updated_at = nowIso();
        if (modelType === "llm") {
          const selected = db.modelCatalog.find((item) => item.model_id === current.model_id);
          const capabilities = new Set((selected?.capabilities || []).map((value) => value.toLowerCase()));
          const project = db.projects.find((item) => item.id === projectId);
          if (project && project.default_chat_mode === "synthetic_realtime" && !capabilities.has("vision")) {
            project.default_chat_mode = "standard";
          }
        }
        await fulfillJson(route, current);
        return;
      }
      const created: PipelineConfigItem = {
        id: `pipe-${modelType}-${nextId(db, "proj")}`,
        project_id: projectId,
        model_type: modelType,
        model_id: body.model_id || "",
        config_json: body.config_json || {},
        created_at: nowIso(),
        updated_at: nowIso(),
      };
      db.pipelineConfigs.push(created);
      await fulfillJson(route, created);
      return;
    }

    const modelDetailMatch = pathname.match(/^\/api\/v1\/models\/([^/]+)$/);
    if (modelDetailMatch && method === "GET") {
      const modelId = modelDetailMatch[1];
      await fulfillJson(route, { aliases: db.modelAliasesById[modelId] || [] });
      return;
    }

    const modelVersionMatch = pathname.match(/^\/api\/v1\/models\/([^/]+)\/versions$/);
    if (modelVersionMatch && method === "GET") {
      const modelId = modelVersionMatch[1];
      await fulfillJson(route, { items: db.modelVersionsById[modelId] || [] });
      return;
    }

    await fulfillJson(
      route,
      { error: { message: `Unhandled mock endpoint: ${method} ${pathname}` } },
      501,
    );
  };

  await page.route("**/api/v1/**", handleApiRoute);

  return {
    workspaceId: db.workspaceId,
    seedProjectId: db.projects[0].id,
  };
}
