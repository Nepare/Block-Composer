import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { SpecificationsPanel } from "@/features/compose/SpecificationsPanel";
import type { UseComposeJobResult } from "@/features/compose/useComposeJob";
import * as api from "@/features/compose/api";

vi.mock("@/features/compose/api", async () => {
  const actual = await vi.importActual<typeof import("@/features/compose/api")>("@/features/compose/api");
  return { ...actual, startCompose: vi.fn() };
});

function fakeComposeJob(overrides: Partial<UseComposeJobResult> = {}): UseComposeJobResult {
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

beforeEach(() => {
  vi.mocked(api.startCompose).mockResolvedValue({
    ok: true,
    json: async () => ({ job_id: "job-1" }),
  } as Response);
});

afterEach(() => {
  vi.clearAllMocks();
});

test("Compose is disabled until the description is non-empty", async () => {
  const user = userEvent.setup();
  render(<SpecificationsPanel composeJob={fakeComposeJob()} />);

  const button = screen.getByRole("button", { name: /compose/i });
  expect(button).toBeDisabled();

  await user.type(screen.getByLabelText("Description"), "A backend engineer");
  expect(button).not.toBeDisabled();
});

test("checking 'I don't know' visually disables the slider and omits count from the payload", async () => {
  const user = userEvent.setup();
  const { container } = render(<SpecificationsPanel composeJob={fakeComposeJob()} />);
  // The slider's actual interactive control is a native <input type="range"> nested a few
  // levels deep — jsdom's lack of real layout keeps base-ui's positioned thumb wrapper out of
  // the accessible-role tree, so we assert on the underlying input directly instead of by role.
  const rangeInput = () => container.querySelector('input[type="range"]') as HTMLInputElement;

  await user.type(screen.getByLabelText("Description"), "A backend engineer");
  expect(rangeInput()).not.toBeDisabled();

  await user.click(screen.getByRole("checkbox", { name: /i don't know/i }));
  expect(rangeInput()).toBeDisabled();

  await user.click(screen.getByRole("button", { name: /compose/i }));

  await waitFor(() => expect(api.startCompose).toHaveBeenCalledTimes(1));
  const payload = vi.mocked(api.startCompose).mock.calls[0][0];
  expect(payload).not.toHaveProperty("count");
});

test("restrict-generation/restrict-mutation checkboxes default unchecked and are included in the payload only when checked", async () => {
  const user = userEvent.setup();
  render(<SpecificationsPanel composeJob={fakeComposeJob()} />);

  expect(screen.getByRole("checkbox", { name: /restrict generation/i })).not.toBeChecked();
  expect(screen.getByRole("checkbox", { name: /restrict mutation/i })).not.toBeChecked();

  await user.type(screen.getByLabelText("Description"), "A backend engineer");
  await user.click(screen.getByRole("checkbox", { name: /restrict generation/i }));
  await user.click(screen.getByRole("button", { name: /compose/i }));

  await waitFor(() => expect(api.startCompose).toHaveBeenCalledTimes(1));
  expect(vi.mocked(api.startCompose).mock.calls[0][0]).toMatchObject({ restrict_generate: true });
  expect(vi.mocked(api.startCompose).mock.calls[0][0]).not.toHaveProperty("restrict_mutate");
});

test("submitting calls startCompose then composeJob.start with the returned job id", async () => {
  const user = userEvent.setup();
  const composeJob = fakeComposeJob();
  render(<SpecificationsPanel composeJob={composeJob} />);

  await user.type(screen.getByLabelText("Description"), "A backend engineer");
  await user.click(screen.getByRole("button", { name: /compose/i }));

  await waitFor(() => expect(composeJob.start).toHaveBeenCalledWith("job-1"));
  expect(api.startCompose).toHaveBeenCalledWith(expect.objectContaining({ request: "A backend engineer" }));
});

test("shows a Cancel action instead of Compose while running, calling composeJob.cancel()", async () => {
  const user = userEvent.setup();
  const composeJob = fakeComposeJob({ status: "running" });
  render(<SpecificationsPanel composeJob={composeJob} />);

  expect(screen.queryByRole("button", { name: /^compose$/i })).not.toBeInTheDocument();
  const cancelButton = screen.getByRole("button", { name: /cancel/i });

  await user.click(cancelButton);
  expect(composeJob.cancel).toHaveBeenCalledTimes(1);
});

test("with an active block selection of size N: the picker control reads 'Selected N blocks', 'Clear selection' is present, the slider is capped at and defaults to N, and 'Restrict generation' is hidden; clearing reverts all four", async () => {
  const user = userEvent.setup();
  const onSelectionChange = vi.fn();
  const { container, rerender } = render(
    <SpecificationsPanel composeJob={fakeComposeJob()} selectedBlockIds={["b1", "b2", "b3"]} onSelectionChange={onSelectionChange} />
  );
  const rangeInput = () => container.querySelector('input[type="range"]') as HTMLInputElement;

  expect(screen.getByRole("button", { name: /selected 3 blocks/i })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /clear selection/i })).toBeInTheDocument();
  expect(screen.queryByRole("checkbox", { name: /restrict generation/i })).not.toBeInTheDocument();
  expect(rangeInput()).toHaveAttribute("max", "3");
  expect(rangeInput()).toHaveValue("3");

  await user.click(screen.getByRole("button", { name: /clear selection/i }));
  expect(onSelectionChange).toHaveBeenCalledWith([]);

  rerender(<SpecificationsPanel composeJob={fakeComposeJob()} selectedBlockIds={[]} onSelectionChange={onSelectionChange} />);

  expect(screen.getByRole("button", { name: /^select exact blocks$/i })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /clear selection/i })).not.toBeInTheDocument();
  expect(screen.getByRole("checkbox", { name: /restrict generation/i })).toBeInTheDocument();
  expect(rangeInput()).toHaveAttribute("max", "20");
});

test("submitting with an active block selection includes from_block_ids in the payload", async () => {
  const user = userEvent.setup();
  render(<SpecificationsPanel composeJob={fakeComposeJob()} selectedBlockIds={["b1", "b2"]} onSelectionChange={vi.fn()} />);

  await user.type(screen.getByLabelText("Description"), "A backend engineer");
  await user.click(screen.getByRole("button", { name: /compose/i }));

  await waitFor(() => expect(api.startCompose).toHaveBeenCalledTimes(1));
  expect(vi.mocked(api.startCompose).mock.calls[0][0]).toMatchObject({ from_block_ids: ["b1", "b2"] });
});
