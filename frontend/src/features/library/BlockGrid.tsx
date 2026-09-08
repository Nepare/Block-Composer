import { useCallback, useEffect, useMemo, useState } from "react";
import { FileText, Grid2x2, Grid3x3, List, Plus, Search, Trash2 } from "lucide-react";
import { toast } from "sonner";
import {
  clearBlocks,
  deleteBlock,
  getBlock,
  listBlocks,
  preserveBlock,
  unpreserveBlock,
  type BlockDetail,
  type ClearBlocksResult,
} from "@/features/library/api";
import { BlockTile, PendingBlockTile, type LibraryBlockRecord, type LibraryViewMode } from "@/features/library/BlockTile";
import { ConfirmDialog } from "@/features/library/ConfirmDialog";
import { DissectDialog } from "@/features/library/DissectDialog";
import { EditBlockDialog } from "@/features/library/EditBlockDialog";
import { GenerateMutateDialog } from "@/features/library/GenerateMutateDialog";
import { ViewBlockDialog } from "@/features/library/ViewBlockDialog";
import type { JobKind, PendingJob, StartJobMeta } from "@/features/library/useLibraryJobs";
import { Button } from "@/shared/ui/button";
import { Input } from "@/shared/ui/input";
import { Spinner } from "@/shared/ui/Spinner";
import { cn } from "@/shared/lib/utils";

const VIEW_STORAGE_KEY = "cvdocs.libraryView";
const DELETE_WARNING_KEY = "cvdocs.skipDeleteWarning";

const VIEW_MODES: { value: LibraryViewMode; label: string; icon: typeof List }[] = [
  { value: "list", label: "List", icon: List },
  { value: "grid-2", label: "2-column", icon: Grid2x2 },
  { value: "grid-3", label: "3-column", icon: Grid3x3 },
];

const FIELD_RE = /^\*\*(.+?):\*\*\s*(.*)$/;
const BULLET_RE = /^-\s+(.+)$/;

// Display-only extraction of the "**Environment:**" field from a block's body —
// not a full port of block_fields.py's parser (that lands with the Edit dialog).
function extractEnvironment(body: string): string[] {
  const lines = body.split("\n");
  let capturing = false;
  let inline = "";
  const bullets: string[] = [];

  for (const raw of lines) {
    const line = raw.trim();
    if (!line) continue;
    const fieldMatch = line.match(FIELD_RE);
    if (fieldMatch) {
      if (capturing) break;
      if (fieldMatch[1].trim().toLowerCase() === "environment") {
        capturing = true;
        inline = fieldMatch[2];
      }
      continue;
    }
    if (!capturing) continue;
    const bulletMatch = line.match(BULLET_RE);
    if (bulletMatch) {
      bullets.push(bulletMatch[1].trim());
    } else {
      inline = `${inline} ${line}`.trim();
    }
  }

  const text = bullets.length ? bullets.join(" ") : inline;
  return text
    .split(",")
    .map((entry) => entry.trim())
    .filter(Boolean);
}

function toLibraryBlock(detail: BlockDetail): LibraryBlockRecord {
  return {
    id: detail.id,
    name: detail.name,
    created_at: detail.created_at,
    created_by: detail.created_by,
    environment: extractEnvironment(detail.body),
    preserved: detail.preserved,
  };
}

function loadStoredViewMode(): LibraryViewMode {
  try {
    const stored = localStorage.getItem(VIEW_STORAGE_KEY);
    if (stored === "list" || stored === "grid-2" || stored === "grid-3") return stored;
  } catch {
    // storage unavailable — fall back to the default
  }
  return "grid-2";
}

interface BlockGridProps {
  pendingJobs?: PendingJob[];
  onDismissJob?: (jobId: string) => void;
  onJobStarted?: (kind: JobKind, jobId: string, meta?: StartJobMeta) => void;
  onJobResolved?: (jobId: string) => void;
  refetchToken?: number;
}

