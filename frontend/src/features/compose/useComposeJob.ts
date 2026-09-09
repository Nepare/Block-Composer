import { useCallback, useRef, useState } from "react";
import { streamUrl } from "@/shared/api";
import { cancelJob, type ResultSlot } from "@/features/compose/api";

export type ComposeJobStatus = "idle" | "running" | "done" | "cancelled" | "error";

export interface PlanStep {
  order: number;
  action: "use" | "mutate" | "generate" | "finalize";
  blockId: string | null;
  criteria: string | null;
  liveStatus: "pending" | "running" | "done";
}

export interface ComposeJobState {
  jobId: string | null;
  status: ComposeJobStatus;
  planSteps: PlanStep[];
  progress: { step: number; total: number } | null;
  messages: string[];
  resultId: string | null;
  name: string | null;
  content: string | null;
  slots: ResultSlot[] | null;
  errorMessage: string | null;
}

export interface UseComposeJobResult extends ComposeJobState {
  start: (jobId: string) => void;
  reconnect: (jobId: string) => void;
  cancel: () => void;
}

interface PlanFrameStep {
  order: number;
  action: "use" | "mutate" | "generate" | "finalize";
  block_id: string | null;
  criteria: string | null;
}

interface ProgressFrame {
  kind: string;
  message?: string | null;
  step?: number | null;
  total?: number | null;
  data?: { steps?: PlanFrameStep[] } | null;
}

interface CompleteFrame {
  status: "running" | "done" | "cancelled" | "error";
  result_id?: string | null;
  name?: string | null;
  content?: string | null;
  cancelled?: boolean;
  slots?: ResultSlot[] | null;
  error?: string | null;
}

const STORAGE_KEY = "cvdocs.pendingComposeJob";
const MAX_MESSAGES = 3;

// Slot-scoped frame kinds that resolve to a plan step's liveStatus (matched by
// `step === order`, per contracts/compose-sse-stream.md — never by block_id).
const SLOT_STATUS_BY_KIND: Record<string, PlanStep["liveStatus"]> = {
  use: "done",
  mutate_start: "running",
  mutate_done: "done",
  generate_start: "running",
  generate_done: "done",
  finalize_start: "running",
  finalize_done: "done",
};

const MESSAGE_KINDS = new Set([
  "keyword_extraction_start",
  "keyword_extraction_done",
  "narrowing_done",
  "narrowing_skipped",
  "warning",
  "plan_start",
  "plan_retry",
  "plan_done",
  "naming",
]);

const initialState: ComposeJobState = {
  jobId: null,
  status: "idle",
  planSteps: [],
  progress: null,
  messages: [],
  resultId: null,
  name: null,
  content: null,
  slots: null,
  errorMessage: null,
};

export function readStoredComposeJobId(): string | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as { jobId?: string };
    return parsed.jobId ?? null;
  } catch {
    return null;
  }
}

function writeStoredJob(jobId: string): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ jobId }));
  } catch {
    // storage unavailable — reload recovery just won't work this session
  }
}

function removeStoredJob(): void {
  try {
    localStorage.removeItem(STORAGE_KEY);
  } catch {
    // storage unavailable — nothing to clear
  }
}

function applyFrame(prev: ComposeJobState, frame: ProgressFrame): ComposeJobState {
  let next = prev;

  if (frame.kind === "plan" && frame.data?.steps) {
    next = {
      ...next,
      planSteps: frame.data.steps.map((step) => ({
        order: step.order,
        action: step.action,
        blockId: step.block_id,
        criteria: step.criteria,
        liveStatus: "pending",
      })),
    };
  } else {
    const liveStatus = SLOT_STATUS_BY_KIND[frame.kind];
    if (liveStatus) {
      next = {
        ...next,
        planSteps: next.planSteps.map((step) => (step.order === frame.step ? { ...step, liveStatus } : step)),
      };
    } else if (MESSAGE_KINDS.has(frame.kind) && frame.message) {
      next = { ...next, messages: [...next.messages, frame.message].slice(-MAX_MESSAGES) };
    }
  }

  if (frame.step != null && frame.total != null) {
    next = { ...next, progress: { step: frame.step, total: frame.total } };
  }

  return next;
}

function applyComplete(prev: ComposeJobState, outcome: CompleteFrame): ComposeJobState {
  if (outcome.status === "done") {
    return {
      ...prev,
      status: "done",
      resultId: outcome.result_id ?? null,
      name: outcome.name ?? null,
      content: outcome.content ?? null,
      slots: outcome.slots ?? null,
    };
  }
  if (outcome.status === "cancelled" || outcome.cancelled) {
    return { ...prev, status: "cancelled", resultId: null };
  }
  if (outcome.status === "error") {
    return { ...prev, status: "error", errorMessage: outcome.error ?? "The composition failed." };
  }
  return prev;
}

export function useComposeJob(): UseComposeJobResult {
  const [state, setState] = useState<ComposeJobState>(initialState);
  const sourceRef = useRef<EventSource | null>(null);

  // mirror=true (start) writes the localStorage entry so a reload can recover; mirror=false
  // (reconnect) leaves whatever entry is already there untouched. isReconnect governs what a
  // pre-first-frame error means: a fresh start's stream hiccup is a real error, but a
  // reconnect's is a stale job (e.g. a backend restart) — drop it and fall back to fresh state.
  const openStream = useCallback((jobId: string, mirror: boolean, isReconnect: boolean) => {
    setState({ ...initialState, jobId, status: "running" });
    if (mirror) writeStoredJob(jobId);

    const source = new EventSource(streamUrl(jobId));
    sourceRef.current = source;
    let receivedFrame = false;

    source.onmessage = (event) => {
      receivedFrame = true;
      try {
        const frame = JSON.parse(event.data) as ProgressFrame;
        setState((prev) => applyFrame(prev, frame));
      } catch {
        // malformed frame — ignore, the terminal complete frame is what actually matters
      }
    };

    source.addEventListener("complete", ((event: MessageEvent) => {
      receivedFrame = true;
      source.close();
      sourceRef.current = null;
      removeStoredJob();

      let outcome: CompleteFrame = { status: "error" };
      try {
        outcome = JSON.parse(event.data) as CompleteFrame;
      } catch {
        // fall through to the error status set above
      }
      setState((prev) => applyComplete(prev, outcome));
    }) as EventListener);

    source.onerror = () => {
      if (receivedFrame) return;
      source.close();
      sourceRef.current = null;
      if (isReconnect) {
        removeStoredJob();
        setState(initialState);
      }
    };
  }, []);

  const start = useCallback((jobId: string) => openStream(jobId, true, false), [openStream]);

  const reconnect = useCallback((jobId: string) => openStream(jobId, false, true), [openStream]);

  const cancel = useCallback(() => {
    if (state.jobId) cancelJob(state.jobId);
  }, [state.jobId]);

  return { ...state, start, reconnect, cancel };
}
