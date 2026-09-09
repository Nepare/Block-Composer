import { CheckCircle2, Circle } from "lucide-react";
import type { PlanStep } from "@/features/compose/useComposeJob";
import { Spinner } from "@/shared/ui/Spinner";
import { cn } from "@/shared/lib/utils";

const ACTION_LABELS: Record<PlanStep["action"], string> = {
  use: "Use existing block",
  mutate: "Mutate block",
  generate: "Generate new block",
};

interface ComposePlanProps {
  planSteps: PlanStep[];
}

export function ComposePlan({ planSteps }: ComposePlanProps) {
  if (planSteps.length === 0) return null;

  return (
    <ol className="flex flex-col gap-2" aria-label="Composition plan">
      {[...planSteps]
        .sort((a, b) => a.order - b.order)
        .map((step) => (
          <li
            key={step.order}
            data-testid="plan-step"
            data-status={step.liveStatus}
            className={cn(
              "flex items-center gap-3 rounded-xl border px-3 py-2 text-sm transition-colors",
              step.liveStatus === "done" && "border-primary/40 bg-primary/5",
              step.liveStatus === "running" && "border-ring/60 bg-accent/40",
              step.liveStatus === "pending" && "border-border text-muted-foreground"
            )}
          >
            {step.liveStatus === "done" && <CheckCircle2 className="size-4 shrink-0 text-primary" />}
            {step.liveStatus === "running" && <Spinner className="shrink-0" />}
            {step.liveStatus === "pending" && <Circle className="size-4 shrink-0 text-muted-foreground" />}
            <span className="flex-1">
              {ACTION_LABELS[step.action]}
              {step.criteria && <span className="text-muted-foreground"> — {step.criteria}</span>}
            </span>
          </li>
        ))}
    </ol>
  );
}