export function BlockGrid({
  pendingJobs = [],
  onDismissJob,
  onJobStarted,
  onJobResolved,
  refetchToken,
}: BlockGridProps) {
  const [blocks, setBlocks] = useState<LibraryBlockRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [viewMode, setViewMode] = useState<LibraryViewMode>(() => loadStoredViewMode());
  const [generateOpen, setGenerateOpen] = useState(false);
  const [mutateBlockId, setMutateBlockId] = useState<string | null>(null);
  const [viewBlockId, setViewBlockId] = useState<string | null>(null);
  const [editBlockId, setEditBlockId] = useState<string | null>(null);
  const [deleteBlockId, setDeleteBlockId] = useState<string | null>(null);
  const [clearOpen, setClearOpen] = useState(false);
  const [dissectOpen, setDissectOpen] = useState(false);

  const loadBlocks = useCallback(async () => {
    setLoading(true);
    const summaries = await listBlocks();
    const details = await Promise.all(summaries.map((summary) => getBlock(summary.id)));
    const nextBlocks = details.map(toLibraryBlock);
    setBlocks(nextBlocks);
    setLoading(false);
    return nextBlocks;
  }, []);

  useEffect(() => {
    let cancelled = false;
    loadBlocks().then((nextBlocks) => {
      if (cancelled) return;
      for (const job of pendingJobs) {
        if (job.status === "resolving" && nextBlocks.some((block) => block.id === job.resultBlockId)) {
          onJobResolved?.(job.jobId);
        }
      }
    });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refetchToken]);

  function selectViewMode(mode: LibraryViewMode) {
    setViewMode(mode);
    try {
      localStorage.setItem(VIEW_STORAGE_KEY, mode);
    } catch {
      // storage unavailable — the choice just won't persist across visits
    }
  }

  const sortedBlocks = useMemo(
    () =>
      [...blocks].sort((a, b) => {
        const aTime = a.created_at ? new Date(a.created_at).getTime() : 0;
        const bTime = b.created_at ? new Date(b.created_at).getTime() : 0;
        return bTime - aTime;
      }),
    [blocks]
  );

  const mutateBlock = mutateBlockId ? (blocks.find((block) => block.id === mutateBlockId) ?? null) : null;

  const visibleBlocks = useMemo(() => {
    const term = search.trim().toLowerCase();
    if (!term) return sortedBlocks;
    return sortedBlocks.filter((block) => {
      const haystack = [block.name, ...block.environment].join(" ").toLowerCase();
      return haystack.includes(term);
    });
  }, [sortedBlocks, search]);

  async function handleTogglePreserve(block: LibraryBlockRecord) {
    const nextPreserved = !block.preserved;
    setBlocks((prev) => prev.map((b) => (b.id === block.id ? { ...b, preserved: nextPreserved } : b)));
    const response = await (nextPreserved ? preserveBlock(block.id) : unpreserveBlock(block.id));
    if (!response.ok) {
      setBlocks((prev) => prev.map((b) => (b.id === block.id ? { ...b, preserved: block.preserved } : b)));
    }
  }

  async function performDelete(id: string) {
    const response = await deleteBlock(id);
    if (response.ok) {
      setBlocks((prev) => prev.filter((b) => b.id !== id));
    }
  }

  function handleDeleteRequest(id: string) {
    let skipWarning = false;
    try {
      skipWarning = localStorage.getItem(DELETE_WARNING_KEY) === "true";
    } catch {
      skipWarning = false;
    }
    if (skipWarning) {
      performDelete(id);
      return;
    }
    setDeleteBlockId(id);
  }

  async function performClear() {
    const response = await clearBlocks();
    if (!response.ok) return;
    const result: ClearBlocksResult = await response.json();
    await loadBlocks();
    toast.success(`Cleared ${result.deleted} block(s), kept ${result.skipped_preserved} preserved.`);
  }

  const gridClassName = cn(
    viewMode === "list" && "flex flex-col gap-2",
    viewMode === "grid-2" && "grid grid-cols-1 gap-3 sm:grid-cols-2",
    viewMode === "grid-3" && "grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3"
  );

  return (
    <div className="flex flex-col gap-4 p-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-sm font-semibold">Library</h2>
        <div className="flex items-center gap-3">
          <div className="relative w-full max-w-xs">
            <Search className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              placeholder="Search blocks"
              aria-label="Search blocks"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              className="bg-background pl-8"
            />
          </div>
          <div
            className="flex items-center gap-0.5 rounded-2xl border bg-card p-1"
            role="group"
            aria-label="View mode"
          >
            {VIEW_MODES.map(({ value, label, icon: Icon }) => (
              <Button
                key={value}
                type="button"
                variant={viewMode === value ? "secondary" : "ghost"}
                size="icon-sm"
                aria-pressed={viewMode === value}
                aria-label={label}
                title={label}
                onClick={() => selectViewMode(value)}
              >
                <Icon />
              </Button>
            ))}
          </div>
        </div>
      </div>
      <div className="flex items-center gap-3">
        <Button
          type="button"
          variant="outline"
          onClick={() => setDissectOpen(true)}
          className="flex-1 justify-center gap-2.5 border-2 border-dashed border-primary/40 py-5 text-muted-foreground hover:border-primary/70 hover:text-primary"
        >
          <FileText className="size-4 text-primary" />
          Populate the library from Google Docs
        </Button>
        <Button
          type="button"
          variant="outline"
          onClick={() => setClearOpen(true)}
          className="gap-2 border-2 border-destructive py-5 text-destructive hover:bg-destructive/10 hover:text-destructive"
        >
          <Trash2 className="size-4" />
          Clear library
        </Button>
      </div>
      {loading ? (
        <p className="flex items-center gap-2 text-muted-foreground">
          <Spinner /> Loading library...
        </p>
      ) : (
        <>
          <div className={gridClassName}>
            <button
              type="button"
              onClick={() => setGenerateOpen(true)}
              aria-label="Generate a new block"
              className={cn(
                "flex items-center justify-center gap-2 rounded-2xl border-2 border-dashed border-primary/30 bg-card p-3 text-sm font-semibold text-primary transition-colors hover:border-primary/60 hover:bg-primary/5",
                viewMode === "list" ? "flex-row py-3" : "flex-col py-8"
              )}
            >
              <Plus className={viewMode === "list" ? "size-5" : "size-6"} />
              Generate
            </button>
            {pendingJobs.filter((job) => job.kind !== "dissect").map((job) => (
              <PendingBlockTile
                key={job.jobId}
                job={job}
                viewMode={viewMode}
                onDismiss={(jobId) => onDismissJob?.(jobId)}
              />
            ))}
            {visibleBlocks.map((block) => (
              <BlockTile
                key={block.id}
                block={block}
                viewMode={viewMode}
                onView={() => setViewBlockId(block.id)}
                onMutate={() => setMutateBlockId(block.id)}
                onEdit={() => setEditBlockId(block.id)}
                onTogglePreserve={() => handleTogglePreserve(block)}
                onDelete={() => handleDeleteRequest(block.id)}
              />
            ))}
          </div>
          {visibleBlocks.length === 0 && pendingJobs.length === 0 && (
            <p className="text-muted-foreground">
              {blocks.length === 0 ? "The library is empty." : "No blocks match your search."}
            </p>
          )}
        </>
      )}
      <GenerateMutateDialog
        mode="generate"
        open={generateOpen}
        onOpenChange={setGenerateOpen}
        onJobStarted={(kind, jobId) => onJobStarted?.(kind, jobId)}
      />
      {mutateBlock && (
        <GenerateMutateDialog
          mode="mutate"
          sourceBlock={mutateBlock}
          open={mutateBlockId !== null}
          onOpenChange={(next) => {
            if (!next) setMutateBlockId(null);
          }}
          onJobStarted={(kind, jobId) => onJobStarted?.(kind, jobId)}
        />
      )}
      {viewBlockId && (
        <ViewBlockDialog
          blockId={viewBlockId}
          open={viewBlockId !== null}
          onOpenChange={(next) => {
            if (!next) setViewBlockId(null);
          }}
          onEdit={() => {
            setEditBlockId(viewBlockId);
            setViewBlockId(null);
          }}
        />
      )}
      {editBlockId && (
        <EditBlockDialog
          blockId={editBlockId}
          open={editBlockId !== null}
          onOpenChange={(next) => {
            if (!next) setEditBlockId(null);
          }}
          onSaved={(updated) => {
            const nextBlock = toLibraryBlock(updated);
            setBlocks((prev) => prev.map((block) => (block.id === nextBlock.id ? nextBlock : block)));
          }}
        />
      )}
      {deleteBlockId && (
        <ConfirmDialog
          open={deleteBlockId !== null}
          onOpenChange={(next) => {
            if (!next) setDeleteBlockId(null);
          }}
          title="Delete block"
          description="This can't be undone."
          suppressionKey={DELETE_WARNING_KEY}
          onConfirm={() => {
            if (deleteBlockId) performDelete(deleteBlockId);
          }}
        />
      )}
      <ConfirmDialog
        open={clearOpen}
        onOpenChange={setClearOpen}
        title="Clear library"
        description="This removes every unpreserved block. This can't be undone."
        onConfirm={performClear}
      />
      <DissectDialog
        open={dissectOpen}
        onOpenChange={setDissectOpen}
        onJobStarted={(jobId, preserveRequested) =>
          onJobStarted?.("dissect", jobId, { preserve: preserveRequested })
        }
      />
    </div>
  );
}
