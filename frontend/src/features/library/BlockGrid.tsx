import { useEffect, useState } from "react";
import { FileText, Plus, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { clearBlocks, deleteBlock, preserveBlock, unpreserveBlock, type ClearBlocksResult } from "@/features/library/api";
import { BlockTile, PendingBlockTile } from "@/features/library/BlockTile";
import { ConfirmDialog } from "@/shared/ui/ConfirmDialog";
import { DissectDialog } from "@/features/library/DissectDialog";
import { EditBlockDialog } from "@/features/library/EditBlockDialog";
import { GenerateMutateDialog } from "@/features/library/GenerateMutateDialog";
import { ViewBlockDialog } from "@/features/library/ViewBlockDialog";
import type { JobKind, PendingJob, StartJobMeta } from "@/features/library/useLibraryJobs";
import { Button } from "@/shared/ui/button";
import { BlockGridLayout } from "@/shared/blocks/BlockGridLayout";
import { toBlockRecord, useBlockCatalog } from "@/shared/blocks/useBlockCatalog";
import type { LibraryBlockRecord } from "@/shared/blocks/types";
import { cn } from "@/shared/lib/utils";

const VIEW_STORAGE_KEY = "cvdocs.libraryView";
const DELETE_WARNING_KEY = "cvdocs.skipDeleteWarning";

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
  const catalog = useBlockCatalog({ storageKey: VIEW_STORAGE_KEY });
  const { blocks, setBlocks, loading, refetch, search, setSearch, visibleBlocks, viewMode, setViewMode } = catalog;

  const [generateOpen, setGenerateOpen] = useState(false);
  const [mutateBlockId, setMutateBlockId] = useState<string | null>(null);
  const [viewBlockId, setViewBlockId] = useState<string | null>(null);
  const [editBlockId, setEditBlockId] = useState<string | null>(null);
  const [deleteBlockId, setDeleteBlockId] = useState<string | null>(null);
  const [clearOpen, setClearOpen] = useState(false);
  const [dissectOpen, setDissectOpen] = useState(false);

  useEffect(() => {
    let cancelled = false;
    refetch().then((nextBlocks) => {
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

  const mutateBlock = mutateBlockId ? (blocks.find((block) => block.id === mutateBlockId) ?? null) : null;

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
    await refetch();
    toast.success(`Cleared ${result.deleted} block(s), kept ${result.skipped_preserved} preserved.`);
  }

  return (
    <div className="flex flex-col gap-4 p-6">
      <BlockGridLayout
        title={<h2 className="text-sm font-semibold">Library</h2>}
        search={search}
        onSearchChange={setSearch}
        viewMode={viewMode}
        onViewModeChange={setViewMode}
        loading={loading}
        loadingMessage="Loading library..."
        actions={
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
        }
        leading={
          <>
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
            {pendingJobs
              .filter((job) => job.kind !== "dissect")
              .map((job) => (
                <PendingBlockTile
                  key={job.jobId}
                  job={job}
                  viewMode={viewMode}
                  onDismiss={(jobId) => onDismissJob?.(jobId)}
                />
              ))}
          </>
        }
        items={visibleBlocks}
        getItemKey={(block) => block.id}
        renderItem={(block, mode) => (
          <BlockTile
            block={block}
            viewMode={mode}
            onView={() => setViewBlockId(block.id)}
            onMutate={() => setMutateBlockId(block.id)}
            onEdit={() => setEditBlockId(block.id)}
            onTogglePreserve={() => handleTogglePreserve(block)}
            onDelete={() => handleDeleteRequest(block.id)}
          />
        )}
        emptyMessage={
          pendingJobs.length === 0 && (
            <p className="text-muted-foreground">
              {blocks.length === 0 ? "The library is empty." : "No blocks match your search."}
            </p>
          )
        }
      />
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
            const nextBlock = toBlockRecord(updated);
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
