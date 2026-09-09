import { useState } from "react";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { toast } from "sonner";
import { HistorySidebar } from "@/features/compose/HistorySidebar";
import type { ClearResultsResult, ResultSummary } from "@/features/compose/api";
import type { DisplayMode } from "@/features/compose/types";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

const DELETE_WARNING_KEY = "cvdocs.skipComposeDeleteWarning";

function summary(overrides: Partial<ResultSummary> = {}): ResultSummary {
  return {
    id: "r1",
    name: "My Composition",
    request: "Build something",
    created_at: "2026-01-01T00:00:00Z",
    preserved: false,
    ...overrides,
  };
}

// Stateful wrapper mirroring how ComposePane wires useResultsHistory's methods into
// HistorySidebar — lets tests assert both the API calls and the resulting UI state.
function Harness({
  initialSummaries,
  isComposeRunning = false,
  isPending = false,
  displayMode = { type: "fresh" },
  onSelect = vi.fn(),
  onNewComposition = vi.fn(),
  onBackToLive = vi.fn(),
  renameImpl,
  preserveImpl,
  unpreserveImpl,
  deleteImpl,
  clearImpl,
}: {
  initialSummaries: ResultSummary[];
  isComposeRunning?: boolean;
  isPending?: boolean;
  displayMode?: DisplayMode;
  onSelect?: (id: string) => void;
  onNewComposition?: () => void;
  onBackToLive?: () => void;
  renameImpl?: (id: string, name: string) => Promise<boolean>;
  preserveImpl?: (id: string) => Promise<boolean>;
  unpreserveImpl?: (id: string) => Promise<boolean>;
  deleteImpl?: (id: string) => Promise<boolean>;
  clearImpl?: () => Promise<ClearResultsResult | null>;
}) {
  const [summaries, setSummaries] = useState(initialSummaries);

  async function onRename(id: string, name: string) {
    const ok = renameImpl ? await renameImpl(id, name) : true;
    if (ok) setSummaries((prev) => prev.map((s) => (s.id === id ? { ...s, name } : s)));
    return ok;
  }
  async function onPreserve(id: string) {
    const ok = preserveImpl ? await preserveImpl(id) : true;
    if (ok) setSummaries((prev) => prev.map((s) => (s.id === id ? { ...s, preserved: true } : s)));
    return ok;
  }
  async function onUnpreserve(id: string) {
    const ok = unpreserveImpl ? await unpreserveImpl(id) : true;
    if (ok) setSummaries((prev) => prev.map((s) => (s.id === id ? { ...s, preserved: false } : s)));
    return ok;
  }
  async function onDelete(id: string) {
    const ok = deleteImpl ? await deleteImpl(id) : true;
    if (ok) setSummaries((prev) => prev.filter((s) => s.id !== id));
    return ok;
  }
  async function onClearHistory() {
    const result = clearImpl ? await clearImpl() : ({ deleted: 0, skipped_preserved: 0 } as ClearResultsResult);
    if (result) setSummaries((prev) => prev.filter((s) => s.preserved));
    return result;
  }

  return (
    <HistorySidebar
      summaries={summaries}
      loading={false}
      displayMode={displayMode}
      onSelect={onSelect}
      isComposeRunning={isComposeRunning}
      isPending={isPending}
      onNewComposition={onNewComposition}
      onBackToLive={onBackToLive}
      onRename={onRename}
      onPreserve={onPreserve}
      onUnpreserve={onUnpreserve}
      onDelete={onDelete}
      onClearHistory={onClearHistory}
    />
  );
}

afterEach(() => {
  localStorage.clear();
  vi.clearAllMocks();
});

test("double-clicking an entry's name enters inline edit mode and commits a rename that persists", async () => {
  const user = userEvent.setup();
  const renameImpl = vi.fn().mockResolvedValue(true);
  render(<Harness initialSummaries={[summary()]} renameImpl={renameImpl} />);

  await user.dblClick(screen.getByText("My Composition"));
  const input = screen.getByDisplayValue("My Composition");
  await user.clear(input);
  await user.type(input, "Renamed Composition{Enter}");

  expect(renameImpl).toHaveBeenCalledWith("r1", "Renamed Composition");
  expect(await screen.findByText("Renamed Composition")).toBeInTheDocument();
  expect(screen.queryByDisplayValue("Renamed Composition")).not.toBeInTheDocument();
});

test("rejects an empty/whitespace rename commit and keeps the previous name", async () => {
  const user = userEvent.setup();
  const renameImpl = vi.fn().mockResolvedValue(true);
  render(<Harness initialSummaries={[summary()]} renameImpl={renameImpl} />);

  await user.dblClick(screen.getByText("My Composition"));
  const input = screen.getByDisplayValue("My Composition");
  await user.clear(input);
  await user.type(input, "   {Enter}");

  expect(renameImpl).not.toHaveBeenCalled();
  expect(await screen.findByText("My Composition")).toBeInTheDocument();
});

