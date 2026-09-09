import { act, renderHook } from "@testing-library/react";
import { useBlockCatalog } from "@/shared/blocks/useBlockCatalog";
import * as api from "@/features/library/api";

vi.mock("@/features/library/api", async () => {
  const actual = await vi.importActual<typeof import("@/features/library/api")>("@/features/library/api");
  return { ...actual, listBlocks: vi.fn(), getBlock: vi.fn() };
});

function summary(id: string, name: string) {
  return { id, name, tags: [], schema: null, source: "manual", created_at: null, preserved: false };
}

function detail(id: string, name: string, body = "") {
  return { ...summary(id, name), body, created_by: "manual", generation_criteria: null, mutated_from: null };
}

beforeEach(() => {
  localStorage.clear();
});

afterEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
});

test("refetch fetches summaries via listBlocks then hydrates each via getBlock", async () => {
  vi.mocked(api.listBlocks).mockResolvedValue([summary("b1", "Backend Engineer"), summary("b2", "Frontend Developer")]);
  vi.mocked(api.getBlock).mockImplementation(async (id: string) =>
    id === "b1"
      ? detail("b1", "Backend Engineer", "**Environment:** Python")
      : detail("b2", "Frontend Developer", "**Environment:** React")
  );

  const { result } = renderHook(() => useBlockCatalog({ storageKey: "test.catalogView" }));
  await act(async () => {
    await result.current.refetch();
  });

  expect(api.listBlocks).toHaveBeenCalledTimes(1);
  expect(api.getBlock).toHaveBeenCalledWith("b1");
  expect(api.getBlock).toHaveBeenCalledWith("b2");
  expect(result.current.blocks.map((b) => b.name).sort()).toEqual(["Backend Engineer", "Frontend Developer"]);
  expect(result.current.blocks.find((b) => b.id === "b1")?.environment).toEqual(["Python"]);
});

test("filters visibleBlocks client-side by search text against name and environment", async () => {
  vi.mocked(api.listBlocks).mockResolvedValue([summary("b1", "Backend Engineer"), summary("b2", "Frontend Developer")]);
  vi.mocked(api.getBlock).mockImplementation(async (id: string) =>
    id === "b1"
      ? detail("b1", "Backend Engineer", "**Environment:** Python")
      : detail("b2", "Frontend Developer", "**Environment:** React")
  );

  const { result } = renderHook(() => useBlockCatalog({ storageKey: "test.catalogView" }));
  await act(async () => {
    await result.current.refetch();
  });

  act(() => result.current.setSearch("Frontend"));
  expect(result.current.visibleBlocks.map((b) => b.name)).toEqual(["Frontend Developer"]);

  act(() => result.current.setSearch("Python"));
  expect(result.current.visibleBlocks.map((b) => b.name)).toEqual(["Backend Engineer"]);

  act(() => result.current.setSearch(""));
  expect(result.current.visibleBlocks).toHaveLength(2);
});

test("persists the chosen view mode under the caller-supplied localStorage key and restores it on remount", () => {
  const { result, unmount } = renderHook(() => useBlockCatalog({ storageKey: "test.customViewKey" }));
  expect(result.current.viewMode).toBe("grid-2");

  act(() => result.current.setViewMode("list"));
  expect(localStorage.getItem("test.customViewKey")).toBe("list");
  unmount();

  const { result: result2 } = renderHook(() => useBlockCatalog({ storageKey: "test.customViewKey" }));
  expect(result2.current.viewMode).toBe("list");
});

test("two callers with different storage keys persist their view mode independently", () => {
  const { result: a } = renderHook(() => useBlockCatalog({ storageKey: "test.keyA" }));
  const { result: b } = renderHook(() => useBlockCatalog({ storageKey: "test.keyB" }));

  act(() => a.current.setViewMode("grid-3"));
  act(() => b.current.setViewMode("list"));

  expect(localStorage.getItem("test.keyA")).toBe("grid-3");
  expect(localStorage.getItem("test.keyB")).toBe("list");
});
