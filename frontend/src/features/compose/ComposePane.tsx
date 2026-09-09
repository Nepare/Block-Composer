import { useEffect, useRef, useState } from "react";
import type { ClearResultsResult, ResultDetail } from "@/features/compose/api";
import { HistorySidebar } from "@/features/compose/HistorySidebar";
import { ResultPanel } from "@/features/compose/ResultPanel";
import { SpecificationsPanel } from "@/features/compose/SpecificationsPanel";
import type { DisplayMode } from "@/features/compose/types";
import type { UseComposeJobResult } from "@/features/compose/useComposeJob";
import { useResultsHistory } from "@/features/compose/useResultsHistory";

interface ComposePaneProps {
  composeJob: UseComposeJobResult;
}

export function ComposePane({ composeJob }: ComposePaneProps) {
  const [displayMode, setDisplayMode] = useState<DisplayMode>({ type: "fresh" });
  const [historyDetail, setHistoryDetail] = useState<ResultDetail | null>(null);
  const [selectedBlockIds, setSelectedBlockIds] = useState<string[]>([]);
  const [freshKey, setFreshKey] = useState(0);
  const resultsHistory = useResultsHistory();
  const previousStatusRef = useRef(composeJob.status);
  // Once a resultId has been observed in the history list, treat it as permanently bridged —
  // otherwise deleting/clearing it later would make it look "not yet arrived" again and the
  // pending placeholder would come back from the dead.
  const bridgedResultIdsRef = useRef<Set<string>>(new Set());
  if (
    composeJob.status === "done" &&
    composeJob.resultId != null &&
    resultsHistory.summaries.some((summary) => summary.id === composeJob.resultId)
  ) {
    bridgedResultIdsRef.current.add(composeJob.resultId);
  }

  const isPendingVisible =
    composeJob.status === "running" ||
    (composeJob.status === "done" &&
      composeJob.resultId != null &&
      !bridgedResultIdsRef.current.has(composeJob.resultId));

  async function handleDelete(id: string): Promise<boolean> {
    const ok = await resultsHistory.deleteResult(id);
    if (ok && displayMode.type === "history" && displayMode.resultId === id) {
      setDisplayMode({ type: "fresh" });
    }
    return ok;
  }

  async function handleClearHistory(): Promise<ClearResultsResult | null> {
    const viewedId = displayMode.type === "history" ? displayMode.resultId : null;
    const viewedSummary = viewedId ? resultsHistory.summaries.find((summary) => summary.id === viewedId) : null;
    const result = await resultsHistory.clearHistory();
    if (result && viewedId && !viewedSummary?.preserved) {
      setDisplayMode({ type: "fresh" });
    }
    return result;
  }

  useEffect(() => {
    if (previousStatusRef.current !== "done" && composeJob.status === "done") {
      resultsHistory.refetch();
      if (composeJob.resultId != null) {
        setDisplayMode({ type: "history", resultId: composeJob.resultId });
      }
    }
    previousStatusRef.current = composeJob.status;
  }, [composeJob.status, composeJob.resultId, resultsHistory]);

  useEffect(() => {
    if (displayMode.type !== "history") {
      setHistoryDetail(null);
      return;
    }
    let cancelled = false;
    resultsHistory.getResult(displayMode.resultId).then((detail) => {
      if (!cancelled) setHistoryDetail(detail);
    });
    return () => {
      cancelled = true;
    };
  }, [displayMode, resultsHistory]);

  return (
    <div className="flex h-full min-h-0">
      <HistorySidebar
        summaries={resultsHistory.summaries}
        loading={resultsHistory.loading}
        displayMode={displayMode}
        onSelect={(resultId) => setDisplayMode({ type: "history", resultId })}
        isComposeRunning={composeJob.status === "running"}
        isPending={isPendingVisible}
        onNewComposition={() => {
          setDisplayMode({ type: "fresh" });
          setSelectedBlockIds([]);
          setFreshKey((key) => key + 1);
        }}
        onBackToLive={() => setDisplayMode({ type: "fresh" })}
        onRename={resultsHistory.renameResult}
        onPreserve={resultsHistory.preserveResult}
        onUnpreserve={resultsHistory.unpreserveResult}
        onDelete={handleDelete}
        onClearHistory={handleClearHistory}
      />
      <div className="flex min-h-0 min-w-0 flex-1">
        <div className="w-96 shrink-0 overflow-y-auto border-r">
          <SpecificationsPanel
            key={freshKey}
            composeJob={composeJob}
            displayMode={displayMode}
            historyDetail={historyDetail}
            selectedBlockIds={selectedBlockIds}
            onSelectionChange={setSelectedBlockIds}
          />
        </div>
        <div className="min-w-0 flex-1 overflow-y-auto bg-muted/40">
          <ResultPanel composeJob={composeJob} displayMode={displayMode} historyDetail={historyDetail} />
        </div>
      </div>
    </div>
  );
}
