import { useRef, useState } from "react";
import { ArrowLeft, ChevronLeft, ChevronRight, Shield, Trash2 } from "lucide-react";
import { toast } from "sonner";
import type { ClearResultsResult, ResultSummary } from "@/features/compose/api";
import type { DisplayMode } from "@/features/compose/types";
import { Button } from "@/shared/ui/button";
import { ConfirmDialog } from "@/shared/ui/ConfirmDialog";
import { cn } from "@/shared/lib/utils";

const DELETE_WARNING_KEY = "cvdocs.skipComposeDeleteWarning";

interface HistorySidebarProps {
  summaries: ResultSummary[];
  loading: boolean;
  displayMode: DisplayMode;
  onSelect: (resultId: string) => void;
  isComposeRunning: boolean;
  onBackToLive: () => void;
  onRename: (id: string, name: string) => Promise<boolean>;
  onPreserve: (id: string) => Promise<boolean>;
  onUnpreserve: (id: string) => Promise<boolean>;
  onDelete: (id: string) => Promise<boolean>;
  onClearHistory: () => Promise<ClearResultsResult | null>;
}

export function HistorySidebar({
  summaries,
  loading,
  displayMode,
  onSelect,
  isComposeRunning,
  onBackToLive,
  onRename,
  onPreserve,
  onUnpreserve,
  onDelete,
  onClearHistory,
}: HistorySidebarProps) {
  const [collapsed, setCollapsed] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [draftName, setDraftName] = useState("");
  // Guards against a rename committing twice — once from an explicit Enter, once
  // from the input's own blur when it unmounts right after.
  const editLockRef = useRef(false);
  const [deleteId, setDeleteId] = useState<string | null>(null);
  const [clearOpen, setClearOpen] = useState(false);

  function startEdit(summary: ResultSummary) {
    editLockRef.current = false;
    setEditingId(summary.id);
    setDraftName(summary.name);
  }

  function cancelEdit() {
    editLockRef.current = true;
    setEditingId(null);
  }

  async function commitEdit(id: string, value: string) {
    if (editLockRef.current) return;
    editLockRef.current = true;
    setEditingId(null);
    const trimmed = value.trim();
    if (!trimmed) return;
    await onRename(id, trimmed);
  }

  function handleDeleteRequest(id: string) {
    let skip = false;
    try {
      skip = localStorage.getItem(DELETE_WARNING_KEY) === "true";
    } catch {
      skip = false;
    }
    if (skip) {
      onDelete(id);
      return;
    }
    setDeleteId(id);
  }

  async function handleClearConfirm() {
    const result = await onClearHistory();
    if (result) {
      toast.success(`Cleared ${result.deleted} composition(s), kept ${result.skipped_preserved} preserved.`);
    }
  }

  const showBackToLive = isComposeRunning && displayMode.type !== "fresh";

  return (
    <div
      className={cn(
        "flex shrink-0 flex-col border-r bg-muted/40 transition-[width] duration-200 ease-in-out",
        collapsed ? "w-11" : "w-64"
      )}
    >
      <div className="flex items-center justify-between gap-2 border-b p-2">
        {!collapsed && <h2 className="px-1 text-sm font-semibold">History</h2>}
        <Button
          type="button"
          variant="ghost"
          size="icon-sm"
          aria-label={collapsed ? "Expand history" : "Collapse history"}
          onClick={() => setCollapsed((prev) => !prev)}
        >
          {collapsed ? <ChevronRight /> : <ChevronLeft />}
        </Button>
      </div>
      {!collapsed && (
        <>
          {showBackToLive && (
            <button
              type="button"
              data-testid="back-to-live"
              onClick={onBackToLive}
              className="mx-2 mt-2 flex items-center gap-2 rounded-lg border border-primary/40 bg-primary/5 px-2.5 py-2 text-left text-sm font-medium text-primary transition-colors hover:bg-primary/10"
            >
              <ArrowLeft className="size-4" />
              Back to live composition
            </button>
          )}
          <div className="flex flex-1 flex-col gap-1 overflow-y-auto p-2">
            {loading && <p className="p-2 text-sm text-muted-foreground">Loading...</p>}
            {!loading && summaries.length === 0 && (
              <p className="p-2 text-sm text-muted-foreground">No compositions yet.</p>
            )}
            {summaries.map((summary) => {
              const isActive = displayMode.type === "history" && displayMode.resultId === summary.id;
              const isEditing = editingId === summary.id;
              return (
                <div
                  key={summary.id}
                  data-testid="history-entry"
                  data-preserved={summary.preserved}
                  className={cn(
                    "group flex items-center gap-1 rounded-lg border px-2.5 py-2 text-sm transition-colors hover:bg-muted",
                    summary.preserved ? "border-2 border-primary" : "border-transparent",
                    isActive && "bg-muted font-medium"
                  )}
                >
                  {isEditing ? (
                    <input
                      autoFocus
                      value={draftName}
                      onChange={(event) => setDraftName(event.target.value)}
                      onBlur={(event) => commitEdit(summary.id, event.currentTarget.value)}
                      onKeyDown={(event) => {
                        if (event.key === "Enter") {
                          event.preventDefault();
                          commitEdit(summary.id, draftName);
                        }
                        if (event.key === "Escape") {
                          event.preventDefault();
                          cancelEdit();
                        }
                      }}
                      className="min-w-0 flex-1 rounded border bg-background px-1.5 py-0.5 text-sm"
                    />
                  ) : (
                    <button
                      type="button"
                      onClick={() => onSelect(summary.id)}
                      onDoubleClick={() => startEdit(summary)}
                      className="line-clamp-1 min-w-0 flex-1 text-left"
                    >
                      {summary.name}
                    </button>
                  )}
                  <div className="flex shrink-0 items-center gap-0.5 opacity-0 transition-opacity group-hover:opacity-100 group-focus-within:opacity-100">
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon-sm"
                      aria-label={summary.preserved ? "Unpreserve" : "Preserve"}
                      onClick={() => (summary.preserved ? onUnpreserve(summary.id) : onPreserve(summary.id))}
                    >
                      <Shield />
                    </Button>
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon-sm"
                      aria-label="Delete"
                      disabled={summary.preserved}
                      onClick={() => handleDeleteRequest(summary.id)}
                      className="text-destructive hover:bg-destructive/10 hover:text-destructive"
                    >
                      <Trash2 />
                    </Button>
                  </div>
                </div>
              );
            })}
          </div>
          <div className="border-t p-2">
            <Button
              type="button"
              variant="outline"
              className="w-full gap-2 border-2 border-destructive text-destructive hover:bg-destructive/10 hover:text-destructive"
              onClick={() => setClearOpen(true)}
            >
              <Trash2 className="size-4" />
              Clear history
            </Button>
          </div>
        </>
      )}
      {deleteId && (
        <ConfirmDialog
          open={deleteId !== null}
          onOpenChange={(next) => {
            if (!next) setDeleteId(null);
          }}
          title="Delete composition"
          description="This can't be undone."
          suppressionKey={DELETE_WARNING_KEY}
          onConfirm={() => {
            if (deleteId) onDelete(deleteId);
          }}
        />
      )}
      <ConfirmDialog
        open={clearOpen}
        onOpenChange={setClearOpen}
        title="Clear history"
        description="This removes every unpreserved composition. This can't be undone."
        onConfirm={handleClearConfirm}
      />
    </div>
  );
}
