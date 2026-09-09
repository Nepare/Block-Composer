import { useCallback, useEffect, useRef, useState } from "react";
import {
  clearResults,
  deleteResult as apiDeleteResult,
  getResult as apiGetResult,
  listResults,
  preserveResult as apiPreserveResult,
  renameResult as apiRenameResult,
  unpreserveResult as apiUnpreserveResult,
  type ClearResultsResult,
  type ResultDetail,
  type ResultSummary,
} from "@/features/compose/api";

export interface UseResultsHistoryResult {
  summaries: ResultSummary[];
  loading: boolean;
  refetch: () => Promise<void>;
  getResult: (id: string) => Promise<ResultDetail>;
  renameResult: (id: string, name: string) => Promise<boolean>;
  preserveResult: (id: string) => Promise<boolean>;
  unpreserveResult: (id: string) => Promise<boolean>;
  deleteResult: (id: string) => Promise<boolean>;
  clearHistory: () => Promise<ClearResultsResult | null>;
}

export function useResultsHistory(): UseResultsHistoryResult {
  const [summaries, setSummaries] = useState<ResultSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const detailCache = useRef<Map<string, ResultDetail>>(new Map());

  const refetch = useCallback(async () => {
    setLoading(true);
    const next = await listResults();
    setSummaries(next);
    setLoading(false);
  }, []);

  useEffect(() => {
    refetch();
  }, [refetch]);

  const getResult = useCallback(async (id: string): Promise<ResultDetail> => {
    const cached = detailCache.current.get(id);
    if (cached) return cached;
    const detail = await apiGetResult(id);
    detailCache.current.set(id, detail);
    return detail;
  }, []);

  const patchPreserved = useCallback((id: string, preserved: boolean) => {
    setSummaries((prev) => prev.map((entry) => (entry.id === id ? { ...entry, preserved } : entry)));
    const cached = detailCache.current.get(id);
    if (cached) detailCache.current.set(id, { ...cached, preserved });
  }, []);

  const renameResult = useCallback(async (id: string, name: string): Promise<boolean> => {
    const response = await apiRenameResult(id, name);
    if (!response.ok) return false;
    setSummaries((prev) => prev.map((entry) => (entry.id === id ? { ...entry, name } : entry)));
    const cached = detailCache.current.get(id);
    if (cached) detailCache.current.set(id, { ...cached, name });
    return true;
  }, []);

  const preserveResult = useCallback(
    async (id: string): Promise<boolean> => {
      const response = await apiPreserveResult(id);
      if (!response.ok) return false;
      patchPreserved(id, true);
      return true;
    },
    [patchPreserved]
  );

  const unpreserveResult = useCallback(
    async (id: string): Promise<boolean> => {
      const response = await apiUnpreserveResult(id);
      if (!response.ok) return false;
      patchPreserved(id, false);
      return true;
    },
    [patchPreserved]
  );

  const deleteResult = useCallback(async (id: string): Promise<boolean> => {
    const response = await apiDeleteResult(id);
    if (!response.ok) return false;
    setSummaries((prev) => prev.filter((entry) => entry.id !== id));
    detailCache.current.delete(id);
    return true;
  }, []);

  const clearHistory = useCallback(async (): Promise<ClearResultsResult | null> => {
    const response = await clearResults();
    if (!response.ok) return null;
    const result: ClearResultsResult = await response.json();
    const next = await listResults();
    setSummaries(next);
    const keptIds = new Set(next.map((entry) => entry.id));
    for (const id of detailCache.current.keys()) {
      if (!keptIds.has(id)) detailCache.current.delete(id);
    }
    return result;
  }, []);

  return {
    summaries,
    loading,
    refetch,
    getResult,
    renameResult,
    preserveResult,
    unpreserveResult,
    deleteResult,
    clearHistory,
  };
}
