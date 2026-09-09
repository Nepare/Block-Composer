import { act, renderHook } from "@testing-library/react";
import { useComposeJob } from "@/features/compose/useComposeJob";
import * as session from "@/shared/session";
import * as api from "@/features/compose/api";

vi.mock("@/features/compose/api", async () => {
  const actual = await vi.importActual<typeof import("@/features/compose/api")>("@/features/compose/api");
  return { ...actual, cancelJob: vi.fn() };
});

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
  vi.mocked(api.cancelJob).mockResolvedValue({ ok: true } as Response);
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.clearAllMocks();
  session.clear();
  localStorage.clear();
});

test("start opens a stream and mirrors {jobId} into localStorage", () => {
  const { result } = renderHook(() => useComposeJob());

  act(() => result.current.start("job-1"));

  expect(FakeEventSource.instances).toHaveLength(1);
  expect(FakeEventSource.instances[0].url).toContain("job-1");
  expect(result.current.jobId).toBe("job-1");
  expect(result.current.status).toBe("running");
  expect(JSON.parse(localStorage.getItem("cvdocs.pendingComposeJob") ?? "null")).toEqual({ jobId: "job-1" });
});

test("a kind=plan frame populates planSteps, each starting at liveStatus pending", () => {
  const { result } = renderHook(() => useComposeJob());
  act(() => result.current.start("job-1"));
  const source = FakeEventSource.instances[0];

  act(() =>
    source.emitMessage({
      kind: "plan",
      data: {
        steps: [
          { order: 1, action: "use", block_id: "b1", criteria: null },
          { order: 2, action: "generate", block_id: null, criteria: "senior backend" },
        ],
      },
    })
  );

  expect(result.current.planSteps).toEqual([
    { order: 1, action: "use", blockId: "b1", criteria: null, liveStatus: "pending" },
    { order: 2, action: "generate", blockId: null, criteria: "senior backend", liveStatus: "pending" },
  ]);
});

test("slot-scoped frames update the matching plan step's liveStatus by step === order, never by block_id", () => {
  const { result } = renderHook(() => useComposeJob());
  act(() => result.current.start("job-1"));
  const source = FakeEventSource.instances[0];

  act(() =>
    source.emitMessage({
      kind: "plan",
      data: {
        steps: [
          { order: 1, action: "use", block_id: "b1", criteria: null },
          { order: 2, action: "generate", block_id: null, criteria: "senior backend" },
        ],
      },
    })
  );

  // generate_start carries no block_id at all — join must happen via step === order.
  act(() => source.emitMessage({ kind: "generate_start", step: 2, total: 2 }));
  expect(result.current.planSteps[1].liveStatus).toBe("running");
  expect(result.current.planSteps[0].liveStatus).toBe("pending");

  act(() => source.emitMessage({ kind: "use", step: 1, total: 2 }));
  expect(result.current.planSteps[0].liveStatus).toBe("done");

  act(() => source.emitMessage({ kind: "generate_done", step: 2, total: 2 }));
  expect(result.current.planSteps[1].liveStatus).toBe("done");
});

test("a trailing finalize plan step starts pending and is driven by finalize_start/finalize_done", () => {
  const { result } = renderHook(() => useComposeJob());
  act(() => result.current.start("job-1"));
  const source = FakeEventSource.instances[0];

  act(() =>
    source.emitMessage({
      kind: "plan",
      data: {
        steps: [
          { order: 1, action: "use", block_id: "b1", criteria: null },
          { order: 2, action: "finalize", block_id: null, criteria: null },
        ],
      },
    })
  );

  expect(result.current.planSteps).toEqual([
    { order: 1, action: "use", blockId: "b1", criteria: null, liveStatus: "pending" },
    { order: 2, action: "finalize", blockId: null, criteria: null, liveStatus: "pending" },
  ]);

  act(() => source.emitMessage({ kind: "finalize_start", step: 2, total: 2 }));
  expect(result.current.planSteps[1].liveStatus).toBe("running");

  act(() => source.emitMessage({ kind: "finalize_done", step: 2, total: 2 }));
  expect(result.current.planSteps[1].liveStatus).toBe("done");
});

