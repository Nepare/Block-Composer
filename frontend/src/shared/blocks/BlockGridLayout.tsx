import { Fragment, type ReactNode } from "react";
import { Grid2x2, Grid3x3, List, Search } from "lucide-react";
import { Button } from "@/shared/ui/button";
import { Input } from "@/shared/ui/input";
import { Spinner } from "@/shared/ui/Spinner";
import { cn } from "@/shared/lib/utils";
import type { BlockViewMode } from "@/shared/blocks/types";

const VIEW_MODES: { value: BlockViewMode; label: string; icon: typeof List }[] = [
  { value: "list", label: "List", icon: List },
  { value: "grid-2", label: "2-column", icon: Grid2x2 },
  { value: "grid-3", label: "3-column", icon: Grid3x3 },
];

export interface BlockGridLayoutProps<T> {
  title?: ReactNode;
  search: string;
  onSearchChange: (value: string) => void;
  searchPlaceholder?: string;
  viewMode: BlockViewMode;
  onViewModeChange: (mode: BlockViewMode) => void;
  actions?: ReactNode;
  loading?: boolean;
  loadingMessage?: ReactNode;
  leading?: ReactNode;
  items: T[];
  getItemKey: (item: T) => string;
  renderItem: (item: T, viewMode: BlockViewMode) => ReactNode;
  emptyMessage?: ReactNode;
}

// Responsive grid/list shell, search input, and view-mode toggle shared by Library's
// grid and the block picker — each feature supplies its own tile via renderItem.
export function BlockGridLayout<T>({
  title,
  search,
  onSearchChange,
  searchPlaceholder = "Search blocks",
  viewMode,
  onViewModeChange,
  actions,
  loading = false,
  loadingMessage = "Loading...",
  leading,
  items,
  getItemKey,
  renderItem,
  emptyMessage,
}: BlockGridLayoutProps<T>) {
  const gridClassName = cn(
    viewMode === "list" && "flex flex-col gap-2",
    viewMode === "grid-2" && "grid grid-cols-1 gap-3 sm:grid-cols-2",
    viewMode === "grid-3" && "grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3"
  );

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        {title}
        <div className="flex items-center gap-3">
          <div className="relative w-full max-w-xs">
            <Search className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              placeholder={searchPlaceholder}
              aria-label={searchPlaceholder}
              value={search}
              onChange={(event) => onSearchChange(event.target.value)}
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
                onClick={() => onViewModeChange(value)}
              >
                <Icon />
              </Button>
            ))}
          </div>
        </div>
      </div>
      {actions}
      {loading ? (
        <p className="flex items-center gap-2 text-muted-foreground">
          <Spinner /> {loadingMessage}
        </p>
      ) : (
        <>
          <div className={gridClassName}>
            {leading}
            {items.map((item) => (
              <Fragment key={getItemKey(item)}>{renderItem(item, viewMode)}</Fragment>
            ))}
          </div>
          {items.length === 0 && emptyMessage}
        </>
      )}
    </div>
  );
}
