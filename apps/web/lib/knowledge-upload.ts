"use client";

import { apiGet, apiPost, buildPresignedUploadInit, uploadToPresignedUrl } from "@/lib/api";

type DatasetInfo = {
  id: string;
  name: string;
  type: string;
};

type UploadPresignResponse = {
  upload_id: string;
  put_url: string;
  headers: Record<string, string>;
  fields: Record<string, string>;
  upload_method: "PUT" | "POST";
  data_item_id: string;
};

export async function ensureKnowledgeDataset(projectId: string): Promise<DatasetInfo> {
  const datasets = await apiGet<DatasetInfo[]>(`/api/v1/datasets?project_id=${projectId}`);
  if (datasets.length > 0) {
    return datasets[0];
  }

  return apiPost<DatasetInfo>("/api/v1/datasets", {
    project_id: projectId,
    name: "Default Knowledge",
    type: "text",
  });
}

async function uploadSingleFile(datasetId: string, file: File): Promise<void> {
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
}

export async function uploadKnowledgeFiles(projectId: string, files: File[]): Promise<void> {
  if (files.length === 0) {
    return;
  }

  const dataset = await ensureKnowledgeDataset(projectId);
  for (const file of files) {
    await uploadSingleFile(dataset.id, file);
  }
}
