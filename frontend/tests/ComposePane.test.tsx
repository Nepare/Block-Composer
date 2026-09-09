import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ComposePane } from "@/features/compose/ComposePane";
import type { UseComposeJobResult } from "@/features/compose/useComposeJob";
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
    startCompose: vi.fn(),
  };
});

function fakeComposeJob(overrides: Partial<UseComposeJobResult> = {}): UseComposeJobResult {
  return {
    jobId: "job-1",
    status: "idle",
    planSteps: [],
    progress: null,
    messages: [],
    resultId: null,
    name: null,
    content: null,
    slots: null,
    errorMessage: null,
    start: vi.fn(),
    reconnect: vi.fn(),
    cancel: vi.fn(),
    ...overrides,
  };
}

beforeEach(() => {
  vi.mocked(api.listResults).mockResolvedValue([
    { id: "r1", name: "Past Composition", request: "req", created_at: null, preserved: false },
  ]);
});

afterEach(() => {
  vi.clearAllMocks();
});

test("clicking a history entry while running switches displayMode without disrupting the job; back-to-live restores fresh", async () => {
  const user = userEvent.setup();
  const composeJob = fakeComposeJob({ status: "running", progress: { step: 2, total: 5 } });

  render(<ComposePane composeJob={composeJob} />);

  const entry = await screen.findByText("Past Composition");
  expect(screen.queryByTestId("back-to-live")).not.toBeInTheDocument();
  expect(screen.getByTestId("result-panel-running")).toBeInTheDocument();

  await user.click(entry);

  // Selecting a history entry marks it active and surfaces the back-to-live affordance...
  expect(entry.closest('[data-testid="history-entry"]')).toHaveClass("bg-muted");
  const backToLive = await screen.findByTestId("back-to-live");
  expect(backToLive).toBeInTheDocument();

  // ...while the running job's own state is completely untouched the whole time.
  expect(composeJob.status).toBe("running");
  expect(composeJob.progress).toEqual({ step: 2, total: 5 });

  await user.click(backToLive);

  expect(screen.queryByTestId("back-to-live")).not.toBeInTheDocument();
  expect(entry.closest('[data-testid="history-entry"]')).not.toHaveClass("bg-muted");
  expect(composeJob.status).toBe("running");
  expect(composeJob.progress).toEqual({ step: 2, total: 5 });
});

test("a freshly-mounted ComposePane renders exactly the live progress/plan state composeJob already holds", () => {
  const composeJob = fakeComposeJob({
    status: "running",
    progress: { step: 1, total: 2 },
    planSteps: [
      { order: 1, action: "use", blockId: "b1", criteria: null, liveStatus: "done" },
      { order: 2, action: "generate", blockId: null, criteria: "senior backend", liveStatus: "running" },
    ],
  });

  // Simulates a tab-switch remount: a brand new ComposePane instance receives a composeJob
  // that already carries live state from before the remount — nothing should render as blank.
  render(<ComposePane composeJob={composeJob} />);

  expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "50");
  expect(screen.getAllByTestId("plan-step")).toHaveLength(2);
  expect(screen.getByTestId("result-panel-running")).toBeInTheDocument();
});

test("does not refetch results history for a cancelled outcome, only for done", async () => {
  const { rerender } = render(<ComposePane composeJob={fakeComposeJob({ status: "running" })} />);
  await screen.findByText("Past Composition");
  expect(api.listResults).toHaveBeenCalledTimes(1);

  rerender(<ComposePane composeJob={fakeComposeJob({ status: "cancelled" })} />);
  // give any accidental refetch effect a chance to fire before asserting it didn't
  await new Promise((resolve) => setTimeout(resolve, 0));
  expect(api.listResults).toHaveBeenCalledTimes(1);

  rerender(<ComposePane composeJob={fakeComposeJob({ status: "done" })} />);
  await vi.waitFor(() => expect(api.listResults).toHaveBeenCalledTimes(2));
});

test("selecting a history entry populates SpecificationsPanel's fixed fields and ResultPanel's content from its original inputs/output; Compose is not rendered", async () => {
  vi.mocked(api.getResult).mockResolvedValue({
    id: "r1",
    name: "Past Composition",
    request: "Build a great resume",
    created_at: null,
    preserved: false,
    content: "# Past Composition\nFinished output",
    slots: [{ order: 1, action: "use", block_id: "b1", criteria: null, resolved_id: "b1" }],
  });
  const user = userEvent.setup();

  render(<ComposePane composeJob={fakeComposeJob({ status: "idle" })} />);

  await user.click(await screen.findByText("Past Composition"));

  const historyPanel = await screen.findByTestId("result-panel-history");
  expect(historyPanel).toHaveTextContent("Finished output");

  const description = screen.getByLabelText("Description");
  expect(description).toBeDisabled();
  expect(description).toHaveValue("Build a great resume");
  const name = screen.getByLabelText("Name");
  expect(name).toBeDisabled();
  expect(name).toHaveValue("Past Composition");

  expect(screen.queryByRole("button", { name: /^compose$/i })).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: /new composition/i })).toBeInTheDocument();
});

test("'New Composition' returns from a history view to a fresh, editable Specifications state", async () => {
  vi.mocked(api.getResult).mockResolvedValue({
    id: "r1",
    name: "Past Composition",
    request: "Build a great resume",
    created_at: null,
    preserved: false,
    content: "finished content",
    slots: [],
  });
  const user = userEvent.setup();

  render(<ComposePane composeJob={fakeComposeJob({ status: "idle" })} />);

  await user.click(await screen.findByText("Past Composition"));
  expect(await screen.findByRole("button", { name: /new composition/i })).toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: /new composition/i }));

  // The button lives in the always-visible history sidebar now, so it stays in the
  // document after use — only the Specifications panel's state should have changed.
  expect(screen.getByRole("button", { name: /new composition/i })).toBeInTheDocument();
  const button = screen.getByRole("button", { name: /^compose$/i });
  expect(button).toBeInTheDocument();
  expect(button).toBeDisabled();
  expect(screen.getByLabelText("Description")).not.toBeDisabled();
  expect(screen.getByLabelText("Description")).toHaveValue("");
});

test("'New Composition' clicked from an already-fresh state clears name, description, specifiers, and checkboxes", async () => {
  const user = userEvent.setup();

  render(<ComposePane composeJob={fakeComposeJob({ status: "idle" })} />);

  await user.type(screen.getByLabelText("Name"), "My draft");
  await user.type(screen.getByLabelText("Description"), "Build a great resume");
  await user.type(screen.getByLabelText("Specifiers"), "keep it short");
  await user.click(screen.getByRole("checkbox", { name: /restrict generation/i }));
  await user.click(screen.getByRole("checkbox", { name: /restrict mutation/i }));

  await user.click(screen.getByRole("button", { name: /new composition/i }));

  expect(screen.getByLabelText("Name")).toHaveValue("");
  expect(screen.getByLabelText("Description")).toHaveValue("");
  expect(screen.getByLabelText("Specifiers")).toHaveValue("");
  expect(screen.getByRole("checkbox", { name: /restrict generation/i })).not.toBeChecked();
  expect(screen.getByRole("checkbox", { name: /restrict mutation/i })).not.toBeChecked();
});