test("preserving an entry visibly distinguishes it and disables its own delete control; unpreserving reverses both", async () => {
  const user = userEvent.setup();
  const preserveImpl = vi.fn().mockResolvedValue(true);
  const unpreserveImpl = vi.fn().mockResolvedValue(true);
  render(
    <Harness initialSummaries={[summary()]} preserveImpl={preserveImpl} unpreserveImpl={unpreserveImpl} />
  );

  const entry = screen.getByTestId("history-entry");
  expect(entry).toHaveAttribute("data-preserved", "false");
  expect(within(entry).getByRole("button", { name: "Delete" })).not.toBeDisabled();

  await user.click(within(entry).getByRole("button", { name: "Preserve" }));

  expect(preserveImpl).toHaveBeenCalledWith("r1");
  await waitFor(() => expect(entry).toHaveAttribute("data-preserved", "true"));
  expect(within(entry).getByRole("button", { name: "Delete" })).toBeDisabled();
  expect(within(entry).getByRole("button", { name: "Unpreserve" })).toBeInTheDocument();

  await user.click(within(entry).getByRole("button", { name: "Unpreserve" }));

  expect(unpreserveImpl).toHaveBeenCalledWith("r1");
  await waitFor(() => expect(entry).toHaveAttribute("data-preserved", "false"));
  expect(within(entry).getByRole("button", { name: "Delete" })).not.toBeDisabled();
});

test("deleting an unpreserved entry shows the warning, keyed by the Compose-specific suppression key, and 'don't show again' suppresses it later", async () => {
  const user = userEvent.setup();
  const deleteImpl = vi.fn().mockResolvedValue(true);
  const { unmount } = render(
    <Harness initialSummaries={[summary({ id: "r1", name: "First" }), summary({ id: "r2", name: "Second" })]} deleteImpl={deleteImpl} />
  );

  const firstEntry = screen.getByText("First").closest('[data-testid="history-entry"]') as HTMLElement;
  await user.click(within(firstEntry).getByRole("button", { name: "Delete" }));

  expect(screen.getByRole("heading", { name: "Delete composition" })).toBeInTheDocument();
  await user.click(screen.getByRole("checkbox"));
  await user.click(screen.getByRole("button", { name: /confirm/i }));

  expect(deleteImpl).toHaveBeenCalledWith("r1");
  await waitFor(() => expect(localStorage.getItem(DELETE_WARNING_KEY)).toBe("true"));
  unmount();

  render(<Harness initialSummaries={[summary({ id: "r2", name: "Second" })]} deleteImpl={deleteImpl} />);
  const secondEntry = screen.getByText("Second").closest('[data-testid="history-entry"]') as HTMLElement;
  await user.click(within(secondEntry).getByRole("button", { name: "Delete" }));

  expect(screen.queryByRole("heading", { name: "Delete composition" })).not.toBeInTheDocument();
  expect(deleteImpl).toHaveBeenCalledWith("r2");
});

test("'Clear history' always shows its warning regardless of per-entry suppression, calls clearHistory, and surfaces the counts", async () => {
  localStorage.setItem(DELETE_WARNING_KEY, "true");
  const user = userEvent.setup();
  const clearImpl = vi.fn().mockResolvedValue({ deleted: 2, skipped_preserved: 1 } as ClearResultsResult);
  render(
    <Harness
      initialSummaries={[
        summary({ id: "r1", name: "First" }),
        summary({ id: "r2", name: "Second", preserved: true }),
      ]}
      clearImpl={clearImpl}
    />
  );

  await user.click(screen.getByRole("button", { name: "Clear history" }));

  expect(screen.getByRole("heading", { name: "Clear history" })).toBeInTheDocument();
  expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: /confirm/i }));

  expect(clearImpl).toHaveBeenCalledTimes(1);
  await waitFor(() => expect(screen.queryByText("First")).not.toBeInTheDocument());
  expect(screen.getByText("Second")).toBeInTheDocument();
  expect(toast.success).toHaveBeenCalledWith("Cleared 2 composition(s), kept 1 preserved.");
});

test("isPending renders an inert, active-styled entry above every real entry, with no click handler or controls", async () => {
  const user = userEvent.setup();
  const onSelect = vi.fn();
  render(
    <Harness
      initialSummaries={[summary({ id: "r1", name: "First" }), summary({ id: "r2", name: "Second" })]}
      isPending
      onSelect={onSelect}
    />
  );

  const pendingEntry = screen.getByTestId("history-pending-entry");
  const allEntries = screen.getAllByTestId(/history-(pending-)?entry/);
  expect(allEntries[0]).toBe(pendingEntry);
  expect(allEntries).toHaveLength(3);

  expect(within(pendingEntry).queryAllByRole("button")).toHaveLength(0);
  expect(pendingEntry).toHaveClass("bg-muted", "font-medium");
  expect(pendingEntry.querySelector("svg")).toBeInTheDocument();

  await user.click(pendingEntry);
  expect(onSelect).not.toHaveBeenCalled();
});

test("isPending's dots label cycles through '.', '..', '...' on an interval", async () => {
  vi.useFakeTimers();
  render(<Harness initialSummaries={[]} isPending />);

  const pendingEntry = screen.getByTestId("history-pending-entry");
  expect(pendingEntry).toHaveTextContent(".");
  expect(pendingEntry).not.toHaveTextContent("..");

  await act(async () => {
    await vi.advanceTimersByTimeAsync(400);
  });
  expect(pendingEntry.textContent).toBe("..");

  await act(async () => {
    await vi.advanceTimersByTimeAsync(400);
  });
  expect(pendingEntry.textContent).toBe("...");

  await act(async () => {
    await vi.advanceTimersByTimeAsync(400);
  });
  expect(pendingEntry.textContent).toBe(".");

  vi.useRealTimers();
});
