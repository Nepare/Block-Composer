import { act, renderHook } from "@testing-library/react";
import { useLibraryJobs } from "@/features/library/useLibraryJobs";
import * as session from "@/shared/session";

class FakeEventSource {
  static instances: FakeEventSource[] = [];
  url: string;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;
  private listeners: Record<string, ((event: MessageEvent) => void)[]> = {};
  closed = false;

  constructor(url: string) {
    this.url = url;
    FakeEventSource.instances.push(this);
  }

  addEventListener(type: string, handler: (event: MessageEvent) => void) {
    (this.listeners[type] ??= []).push(handler);
  }

  close() {
    this.closed = true;
  }

  emitMessage(data: unknown) {
    this.onmessage?.({ data: JSON.stringify(data) } as MessageEvent);
  }

  emitComplete(data: unknown) {
    const event = { data: JSON.stringify(data) } as MessageEvent;
    this.listeners["complete"]?.forEach((handler) => handler(event));
  }

  emitError() {
    this.onerror?.(new Event("error"));
  }
}

beforeEach(() => {
  session.set("test-key");
  localStorage.clear();
  FakeEventSource.instances = [];
  vi.stubGlobal("EventSource", FakeEventSource);
});

afterEach(() => {
  vi.unstubAllGlobals();
  session.clear();
  localStorage.clear();
});

test("start opens a stream and mirrors {jobId, kind} into localStorage", () => {
  const { result } = renderHook(() => useLibraryJobs({ onRefetchNeeded: vi.fn() }));

  act(() => result.current.start("generate", "job-1"));

  expect(FakeEventSource.instances).toHaveLength(1);
  expect(FakeEventSource.instances[0].url).toContain("job-1");
  expect(result.current.jobs).toEqual([
    { jobId: "job-1", kind: "generate", messages: [], status: "running", resultBlockId: null, errorMessage: null },
  ]);
  const stored = JSON.parse(localStorage.getItem("cvdocs.pendingJobs") ?? "[]");
  expect(stored).toEqual([{ jobId: "job-1", kind: "generate" }]);
});

test("an SSE data frame updates a rolling max-3-message queue, dropping the oldest", () => {
  const { result } = renderHook(() => useLibraryJobs({ onRefetchNeeded: vi.fn() }));
  act(() => result.current.start("generate", "job-1"));
  const source = FakeEventSource.instances[0];

  act(() => source.emitMessage({ message: "step 1" }));
  act(() => source.emitMessage({ message: "step 2" }));
  act(() => source.emitMessage({ message: "step 3" }));
  expect(result.current.jobs[0].messages).toEqual(["step 1", "step 2", "step 3"]);

  act(() => source.emitMessage({ message: "step 4" }));
  expect(result.current.jobs[0].messages).toEqual(["step 2", "step 3", "step 4"]);
});

test("a complete frame with status done and no duplicate fires the refetch callback and only removes the job once confirmed", () => {
  const onRefetchNeeded = vi.fn();
  const { result } = renderHook(() => useLibraryJobs({ onRefetchNeeded }));
  act(() => result.current.start("generate", "job-1"));
  const source = FakeEventSource.instances[0];

  act(() => source.emitComplete({ status: "done", block_id: "b1", duplicate: false, duplicate_of: null }));

  expect(onRefetchNeeded).toHaveBeenCalledTimes(1);
  expect(result.current.jobs).toEqual([
    { jobId: "job-1", kind: "generate", messages: [], status: "resolving", resultBlockId: "b1", errorMessage: null },
  ]);
  expect(JSON.parse(localStorage.getItem("cvdocs.pendingJobs") ?? "[]")).toEqual([
    { jobId: "job-1", kind: "generate" },
  ]);
  expect(source.closed).toBe(true);

  act(() => result.current.confirmResolved("job-1"));

  expect(result.current.jobs).toEqual([]);
  expect(JSON.parse(localStorage.getItem("cvdocs.pendingJobs") ?? "[]")).toEqual([]);
});

test("duplicate: true fires the duplicate callback with no refetch call and drops the job immediately", () => {
  const onRefetchNeeded = vi.fn();
  const onDuplicate = vi.fn();
  const { result } = renderHook(() => useLibraryJobs({ onRefetchNeeded, onDuplicate }));
  act(() => result.current.start("generate", "job-1"));
  const source = FakeEventSource.instances[0];

  act(() =>
    source.emitComplete({ status: "done", block_id: null, duplicate: true, duplicate_of: "existing-stem" })
  );

  expect(onDuplicate).toHaveBeenCalledWith("generate", "existing-stem");
  expect(onRefetchNeeded).not.toHaveBeenCalled();
  expect(result.current.jobs).toEqual([]);
  expect(JSON.parse(localStorage.getItem("cvdocs.pendingJobs") ?? "[]")).toEqual([]);
});

test("status: error keeps the job present with errorMessage until dismiss is called", () => {
  const { result } = renderHook(() => useLibraryJobs({ onRefetchNeeded: vi.fn() }));
  act(() => result.current.start("generate", "job-1"));
  const source = FakeEventSource.instances[0];

  act(() => source.emitComplete({ status: "error", error: "something broke" }));

  expect(result.current.jobs).toEqual([
    { jobId: "job-1", kind: "generate", messages: [], status: "error", resultBlockId: null, errorMessage: "something broke" },
  ]);
  expect(JSON.parse(localStorage.getItem("cvdocs.pendingJobs") ?? "[]")).toEqual([
    { jobId: "job-1", kind: "generate" },
  ]);

  act(() => result.current.dismiss("job-1"));

  expect(result.current.jobs).toEqual([]);
  expect(JSON.parse(localStorage.getItem("cvdocs.pendingJobs") ?? "[]")).toEqual([]);
});

test("reconnect that errors before any frame drops the stale entry and fires one opportunistic refetch", () => {
  const onRefetchNeeded = vi.fn();
  localStorage.setItem("cvdocs.pendingJobs", JSON.stringify([{ jobId: "stale-job", kind: "generate" }]));
  const { result } = renderHook(() => useLibraryJobs({ onRefetchNeeded }));

  act(() => result.current.reconnect("generate", "stale-job"));
  const source = FakeEventSource.instances[0];
  act(() => source.emitError());

  expect(onRefetchNeeded).toHaveBeenCalledTimes(1);
  expect(result.current.jobs).toEqual([]);
  expect(JSON.parse(localStorage.getItem("cvdocs.pendingJobs") ?? "[]")).toEqual([]);
});
