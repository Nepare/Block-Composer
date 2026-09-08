import { apiFetch } from "@/shared/api";
import * as session from "@/shared/session";

export interface BlockSummary {
  id: string;
  name: string;
  tags: string[];
  schema: string | null;
  source: string;
  created_at: string | null;
  preserved: boolean;
}

export interface BlockDetail extends BlockSummary {
  body: string;
  created_by: string;
  generation_criteria: string | null;
  mutated_from: string | null;
}

export interface BlockUpdatePayload {
  body: string;
  tags?: string[];
  schema?: string;
}

export interface DeleteBlockResult {
  deleted: string;
}

export interface PreserveBlockResult {
  preserved: string;
}

export interface UnpreserveBlockResult {
  preserved: false;
}

export interface ClearBlocksResult {
  deleted: number;
  skipped_preserved: number;
}

export interface GenerateStartPayload {
  criteria: string;
  name?: string;
  preserve?: boolean;
}

export interface MutateStartPayload {
  block_id: string;
  criteria: string;
  name?: string;
  preserve?: boolean;
}

export interface DissectStartPayload {
  doc: string;
}

export interface JobStartResult {
  job_id: string;
}

export async function listBlocks(query?: string): Promise<BlockSummary[]> {
  const path = query ? `/blocks?query=${encodeURIComponent(query)}` : "/blocks";
  const response = await apiFetch(path);
  return response.json();
}

export async function getBlock(id: string): Promise<BlockDetail> {
  const response = await apiFetch(`/blocks/${encodeURIComponent(id)}`);
  return response.json();
}

export function updateBlock(id: string, payload: BlockUpdatePayload): Promise<Response> {
  return apiFetch(`/blocks/${encodeURIComponent(id)}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function deleteBlock(id: string): Promise<Response> {
  return apiFetch(`/blocks/${encodeURIComponent(id)}`, { method: "DELETE" });
}

export function preserveBlock(id: string): Promise<Response> {
  return apiFetch(`/blocks/${encodeURIComponent(id)}/preserve`, { method: "POST" });
}

export function unpreserveBlock(id: string): Promise<Response> {
  return apiFetch(`/blocks/${encodeURIComponent(id)}/unpreserve`, { method: "POST" });
}

export function clearBlocks(): Promise<Response> {
  return apiFetch("/blocks/clear", { method: "POST" });
}

export function startGenerate(payload: GenerateStartPayload): Promise<Response> {
  return apiFetch("/generate/start", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function startMutate(payload: MutateStartPayload): Promise<Response> {
  return apiFetch("/mutate/start", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function startDissect(payload: DissectStartPayload): Promise<Response> {
  return apiFetch("/dissect/start", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function streamUrl(jobId: string): string {
  return `/stream/${jobId}?key=${encodeURIComponent(session.get() ?? "")}`;
}
