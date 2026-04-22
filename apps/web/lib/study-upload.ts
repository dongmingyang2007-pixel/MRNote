"use client";

import {
  apiGet,
  apiPost,
  buildPresignedUploadInit,
  uploadToPresignedUrl,
} from "@/lib/api";
import { ensureKnowledgeDataset } from "@/lib/knowledge-upload";
import {
  dispatchNotebookStudyChanged,
  dispatchNotebooksChanged,
} from "@/lib/notebook-events";

type UploadPresignResponse = {
  upload_id: string;
  put_url: string;
  headers: Record<string, string>;
  fields: Record<string, string>;
  upload_method: "PUT" | "POST";
  data_item_id: string;
};

type NotebookMeta = {
  id: string;
  project_id: string | null;
};

type StudyAssetOut = {
  id: string;
  notebook_id: string;
  title: string;
  asset_type: string;
  status: string;
};

const TEXT_ARTICLE_EXTENSIONS = new Set([
  ".txt", ".md", ".csv", ".tsv", ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".env",
  ".log", ".rst", ".tex", ".py", ".js", ".jsx", ".ts", ".tsx", ".java", ".c", ".cc", ".cpp",
  ".cxx", ".h", ".hpp", ".cs", ".go", ".rs", ".rb", ".php", ".swift", ".kt", ".kts", ".scala",
  ".r", ".sql", ".sh", ".bash", ".zsh", ".fish", ".ps1", ".vue", ".svelte", ".ipynb", ".xml",
  ".html", ".htm", ".css",
]);
const IMAGE_EXTENSIONS = new Set([
  ".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff",
]);

// Leave the picker unrestricted so any file can enter the study pipeline.
export const STUDY_UPLOAD_ACCEPT = "";

const ASSET_TYPE_BY_MIME: Record<string, string> = {
  "application/pdf": "pdf",
  "image/png": "image",
  "image/jpeg": "image",
  "image/webp": "image",
  "image/gif": "image",
};

function assetTypeForFile(file: File): string {
  if (ASSET_TYPE_BY_MIME[file.type]) return ASSET_TYPE_BY_MIME[file.type];
  const name = file.name.toLowerCase();
  if (name.endsWith(".pdf")) return "pdf";
  if (name.endsWith(".docx")) return "pdf";
  if (name.endsWith(".pptx")) return "slides";
  const extensionIndex = name.lastIndexOf(".");
  const extension = extensionIndex >= 0 ? name.slice(extensionIndex) : "";
  if (IMAGE_EXTENSIONS.has(extension)) return "image";
  if (TEXT_ARTICLE_EXTENSIONS.has(extension)) return "article";
  return "file";
}

async function uploadOne(datasetId: string, file: File): Promise<string> {
  const presign = await apiPost<UploadPresignResponse>("/api/v1/uploads/presign", {
    dataset_id: datasetId,
    filename: file.name,
    media_type: file.type || "application/octet-stream",
    size_bytes: file.size,
  });

  const putRes = await uploadToPresignedUrl(
    presign.put_url,
    buildPresignedUploadInit(presign, file),
    { authenticated: true },
  );
  if (!putRes.ok) {
    throw new Error(`File upload failed (${putRes.status})`);
  }

  await apiPost("/api/v1/uploads/complete", {
    upload_id: presign.upload_id,
    data_item_id: presign.data_item_id,
  });
  return presign.data_item_id;
}

export async function uploadStudyAssets(
  notebookId: string,
  files: File[],
  onProgress?: (done: number, total: number) => void,
): Promise<StudyAssetOut[]> {
  if (files.length === 0) return [];

  const notebook = await apiGet<NotebookMeta>(`/api/v1/notebooks/${notebookId}`);
  if (!notebook.project_id) {
    throw new Error("Notebook has no linked project");
  }
  const dataset = await ensureKnowledgeDataset(notebook.project_id);

  const created: StudyAssetOut[] = [];
  for (let i = 0; i < files.length; i += 1) {
    const file = files[i];
    const dataItemId = await uploadOne(dataset.id, file);
    const asset = await apiPost<StudyAssetOut>(
      `/api/v1/notebooks/${notebookId}/study`,
      {
        title: file.name.replace(/\.[^.]+$/, "") || file.name,
        asset_type: assetTypeForFile(file),
        data_item_id: dataItemId,
      },
    );
    created.push(asset);
    onProgress?.(i + 1, files.length);
  }
  dispatchNotebookStudyChanged(notebookId);
  dispatchNotebooksChanged();
  return created;
}
