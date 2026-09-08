import { useCallback, useEffect, useRef, useState } from "react";
import { streamUrl } from "@/features/library/api";

export type JobKind = "generate" | "mutate" | "dissect";

export interface PendingJob {
  jobId: string;
  kind: JobKind;
  messages: string[];
  status: "running" | "resolving" | "error";
  resultBlockId: string | null;
  errorMessage: string | null;
}

interface StoredJob {
  jobId: string;
  kind: JobKind;
}

interface CompleteOutcome {
  status: "running" | "done" | "cancelled" | "error";
  block_id?: string | null;
  duplicate?: boolean;
  duplicate_of?: string | null;
  error?: string;
  saved?: { block_id: string; name: string }[];
  skipped_duplicates?: { name: string; duplicate_of: string }[];
  variants?: { block_id: string; name: string; label: string }[];
}

export interface DissectOutcome {
  saved: { block_id: string; name: string }[];
  skipped_duplicates: { name: string; duplicate_of: string }[];
  variants: { block_id: string; name: string; label: string }[];
}

export interface StartJobMeta {
  preserve?: boolean;
}

export interface UseLibraryJobsOptions {
  onRefetchNeeded: () => void;
  onDuplicate?: (kind: JobKind, duplicateOf: string | null) => void;
  onDissectComplete?: (jobId: string, outcome: DissectOutcome, preserveRequested: boolean) => void;
  onDissectError?: (jobId: string, message: string) => void;
}

export interface UseLibraryJobsResult {
  jobs: PendingJob[];
  start: (kind: JobKind, jobId: string, meta?: StartJobMeta) => void;
  reconnect: (kind: JobKind, jobId: string) => void;
  confirmResolved: (jobId: string) => void;
  dismiss: (jobId: string) => void;
}

const STORAGE_KEY = "cvdocs.pendingJobs";
const MAX_MESSAGES = 3;

export function readStoredJobs(): StoredJob[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function writeStoredJobs(jobs: StoredJob[]): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(jobs));
  } catch {
    // storage unavailable — reload recovery just won't work this session
  }
}

function addStoredJob(jobId: string, kind: JobKind): void {
  const jobs = readStoredJobs();
  if (jobs.some((job) => job.jobId === jobId)) return;
  writeStoredJobs([...jobs, { jobId, kind }]);
}

function removeStoredJob(jobId: string): void {
  writeStoredJobs(readStoredJobs().filter((job) => job.jobId !== jobId));
}

