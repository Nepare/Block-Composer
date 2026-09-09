import { act, renderHook } from "@testing-library/react";
import { useResultsHistory } from "@/features/compose/useResultsHistory";
import type { ResultDetail } from "@/features/compose/api";
import * as api from "@/features/compose/api";

vi.mock("@/features/compose/api", async () => {
  const actual = await vi.importActual<typeof import("@/features/compose/api")>("@/features/compose/api");
  return {
    ...actual,
    listResults: vi.fn(),
    getResult: vi.fn(),
    renameResult: vi.fn(),
    preserveResult: vi.fn(),
    unpreserveResult: vi.fn(),
    deleteResult: vi.fn(),
    clearResults: vi.fn(),
  };
});

function detail(id: string, name = "Composition"): ResultDetail {
  return { id, name, request: "req", created_at: null, preserved: false, content: "content", slots: [] };
}

beforeEach(() => {
  vi.mocked(api.listResults).mockResolvedValue([]);
});

afterEach(() => {
  vi.clearAllMocks();
});

test("getResult fetches once and returns the cached detail on every subsequent call, with zero additional network calls", async () => {
  vi.mocked(api.getResult).mockResolvedValue(detail("r1"));
  const { result } = renderHook(() => useResultsHistory());

  const first = await act(() => result.current.getResult("r1"));
  const second = await act(() => result.current.getResult("r1"));
  const third = await act(() => result.current.getResult("r1"));

  expect(first).toEqual(detail("r1"));
  expect(second).toBe(first);
  expect(third).toBe(first);
  expect(api.getResult).toHaveBeenCalledTimes(1);
});

test("fetches independently per id, caching each separately", async () => {
  vi.mocked(api.getResult).mockImplementation(async (id: string) => detail(id, `Composition ${id}`));
  const { result } = renderHook(() => useResultsHistory());

  await act(() => result.current.getResult("r1"));
  await act(() => result.current.getResult("r2"));
  await act(() => result.current.getResult("r1"));

  expect(api.getResult).toHaveBeenCalledTimes(2);
  expect(api.getResult).toHaveBeenCalledWith("r1");
  expect(api.getResult).toHaveBeenCalledWith("r2");
});

test("a rename patches the cached entry in place without any additional fetch", async () => {
  vi.mocked(api.getResult).mockResolvedValue(detail("r1", "Old Name"));
  vi.mocked(api.renameResult).mockResolvedValue({ ok: true } as Response);
  const { result } = renderHook(() => useResultsHistory());

  await act(() => result.current.getResult("r1"));
  await act(() => result.current.renameResult("r1", "New Name"));
  const afterRename = await act(() => result.current.getResult("r1"));

  expect(afterRename.name).toBe("New Name");
  expect(api.getResult).toHaveBeenCalledTimes(1);
});

test("deleting an id evicts it from the cache, so a later getResult call re-fetches", async () => {
  vi.mocked(api.getResult).mockResolvedValue(detail("r1"));
  vi.mocked(api.deleteResult).mockResolvedValue({ ok: true } as Response);
  const { result } = renderHook(() => useResultsHistory());

  await act(() => result.current.getResult("r1"));
  expect(api.getResult).toHaveBeenCalledTimes(1);

  await act(() => result.current.deleteResult("r1"));
  await act(() => result.current.getResult("r1"));

  expect(api.getResult).toHaveBeenCalledTimes(2);
});

test("clearHistory evicts any cached id no longer present in the refreshed summaries", async () => {
  vi.mocked(api.getResult).mockResolvedValue(detail("r1"));
  vi.mocked(api.clearResults).mockResolvedValue({
    ok: true,
    json: async () => ({ deleted: 1, skipped_preserved: 0 }),
  } as Response);
  const { result } = renderHook(() => useResultsHistory());

  await act(() => result.current.getResult("r1"));
  expect(api.getResult).toHaveBeenCalledTimes(1);

  // r1 was unpreserved and swept away by the clear — the refreshed list no longer has it.
  vi.mocked(api.listResults).mockResolvedValue([]);
  await act(async () => {
    await result.current.clearHistory();
  });
  await act(() => result.current.getResult("r1"));

  expect(api.getResult).toHaveBeenCalledTimes(2);
});

test("clearHistory keeps a cached entry that is still present in the refreshed summaries", async () => {
  const kept = { id: "r2", name: "Kept", request: "req", created_at: null, preserved: true };
  vi.mocked(api.getResult).mockResolvedValue(detail("r2"));
  vi.mocked(api.clearResults).mockResolvedValue({
    ok: true,
    json: async () => ({ deleted: 1, skipped_preserved: 1 }),
  } as Response);
  const { result } = renderHook(() => useResultsHistory());

  await act(() => result.current.getResult("r2"));
  expect(api.getResult).toHaveBeenCalledTimes(1);

  vi.mocked(api.listResults).mockResolvedValue([kept]);
  await act(async () => {
    await result.current.clearHistory();
  });
  await act(() => result.current.getResult("r2"));

  expect(api.getResult).toHaveBeenCalledTimes(1);
});