test("any frame carrying step/total updates progress", () => {
  const { result } = renderHook(() => useComposeJob());
  act(() => result.current.start("job-1"));
  const source = FakeEventSource.instances[0];

  act(() => source.emitMessage({ kind: "mutate_start", step: 1, total: 3 }));
  expect(result.current.progress).toEqual({ step: 1, total: 3 });

  act(() => source.emitMessage({ kind: "mutate_done", step: 1, total: 3 }));
  expect(result.current.progress).toEqual({ step: 1, total: 3 });
});

test("a complete frame with status done populates resultId/name/content/slots and removes the localStorage entry", () => {
  const { result } = renderHook(() => useComposeJob());
  act(() => result.current.start("job-1"));
  const source = FakeEventSource.instances[0];

  const slots = [{ order: 1, action: "use", block_id: "b1", criteria: null, resolved_id: "b1" }];
  act(() =>
    source.emitComplete({
      status: "done",
      result_id: "r1",
      name: "My Composition",
      content: "# My Composition\n...",
      cancelled: false,
      slots,
    })
  );

  expect(result.current.status).toBe("done");
  expect(result.current.resultId).toBe("r1");
  expect(result.current.name).toBe("My Composition");
  expect(result.current.content).toBe("# My Composition\n...");
  expect(result.current.slots).toEqual(slots);
  expect(source.closed).toBe(true);
  expect(localStorage.getItem("cvdocs.pendingComposeJob")).toBeNull();
});

test("a complete frame with status cancelled sets status to cancelled with resultId left null and removes the localStorage entry", () => {
  const { result } = renderHook(() => useComposeJob());
  act(() => result.current.start("job-1"));
  const source = FakeEventSource.instances[0];

  act(() => source.emitComplete({ status: "cancelled", cancelled: true, result_id: null }));

  expect(result.current.status).toBe("cancelled");
  expect(result.current.resultId).toBeNull();
  expect(source.closed).toBe(true);
  expect(localStorage.getItem("cvdocs.pendingComposeJob")).toBeNull();
});

test("cancel() calls POST /cancel/{job_id} for the active job", () => {
  const { result } = renderHook(() => useComposeJob());
  act(() => result.current.start("job-1"));

  act(() => result.current.cancel());

  expect(api.cancelJob).toHaveBeenCalledWith("job-1");
});

test("reconnect opens a stream without writing a fresh localStorage entry", () => {
  localStorage.setItem("cvdocs.pendingComposeJob", JSON.stringify({ jobId: "job-1" }));
  const { result } = renderHook(() => useComposeJob());

  act(() => result.current.reconnect("job-1"));

  expect(FakeEventSource.instances).toHaveLength(1);
  expect(FakeEventSource.instances[0].url).toContain("job-1");
  expect(result.current.jobId).toBe("job-1");
  expect(result.current.status).toBe("running");
  // the entry pre-dates the reconnect call — reconnect must not have rewritten it
  expect(localStorage.getItem("cvdocs.pendingComposeJob")).toBe(JSON.stringify({ jobId: "job-1" }));
});

test("reconnect resumes tracking from wherever the buffered SSE queue picks up", () => {
  const { result } = renderHook(() => useComposeJob());
  act(() => result.current.reconnect("job-1"));
  const source = FakeEventSource.instances[0];

  act(() =>
    source.emitMessage({
      kind: "plan",
      data: { steps: [{ order: 1, action: "generate", block_id: null, criteria: "senior backend" }] },
    })
  );
  expect(result.current.planSteps).toEqual([
    { order: 1, action: "generate", blockId: null, criteria: "senior backend", liveStatus: "pending" },
  ]);

  act(() => source.emitMessage({ kind: "generate_start", step: 1, total: 1 }));
  expect(result.current.planSteps[0].liveStatus).toBe("running");
});

test("a reconnect that 404s drops the stale localStorage entry and resets to idle", () => {
  localStorage.setItem("cvdocs.pendingComposeJob", JSON.stringify({ jobId: "stale-job" }));
  const { result } = renderHook(() => useComposeJob());

  act(() => result.current.reconnect("stale-job"));
  const source = FakeEventSource.instances[0];
  act(() => source.emitError());

  expect(result.current.status).toBe("idle");
  expect(result.current.jobId).toBeNull();
  expect(localStorage.getItem("cvdocs.pendingComposeJob")).toBeNull();
});
