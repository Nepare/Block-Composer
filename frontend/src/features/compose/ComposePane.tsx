import { useEffect, useRef, useState } from "react";
import type { ResultDetail } from "@/features/compose/api";
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
  const resultsHistory = useResultsHistory();
  const previousStatusRef = useRef(composeJob.status);

  useEffect(() => {
    if (previousStatusRef.current !== "done" && composeJob.status === "done") {
      resultsHistory.refetch();
    }
    previousStatusRef.current = composeJob.status;
  }, [composeJob.status, resultsHistory]);

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
        onNewComposition={() => setDisplayMode({ type: "fresh" })}
        onBackToLive={() => setDisplayMode({ type: "fresh" })}
        onRename={resultsHistory.renameResult}
        onPreserve={resultsHistory.preserveResult}
        onUnpreserve={resultsHistory.unpreserveResult}
        onDelete={resultsHistory.deleteResult}
        onClearHistory={resultsHistory.clearHistory}
      />
      <div className="flex min-h-0 min-w-0 flex-1">
        <div className="w-96 shrink-0 overflow-y-auto border-r">
          <SpecificationsPanel
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
