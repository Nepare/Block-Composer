import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ResultPanel } from "@/features/compose/ResultPanel";
import type { UseComposeJobResult } from "@/features/compose/useComposeJob";

function fakeJob(overrides: Partial<UseComposeJobResult> = {}): UseComposeJobResult {
  return {
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
    start: vi.fn(),
    reconnect: vi.fn(),
    cancel: vi.fn(),
    ...overrides,
  };
}

test("shows a progress bar plus the plan while running", () => {
  const composeJob = fakeJob({
    status: "running",
    progress: { step: 1, total: 2 },
    planSteps: [{ order: 1, action: "generate", blockId: null, criteria: null, liveStatus: "running" }],
  });

  render(<ResultPanel composeJob={composeJob} displayMode={{ type: "fresh" }} />);

  expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "50");
  expect(screen.getAllByTestId("plan-step")).toHaveLength(1);
});

test("shows the finished content once done", () => {
  const composeJob = fakeJob({ status: "done", name: "My Composition", content: "finished content" });

  render(<ResultPanel composeJob={composeJob} displayMode={{ type: "fresh" }} />);

  expect(screen.getByText("My Composition")).toBeInTheDocument();
  expect(screen.getByText("finished content")).toBeInTheDocument();
  expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
});

test("shows an idle/empty prompt when no job is active and displayMode is fresh", () => {
  render(<ResultPanel composeJob={fakeJob()} displayMode={{ type: "fresh" }} />);

  expect(screen.getByTestId("result-panel-idle")).toBeInTheDocument();
  expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
});

test("a Cancel action is visible and usable while running", async () => {
  const user = userEvent.setup();
  const composeJob = fakeJob({ status: "running", progress: { step: 1, total: 2 } });

  render(<ResultPanel composeJob={composeJob} displayMode={{ type: "fresh" }} />);

  const cancelButton = screen.getByRole("button", { name: /cancel/i });
  expect(cancelButton).toBeEnabled();
  await user.click(cancelButton);
  expect(composeJob.cancel).toHaveBeenCalledTimes(1);
});

test("renders the cancelled outcome distinctly, not an empty/blank state", () => {
  render(<ResultPanel composeJob={fakeJob({ status: "cancelled" })} displayMode={{ type: "fresh" }} />);

  const cancelledPanel = screen.getByTestId("result-panel-cancelled");
  expect(cancelledPanel).toBeInTheDocument();
  expect(cancelledPanel).toHaveTextContent(/cancel/i);
  expect(screen.queryByTestId("result-panel-idle")).not.toBeInTheDocument();
});

test("renders a failed outcome distinctly, not an empty/blank state", () => {
  const composeJob = fakeJob({ status: "error", errorMessage: "the model produced no output" });

  render(<ResultPanel composeJob={composeJob} displayMode={{ type: "fresh" }} />);

  const errorPanel = screen.getByTestId("result-panel-error");
  expect(errorPanel).toBeInTheDocument();
  expect(errorPanel).toHaveTextContent("the model produced no output");
  expect(screen.queryByTestId("result-panel-idle")).not.toBeInTheDocument();
});
