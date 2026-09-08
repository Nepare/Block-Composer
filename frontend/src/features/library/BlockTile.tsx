import { Loader2, Pencil, RefreshCw, Shield, Trash2, X } from "lucide-react";
import { OriginIcon, type BlockOrigin } from "@/shared/icons/OriginIcon";
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
  variant: "outline" | "destructive";
}

export function BlockTile({ block, viewMode, onMutate, onEdit, onTogglePreserve, onDelete }: BlockTileProps) {
  const origin = originFromCreatedBy(block.created_by);
  const environmentText = block.environment.join(", ");
  const isList = viewMode === "list";

  const controls: ControlSpec[] = [
    { key: "mutate", label: "Mutate", icon: RefreshCw, handler: onMutate, variant: "outline" },
    { key: "edit", label: "Edit", icon: Pencil, handler: onEdit, variant: "outline" },
    {
      key: "preserve",
      label: block.preserved ? "Unpreserve" : "Preserve",
      icon: Shield,
      handler: onTogglePreserve,
      variant: "outline",
    },
    { key: "delete", label: "Delete", icon: Trash2, handler: onDelete, variant: "destructive" },
  ];

  return (
    <div
      data-testid="block-tile"
      className={cn(
        "flex gap-3 rounded-lg border bg-card p-3",
        block.preserved ? "border-2 border-primary" : "border-border",
        isList ? "flex-row items-center" : "flex-col"
      )}
    >
      <div className={cn("flex min-w-0 flex-1 gap-2", isList ? "flex-row items-center" : "flex-col")}>
        <OriginIcon origin={origin} />
        <div className="min-w-0 flex-1">
          <p className="truncate font-medium">{block.name}</p>
          {environmentText && (
            <Tooltip>
              <TooltipTrigger
                render={
                  <p
                    tabIndex={0}
                    className="line-clamp-2 text-xs text-muted-foreground"
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
      <div className={cn("flex shrink-0 gap-1", isList ? "flex-row" : "flex-col")}>
        {controls.map(({ key, label, icon: Icon, handler, variant }) => (
          <Button
            key={key}
            type="button"
            variant={variant}
            size={isList ? "icon-sm" : "sm"}
            disabled={!handler || (key === "delete" && block.preserved)}
            onClick={handler}
            aria-label={label}
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
        "flex gap-3 rounded-lg border border-dashed bg-card p-3",
        isError ? "border-destructive" : "border-border",
        isList ? "flex-row items-center" : "flex-col"
      )}
    >
      <div className={cn("flex min-w-0 flex-1 gap-2", isList ? "flex-row items-center" : "flex-col")}>
        <OriginIcon origin={origin} />
        <div className="min-w-0 flex-1">
          {isError ? (
            <>
              <p className="font-medium text-destructive">Failed</p>
              <p className="text-xs text-muted-foreground">{job.errorMessage}</p>
            </>
          ) : (
            <>
              <p className="flex items-center gap-1.5 font-medium">
                <Loader2 className="size-3.5 animate-spin" />
                Working...
              </p>
              {job.messages.length > 0 && (
                <ul className="text-xs text-muted-foreground">
                  {job.messages.map((message, index) => (
                    <li key={index}>{message}</li>
                  ))}
                </ul>
              )}
            </>
          )}
        </div>
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
