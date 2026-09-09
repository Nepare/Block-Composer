import * as session from "@/shared/session";

type UnauthorizedHandler = () => void;

let unauthorizedHandler: UnauthorizedHandler | null = null;

// Lets App.tsx react to a 401 from any apiFetch call in one place, instead of
// every call site checking response.status itself.
export function setUnauthorizedHandler(handler: UnauthorizedHandler | null): void {
  unauthorizedHandler = handler;
}

export async function apiFetch(path: string, init?: RequestInit): Promise<Response> {
  const key = session.get() ?? "";
  const separator = path.includes("?") ? "&" : "?";
  const url = `${path}${separator}key=${encodeURIComponent(key)}`;
  const response = await fetch(url, init);
  if (response.status === 401) {
    unauthorizedHandler?.();
  }
  return response;
}

export function streamUrl(jobId: string): string {
  return `/stream/${jobId}?key=${encodeURIComponent(session.get() ?? "")}`;
}