export function useLibraryJobs(options: UseLibraryJobsOptions): UseLibraryJobsResult {
  const [jobs, setJobs] = useState<PendingJob[]>([]);
  const sourcesRef = useRef<Map<string, EventSource>>(new Map());
  const dissectMetaRef = useRef<Map<string, boolean>>(new Map());
  const optionsRef = useRef(options);
  useEffect(() => {
    optionsRef.current = options;
  }, [options]);

  const openStream = useCallback((kind: JobKind, jobId: string, mirror: boolean, isReconnect: boolean) => {
    setJobs((prev) => {
      if (prev.some((job) => job.jobId === jobId)) return prev;
      return [
        ...prev,
        { jobId, kind, messages: [], status: "running", resultBlockId: null, errorMessage: null },
      ];
    });
    if (mirror) addStoredJob(jobId, kind);

    const source = new EventSource(streamUrl(jobId));
    sourcesRef.current.set(jobId, source);
    let receivedFrame = false;

    source.onmessage = (event) => {
      receivedFrame = true;
      try {
        const data = JSON.parse(event.data) as { message?: string | null };
        if (!data.message) return;
        setJobs((prev) =>
          prev.map((job) =>
            job.jobId === jobId
              ? { ...job, messages: [...job.messages, data.message as string].slice(-MAX_MESSAGES) }
              : job
          )
        );
      } catch {
        // malformed frame — ignore, the terminal complete frame is what actually matters
      }
    };

    source.addEventListener("complete", ((event: MessageEvent) => {
      receivedFrame = true;
      source.close();
      sourcesRef.current.delete(jobId);

      let outcome: CompleteOutcome = { status: "error" };
      try {
        outcome = JSON.parse(event.data) as CompleteOutcome;
      } catch {
        // fall through to the error status set above
      }

      if (kind === "dissect") {
        // dissect has no grid tile waiting on a result — resolve and drop the entry immediately
        // instead of going through "resolving", per data-model.md.
        removeStoredJob(jobId);
        setJobs((prev) => prev.filter((job) => job.jobId !== jobId));
        const preserveRequested = dissectMetaRef.current.get(jobId) ?? false;
        dissectMetaRef.current.delete(jobId);
        if (outcome.status === "done") {
          optionsRef.current.onDissectComplete?.(
            jobId,
            {
              saved: outcome.saved ?? [],
              skipped_duplicates: outcome.skipped_duplicates ?? [],
              variants: outcome.variants ?? [],
            },
            preserveRequested
          );
          optionsRef.current.onRefetchNeeded();
        } else {
          optionsRef.current.onDissectError?.(jobId, outcome.error ?? "The import failed.");
        }
        return;
      }

      if (outcome.status === "done" && outcome.duplicate) {
        removeStoredJob(jobId);
        setJobs((prev) => prev.filter((job) => job.jobId !== jobId));
        optionsRef.current.onDuplicate?.(kind, outcome.duplicate_of ?? null);
        return;
      }

      if (outcome.status === "done") {
        setJobs((prev) =>
          prev.map((job) =>
            job.jobId === jobId
              ? { ...job, status: "resolving", resultBlockId: outcome.block_id ?? null }
              : job
          )
        );
        optionsRef.current.onRefetchNeeded();
        return;
      }

      setJobs((prev) =>
        prev.map((job) =>
          job.jobId === jobId
            ? { ...job, status: "error", errorMessage: outcome.error ?? "The operation failed." }
            : job
        )
      );
    }) as EventListener);

    source.onerror = () => {
      if (receivedFrame) return;
      source.close();
      sourcesRef.current.delete(jobId);
      if (kind === "dissect") {
        removeStoredJob(jobId);
        dissectMetaRef.current.delete(jobId);
        setJobs((prev) => prev.filter((job) => job.jobId !== jobId));
        optionsRef.current.onDissectError?.(jobId, "Lost connection to the import.");
        return;
      }
      if (isReconnect) {
        removeStoredJob(jobId);
        setJobs((prev) => prev.filter((job) => job.jobId !== jobId));
        optionsRef.current.onRefetchNeeded();
      } else {
        setJobs((prev) =>
          prev.map((job) =>
            job.jobId === jobId
              ? { ...job, status: "error", errorMessage: "Lost connection to the job." }
              : job
          )
        );
      }
    };
  }, []);

  const start = useCallback(
    (kind: JobKind, jobId: string, meta?: StartJobMeta) => {
      if (kind === "dissect") dissectMetaRef.current.set(jobId, meta?.preserve ?? false);
      openStream(kind, jobId, true, false);
    },
    [openStream]
  );

  const reconnect = useCallback(
    (kind: JobKind, jobId: string) => openStream(kind, jobId, false, true),
    [openStream]
  );

  const confirmResolved = useCallback((jobId: string) => {
    removeStoredJob(jobId);
    setJobs((prev) => prev.filter((job) => job.jobId !== jobId));
  }, []);

  const dismiss = useCallback((jobId: string) => {
    sourcesRef.current.get(jobId)?.close();
    sourcesRef.current.delete(jobId);
    removeStoredJob(jobId);
    setJobs((prev) => prev.filter((job) => job.jobId !== jobId));
  }, []);

  return { jobs, start, reconnect, confirmResolved, dismiss };
}
