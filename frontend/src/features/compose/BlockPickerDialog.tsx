import { useEffect, useState } from "react";
import { Modal } from "@/shared/ui/Modal";
import { Button } from "@/shared/ui/button";
import { Checkbox } from "@/shared/ui/checkbox";
import { OriginIcon } from "@/shared/icons/OriginIcon";
import { BlockGridLayout } from "@/shared/blocks/BlockGridLayout";
import { useBlockCatalog } from "@/shared/blocks/useBlockCatalog";
import { originFromCreatedBy, type BlockViewMode, type LibraryBlockRecord } from "@/shared/blocks/types";
import { cn } from "@/shared/lib/utils";

// Deliberately reuses Library's own view-mode key (data-model.md's "Block-picker view
// preference") so a user's list/2-col/3-col choice stays consistent across both surfaces.
const VIEW_STORAGE_KEY = "cvdocs.libraryView";

interface BlockPickerDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  initialSelectedIds: string[];
  onDone: (ids: string[]) => void;
}

export function BlockPickerDialog({ open, onOpenChange, initialSelectedIds, onDone }: BlockPickerDialogProps) {
  const { blocks, loading, refetch, search, setSearch, visibleBlocks, viewMode, setViewMode } = useBlockCatalog({
    storageKey: VIEW_STORAGE_KEY,
  });
  const [selected, setSelected] = useState<Set<string>>(new Set(initialSelectedIds));

  useEffect(() => {
    if (!open) return;
    setSelected(new Set(initialSelectedIds));
    refetch();
    // Re-seed selection and refetch only when the dialog is (re)opened — not on every
    // render, and not merely because the caller's selected-ids array reference changed.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  function toggle(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function handleDone() {
    onDone(Array.from(selected));
  }

  return (
    <Modal
      open={open}
      onOpenChange={onOpenChange}
      title="Select exact blocks"
      description="Choose the exact blocks this composition may draw from."
      contentClassName="flex max-h-[85vh] flex-col overflow-hidden sm:max-w-4xl"
    >
      <div className="flex min-h-0 flex-1 flex-col gap-4">
        <div className="min-h-0 flex-1 overflow-y-auto">
          <BlockGridLayout
            search={search}
            onSearchChange={setSearch}
            viewMode={viewMode}
            onViewModeChange={setViewMode}
            loading={loading}
            loadingMessage="Loading library..."
            items={visibleBlocks}
            getItemKey={(block) => block.id}
            renderItem={(block, mode) => (
              <PickerTile block={block} viewMode={mode} checked={selected.has(block.id)} onToggle={() => toggle(block.id)} />
            )}
            emptyMessage={
              <p className="text-muted-foreground">
                {blocks.length === 0 ? "The library is empty." : "No blocks match your search."}
              </p>
            }
          />
        </div>
        <div className="flex items-center justify-between gap-3 border-t pt-4">
          <p className="text-sm text-muted-foreground">{selected.size} selected</p>
          <div className="flex gap-2">
            <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="button" onClick={handleDone}>
              Done
            </Button>
          </div>
        </div>
      </div>
    </Modal>
  );
}

interface PickerTileProps {
  block: LibraryBlockRecord;
  viewMode: BlockViewMode;
  checked: boolean;
  onToggle: () => void;
}

// Library's own control-rail tile, but stripped to a single selection checkbox — no
// mutate/edit/preserve/delete actions belong in a picker dedicated to selection only.
function PickerTile({ block, viewMode, checked, onToggle }: PickerTileProps) {
  const origin = originFromCreatedBy(block.created_by);
  const environmentText = block.environment.join(", ");
  const isList = viewMode === "list";

  return (
    <div
      data-testid="picker-tile"
      role="button"
      tabIndex={0}
      onClick={onToggle}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          onToggle();
        }
      }}
      className={cn(
        "flex cursor-pointer items-start gap-3 overflow-hidden rounded-2xl border bg-card p-4 transition-shadow hover:shadow-md",
        isList && "flex-row items-center",
        checked ? "border-2 border-primary" : "border-border"
      )}
    >
      <Checkbox
        checked={checked}
        onCheckedChange={onToggle}
        onClick={(event) => event.stopPropagation()}
        aria-label={`Select ${block.name}`}
      />
      <OriginIcon origin={origin} />
      <div className="min-w-0 flex-1">
        <p className={cn("font-semibold text-foreground", isList ? "truncate text-sm" : "line-clamp-3 text-base")}>
          {block.name}
        </p>
        {environmentText && (
          <p className="mt-1 line-clamp-2 text-xs text-muted-foreground" title={environmentText}>
            {environmentText}
          </p>
        )}
      </div>
    </div>
  );
}
