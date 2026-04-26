export interface NotebookCard {
  id: string;
  title: string;
  description: string;
  notebook_type: string;
  updated_at: string;
  page_count: number;
  study_asset_count: number;
  ai_action_count: number;
}

export interface HomePageItem {
  id: string;
  notebook_id: string;
  notebook_title: string;
  title: string;
  updated_at: string;
  last_edited_at: string | null;
  plain_text_preview: string;
}

export interface HomeStudyAsset {
  id: string;
  notebook_id: string;
  notebook_title: string;
  title: string;
  status: string;
  asset_type: string;
  total_chunks: number;
  created_at: string;
}

export interface HomeAIAction {
  id: string;
  notebook_id: string | null;
  page_id: string | null;
  notebook_title: string | null;
  page_title: string | null;
  action_type: string;
  output_summary: string;
  created_at: string;
}

export interface FocusItem {
  notebook_id: string;
  notebook_title: string;
  page_count: number;
  study_asset_count: number;
  ai_action_count: number;
}

export interface HomeSummary {
  notebooks: NotebookCard[];
  recent_pages: HomePageItem[];
  continue_writing: HomePageItem[];
  recent_study_assets: HomeStudyAsset[];
  ai_today: {
    actions_today: number;
    top_action_types: Array<{ action_type: string; count: number }>;
    recent_actions: HomeAIAction[];
  };
  work_themes: FocusItem[];
  long_term_focus: FocusItem[];
  recommended_pages: HomePageItem[];
}

export interface NotebookHomeMetrics {
  notebooks: number;
  pages: number;
  assets: number;
  ai: number;
}

export function emptyHomeSummary(): HomeSummary {
  return {
    notebooks: [],
    recent_pages: [],
    continue_writing: [],
    recent_study_assets: [],
    ai_today: {
      actions_today: 0,
      top_action_types: [],
      recent_actions: [],
    },
    work_themes: [],
    long_term_focus: [],
    recommended_pages: [],
  };
}

export function getNotebookHomeMetrics(home: HomeSummary): NotebookHomeMetrics {
  return {
    notebooks: home.notebooks.length,
    pages: home.notebooks.reduce(
      (sum, notebook) => sum + notebook.page_count,
      0,
    ),
    assets: home.notebooks.reduce(
      (sum, notebook) => sum + notebook.study_asset_count,
      0,
    ),
    ai: home.ai_today?.actions_today ?? 0,
  };
}

export function formatNotebookDate(value: string | null | undefined): string {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}
