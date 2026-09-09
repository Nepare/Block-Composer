import { useCallback, useMemo, useState } from "react";
import { getBlock, listBlocks, type BlockDetail } from "@/features/library/api";
import { extractEnvironment, type BlockViewMode, type LibraryBlockRecord } from "@/shared/blocks/types";

export function toBlockRecord(detail: BlockDetail): LibraryBlockRecord {
  return {
    id: detail.id,
    name: detail.name,
    created_at: detail.created_at,
    created_by: detail.created_by,
    environment: extractEnvironment(detail.body),
    preserved: detail.preserved,
  };
}

function loadStoredViewMode(storageKey: string): BlockViewMode {
  try {
    const stored = localStorage.getItem(storageKey);
    if (stored === "list" || stored === "grid-2" || stored === "grid-3") return stored;
  } catch {
    // storage unavailable — fall back to the default
  }
  return "grid-2";
}

export interface UseBlockCatalogOptions {
  storageKey: string;
}

export interface UseBlockCatalogResult {
  blocks: LibraryBlockRecord[];
  setBlocks: React.Dispatch<React.SetStateAction<LibraryBlockRecord[]>>;
  loading: boolean;
  refetch: () => Promise<LibraryBlockRecord[]>;
  search: string;
  setSearch: (value: string) => void;
  visibleBlocks: LibraryBlockRecord[];
  viewMode: BlockViewMode;
  setViewMode: (mode: BlockViewMode) => void;
}

// Fetch+hydrate, search-filter, and view-mode/localStorage logic shared by
// Library's grid and the block picker — no dialog/mutation behavior lives here.
export function useBlockCatalog({ storageKey }: UseBlockCatalogOptions): UseBlockCatalogResult {
  const [blocks, setBlocks] = useState<LibraryBlockRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [viewMode, setViewModeState] = useState<BlockViewMode>(() => loadStoredViewMode(storageKey));

  const refetch = useCallback(async () => {
    setLoading(true);
    const summaries = await listBlocks();
    const details = await Promise.all(summaries.map((summary) => getBlock(summary.id)));
    const nextBlocks = details.map(toBlockRecord);
    setBlocks(nextBlocks);
    setLoading(false);
    return nextBlocks;
  }, []);

  const setViewMode = useCallback(
    (mode: BlockViewMode) => {
      setViewModeState(mode);
      try {
        localStorage.setItem(storageKey, mode);
      } catch {
        // storage unavailable — the choice just won't persist across visits
      }
    },
    [storageKey]
  );

  const sortedBlocks = useMemo(
    () =>
      [...blocks].sort((a, b) => {
        const aTime = a.created_at ? new Date(a.created_at).getTime() : 0;
        const bTime = b.created_at ? new Date(b.created_at).getTime() : 0;
        return bTime - aTime;
      }),
    [blocks]
  );

  const visibleBlocks = useMemo(() => {
    const term = search.trim().toLowerCase();
    if (!term) return sortedBlocks;
    return sortedBlocks.filter((block) => {
      const haystack = [block.name, ...block.environment].join(" ").toLowerCase();
      return haystack.includes(term);
    });
  }, [sortedBlocks, search]);

  return { blocks, setBlocks, loading, refetch, search, setSearch, visibleBlocks, viewMode, setViewMode };
}
