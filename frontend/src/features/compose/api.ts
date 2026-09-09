import { apiFetch, streamUrl } from "@/shared/api";

export { streamUrl };

export interface ComposeStartPayload {
  request: string;
  specifiers?: string;
  count?: number;
  name?: string;
  preserve?: boolean;
  restrict_generate?: boolean;
  restrict_mutate?: boolean;
  from_block_ids?: string[];
}

export interface ResultSlot {
  order: number;
  action: "use" | "mutate" | "generate";
  block_id: string | null;
  criteria: string | null;
  resolved_id: string | null;
}

export interface ResultSummary {
  id: string;
  name: string;
  request: string;
  created_at: string | null;
  preserved: boolean;
}

export interface ResultDetail extends ResultSummary {
  content: string;
  slots: ResultSlot[];
}

export interface RenameResultResult {
  id: string;
  name: string;
}

export interface ClearResultsResult {
  deleted: number;
  skipped_preserved: number;
}

export function startCompose(payload: ComposeStartPayload): Promise<Response> {
  return apiFetch("/compose/start", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function cancelJob(jobId: string): Promise<Response> {
  return apiFetch(`/cancel/${encodeURIComponent(jobId)}`, { method: "POST" });
}

export async function listResults(query?: string): Promise<ResultSummary[]> {
  const path = query ? `/results?query=${encodeURIComponent(query)}` : "/results";
  const response = await apiFetch(path);
  return response.json();
}

export async function getResult(id: string): Promise<ResultDetail> {
  const response = await apiFetch(`/results/${encodeURIComponent(id)}`);
  return response.json();
}

export function deleteResult(id: string): Promise<Response> {
  return apiFetch(`/results/${encodeURIComponent(id)}`, { method: "DELETE" });
}

export function preserveResult(id: string): Promise<Response> {
  return apiFetch(`/results/${encodeURIComponent(id)}/preserve`, { method: "POST" });
}

export function unpreserveResult(id: string): Promise<Response> {
  return apiFetch(`/results/${encodeURIComponent(id)}/unpreserve`, { method: "POST" });
}

export function renameResult(id: string, name: string): Promise<Response> {
  return apiFetch(`/results/${encodeURIComponent(id)}/rename`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  });
}

export function clearResults(): Promise<Response> {
  return apiFetch("/results/clear", { method: "POST" });
}
