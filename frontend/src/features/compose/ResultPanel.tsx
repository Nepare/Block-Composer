import { ComposePlan } from "@/features/compose/ComposePlan";
import type { UseComposeJobResult } from "@/features/compose/useComposeJob";
import type { ResultDetail, ResultSlot } from "@/features/compose/api";
import type { DisplayMode } from "@/features/compose/types";
import { Button } from "@/shared/ui/button";

const ACTION_LABELS: Record<ResultSlot["action"], string> = {
  use: "Used existing block",
  mutate: "Mutated block",
  generate: "Generated new block",
};

interface ResultPanelProps {
  composeJob: UseComposeJobResult;
  displayMode: DisplayMode;
  historyDetail?: ResultDetail | null;
}

function ProgressBar({ progress }: { progress: UseComposeJobResult["progress"] }) {
  const pct = progress && progress.total > 0 ? Math.min(100, Math.round((progress.step / progress.total) * 100)) : 0;
  return (
    <div
      role="progressbar"
      aria-valuenow={pct}
      aria-valuemin={0}
      aria-valuemax={100}
      className="h-2 w-full overflow-hidden rounded-full bg-muted"
    >
      <div className="h-full rounded-full bg-primary transition-all" style={{ width: `${pct}%` }} />
    </div>
  );
}

export function ResultPanel({ composeJob, displayMode, historyDetail = null }: ResultPanelProps) {
  // A history selection always takes over the display, regardless of a background job's own
  // status — the running job itself is untouched (FR-017/FR-018), only what's shown switches.
  if (displayMode.type === "history") {
    if (!historyDetail) {
      return (
        <div
          className="flex h-full flex-col items-center justify-center gap-2 p-6 text-center text-muted-foreground"
          data-testid="result-panel-history-loading"
        >
          <p>Loading...</p>
        </div>
      );
    }
    return (
      <div className="flex flex-col gap-3 p-6" data-testid="result-panel-history">
        <h3 className="text-sm font-semibold">{historyDetail.name}</h3>
        <pre className="whitespace-pre-wrap rounded-xl border bg-card p-4 text-sm">{historyDetail.content}</pre>
        {historyDetail.slots.length > 0 && (
          <ol className="flex flex-col gap-2" aria-label="Composition steps">
            {historyDetail.slots.map((slot) => (
              <li key={slot.order} data-testid="history-slot" className="rounded-xl border px-3 py-2 text-sm">
                {ACTION_LABELS[slot.action]}
                {slot.criteria && <span className="text-muted-foreground"> — {slot.criteria}</span>}
              </li>
            ))}
          </ol>
        )}
      </div>
    );
  }

  if (composeJob.status === "running") {
    return (
      <div className="flex flex-col gap-4 p-6" data-testid="result-panel-running">
        <div className="flex items-center gap-3">
          <div className="flex-1">
            <ProgressBar progress={composeJob.progress} />
          </div>
          <Button type="button" variant="outline" size="sm" onClick={() => composeJob.cancel()}>
            Cancel
          </Button>
        </div>
        {composeJob.messages.length > 0 && (
          <p className="text-sm text-muted-foreground">{composeJob.messages[composeJob.messages.length - 1]}</p>
        )}
        <ComposePlan planSteps={composeJob.planSteps} />
      </div>
    );
  }

  if (composeJob.status === "done") {
    return (
      <div className="flex flex-col gap-3 p-6" data-testid="result-panel-done">
        <h3 className="text-sm font-semibold">{composeJob.name}</h3>
        <pre className="whitespace-pre-wrap rounded-xl border bg-card p-4 text-sm">{composeJob.content}</pre>
      </div>
    );
  }

  if (composeJob.status === "cancelled") {
    return (
      <div
        className="flex h-full flex-col items-center justify-center gap-2 p-6 text-center text-muted-foreground"
        data-testid="result-panel-cancelled"
      >
        <p>Composition cancelled — no history entry was created.</p>
      </div>
    );
  }

  if (composeJob.status === "error") {
    return (
      <div
        className="flex h-full flex-col items-center justify-center gap-2 p-6 text-center text-destructive"
        data-testid="result-panel-error"
      >
        <p className="font-semibold">Composition failed</p>
        <p className="text-sm">{composeJob.errorMessage ?? "The composition failed."}</p>
      </div>
    );
  }

  return (
    <div
      className="flex h-full flex-col items-center justify-center gap-2 p-6 text-center text-muted-foreground"
      data-testid="result-panel-idle"
    >
      <p>Describe a composition and hit Compose to see it run here.</p>
    </div>
  );
}
