import { Pencil, RefreshCw, Shield, Trash2, X } from "lucide-react";
import { GeneratingSpinner, OriginIcon, type BlockOrigin } from "@/shared/icons/OriginIcon";
import type { PendingJob } from "@/features/library/useLibraryJobs";
import { Button } from "@/shared/ui/button";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/shared/ui/tooltip";
import { cn } from "@/shared/lib/utils";

export type LibraryViewMode = "list" | "grid-2" | "grid-3";

export interface LibraryBlockRecord {
  id: string;
  name: string;
  created_at: string | null;
  created_by: string;
  environment: string[];
  preserved: boolean;
}

export function originFromCreatedBy(createdBy: string): BlockOrigin {
  if (createdBy === "dissected" || createdBy === "mutated" || createdBy === "generated") {
    return createdBy;
  }
  return "manual";
}

interface BlockTileProps {
  block: LibraryBlockRecord;
  viewMode: LibraryViewMode;
  onView?: () => void;
  onMutate?: () => void;
  onEdit?: () => void;
  onTogglePreserve?: () => void;
  onDelete?: () => void;
}

interface ControlSpec {
  key: string;
  label: string;
  icon: typeof RefreshCw;
  handler?: () => void;
}

export function BlockTile({ block, viewMode, onView, onMutate, onEdit, onTogglePreserve, onDelete }: BlockTileProps) {
  const origin = originFromCreatedBy(block.created_by);
  const environmentText = block.environment.join(", ");
  const isList = viewMode === "list";

  const controls: ControlSpec[] = [
    { key: "mutate", label: "Mutate", icon: RefreshCw, handler: onMutate },
    { key: "edit", label: "Edit", icon: Pencil, handler: onEdit },
    { key: "preserve", label: block.preserved ? "Unpreserve" : "Preserve", icon: Shield, handler: onTogglePreserve },
    { key: "delete", label: "Delete", icon: Trash2, handler: onDelete },
  ];

  return (
    <div
      data-testid="block-tile"
      role="button"
      tabIndex={0}
      onClick={onView}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          onView?.();
        }
      }}
      className={cn(
        "flex cursor-pointer overflow-hidden rounded-2xl border bg-card transition-shadow hover:shadow-md",
        block.preserved ? "border-2 border-primary" : "border-border"
      )}
    >
      <div
        className={cn(
          "flex min-w-0 flex-1 items-start gap-3 p-4",
          isList && "flex-row items-center"
        )}
      >
        <OriginIcon origin={origin} />
        <div className="min-w-0 flex-1">
          <p
            className={cn(
              "font-semibold text-foreground",
              isList ? "truncate text-sm" : "line-clamp-3 text-base"
            )}
          >
            {block.name}
          </p>
          {environmentText && (
            <Tooltip>
              <TooltipTrigger
                render={
                  <p
                    tabIndex={0}
                    className="line-clamp-2 mt-1 w-fit max-w-full cursor-help text-xs leading-relaxed text-muted-foreground underline decoration-dotted decoration-muted-foreground/40 underline-offset-2"
                    title={environmentText}
                  />
                }
              >
                {environmentText}
              </TooltipTrigger>
              <TooltipContent>{environmentText}</TooltipContent>
            </Tooltip>
          )}
        </div>
      </div>
      <div
        className={cn(
          "flex shrink-0 gap-0.5 border-l border-border px-1.5",
          isList ? "flex-row items-center" : "w-28 flex-col justify-center py-2"
        )}
      >
        {controls.map(({ key, label, icon: Icon, handler }) => (
          <Button
            key={key}
            type="button"
            variant="ghost"
            size={isList ? "icon-sm" : "sm"}
            disabled={!handler || (key === "delete" && block.preserved)}
            onClick={(event) => {
              event.stopPropagation();
              handler?.();
            }}
            aria-label={label}
            className={cn(
              !isList && "w-full justify-start gap-2 rounded-lg px-2 text-muted-foreground",
              key === "delete" && "text-destructive hover:bg-destructive/10 hover:text-destructive",
              key === "delete" && block.preserved && "disabled:opacity-30"
            )}
          >
            <Icon />
            <span className={cn(isList && "sr-only")}>{label}</span>
          </Button>
        ))}
      </div>
    </div>
  );
}

const JOB_KIND_ORIGIN: Record<PendingJob["kind"], BlockOrigin> = {
  generate: "generated",
  mutate: "mutated",
  dissect: "manual",
};

interface PendingBlockTileProps {
  job: PendingJob;
  viewMode: LibraryViewMode;
  onDismiss: (jobId: string) => void;
}

export function PendingBlockTile({ job, viewMode, onDismiss }: PendingBlockTileProps) {
  const origin = JOB_KIND_ORIGIN[job.kind];
  const isList = viewMode === "list";
  const isError = job.status === "error";

  return (
    <div
      data-testid="pending-block-tile"
      className={cn(
        "flex gap-3 rounded-2xl border-2 border-dashed bg-card p-4 opacity-80",
        isError ? "border-destructive" : "border-border",
        isList ? "flex-row items-center" : "flex-col items-start"
      )}
    >
      <div className="flex min-w-0 flex-1 items-center gap-3">
        {isError ? (
          <>
            <OriginIcon origin={origin} />
            <div className="min-w-0 flex-1">
              <p className="text-sm font-semibold text-destructive">Failed</p>
              <p className="mt-1 text-xs text-muted-foreground">{job.errorMessage}</p>
            </div>
          </>
        ) : (
          <>
            <GeneratingSpinner origin={origin} />
            <ul className="min-w-0 flex-1 text-xs text-muted-foreground">
              {job.messages.length > 0 ? (
                job.messages.map((message, index) => <li key={index}>{message}</li>)
              ) : (
                <li className="text-muted-foreground/70">Working…</li>
              )}
            </ul>
          </>
        )}
      </div>
      {isError && (
        <div className={cn("flex shrink-0 gap-1", isList ? "flex-row" : "flex-col")}>
          <Button
            type="button"
            variant="outline"
            size={isList ? "icon-sm" : "sm"}
            onClick={() => onDismiss(job.jobId)}
            aria-label="Dismiss"
          >
            <X />
            <span className={cn(isList && "sr-only")}>Dismiss</span>
          </Button>
        </div>
      )}
    </div>
  );
}
