import { useState } from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { GenerateMutateDialog } from "@/features/library/GenerateMutateDialog";
import * as api from "@/features/library/api";

function ControlledDialog({ onJobStarted }: { onJobStarted: (kind: string, jobId: string) => void }) {
  const [open, setOpen] = useState(true);
  return <GenerateMutateDialog mode="generate" open={open} onOpenChange={setOpen} onJobStarted={onJobStarted} />;
}

function ControlledMutateDialog({ onJobStarted }: { onJobStarted: (kind: string, jobId: string) => void }) {
  const [open, setOpen] = useState(true);
  return (
    <GenerateMutateDialog
      mode="mutate"
      sourceBlock={sourceBlock}
      open={open}
      onOpenChange={setOpen}
      onJobStarted={onJobStarted}
    />
  );
}

vi.mock("@/features/library/api", async () => {
  const actual = await vi.importActual<typeof import("@/features/library/api")>(
    "@/features/library/api"
  );
  return { ...actual, startGenerate: vi.fn(), startMutate: vi.fn(), getBlock: vi.fn() };
});

const sourceBlock = {
  id: "block-1",
  name: "Platform Engineer",
  created_at: null,
  created_by: "manual",
  environment: ["Kubernetes", "AWS"],
  preserved: false,
};

afterEach(() => {
  vi.clearAllMocks();
});

test("submit is blocked while criteria is empty", async () => {
  const onJobStarted = vi.fn();
  const user = userEvent.setup();

  render(
    <GenerateMutateDialog mode="generate" open onOpenChange={vi.fn()} onJobStarted={onJobStarted} />
  );

  const submit = screen.getByRole("button", { name: /generate/i });
  expect(submit).toBeDisabled();

  await user.click(submit);
  expect(api.startGenerate).not.toHaveBeenCalled();
  expect(onJobStarted).not.toHaveBeenCalled();
});

test("name and preserve are optional — submitting with only criteria succeeds", async () => {
  vi.mocked(api.startGenerate).mockResolvedValue({
    ok: true,
    json: async () => ({ job_id: "job-123" }),
  } as Response);
  const onJobStarted = vi.fn();
  const onOpenChange = vi.fn();
  const user = userEvent.setup();

  render(
    <GenerateMutateDialog mode="generate" open onOpenChange={onOpenChange} onJobStarted={onJobStarted} />
  );

  await user.type(screen.getByLabelText(/criteria/i), "A senior backend role");
  await user.click(screen.getByRole("button", { name: /generate/i }));

  await waitFor(() => expect(api.startGenerate).toHaveBeenCalledWith({
    criteria: "A senior backend role",
    name: undefined,
    preserve: false,
  }));
  expect(onJobStarted).toHaveBeenCalledWith("generate", "job-123");
});

test("submitting calls startGenerate and the dialog is gone from the DOM right after, without waiting on job resolution", async () => {
  let resolveStart!: (value: Response) => void;
  vi.mocked(api.startGenerate).mockReturnValue(
    new Promise<Response>((resolve) => {
      resolveStart = resolve;
    })
  );
  const onJobStarted = vi.fn();
  const user = userEvent.setup();

  render(<ControlledDialog onJobStarted={onJobStarted} />);

  await user.type(screen.getByLabelText(/criteria/i), "A platform engineer block");
  await user.type(screen.getByLabelText(/name/i), "Platform Engineer");
  await user.click(screen.getByRole("checkbox", { name: /preserve/i }));
  await user.click(screen.getByRole("button", { name: /generate/i }));

  expect(screen.getByRole("dialog")).toBeInTheDocument();

  resolveStart({ ok: true, json: async () => ({ job_id: "job-456" }) } as Response);

  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  expect(onJobStarted).toHaveBeenCalledWith("generate", "job-456");
  expect(api.startGenerate).toHaveBeenCalledWith({
    criteria: "A platform engineer block",
    name: "Platform Engineer",
    preserve: true,
  });
});

test("mutate mode shows the source block's project and description read-only", async () => {
  vi.mocked(api.getBlock).mockResolvedValue({
    id: "block-1",
    name: "Platform Engineer",
    tags: [],
    schema: null,
    source: "manual",
    created_at: null,
    preserved: false,
    body: "# Platform Engineer\nBuilds scalable platform tooling.\n**Role:** Platform Engineer\n**Environment:** Kubernetes, AWS",
    created_by: "manual",
    generation_criteria: null,
    mutated_from: null,
  });

  render(
    <GenerateMutateDialog
      mode="mutate"
      sourceBlock={sourceBlock}
      open
      onOpenChange={vi.fn()}
      onJobStarted={vi.fn()}
    />
  );

  expect(screen.getByText("Platform Engineer")).toBeInTheDocument();

  await waitFor(() => expect(screen.getByText("Builds scalable platform tooling.")).toBeInTheDocument());
  expect(screen.queryByLabelText(/source block content/i)).not.toBeInTheDocument();
});

test("mutate mode submits with the source block's id and closes immediately without waiting on job resolution", async () => {
  vi.mocked(api.getBlock).mockResolvedValue({
    id: "block-1",
    name: "Platform Engineer",
    tags: [],
    schema: null,
    source: "manual",
    created_at: null,
    preserved: false,
    body: "**Role:** Platform Engineer",
    created_by: "manual",
    generation_criteria: null,
    mutated_from: null,
  });
  let resolveStart!: (value: Response) => void;
  vi.mocked(api.startMutate).mockReturnValue(
    new Promise<Response>((resolve) => {
      resolveStart = resolve;
    })
  );
  const onJobStarted = vi.fn();
  const user = userEvent.setup();

  render(<ControlledMutateDialog onJobStarted={onJobStarted} />);

  await user.type(screen.getByLabelText(/criteria/i), "Make it more senior");
  await user.click(screen.getByRole("button", { name: /mutate/i }));

  expect(screen.getByRole("dialog")).toBeInTheDocument();

  resolveStart({ ok: true, json: async () => ({ job_id: "job-789" }) } as Response);

  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  expect(onJobStarted).toHaveBeenCalledWith("mutate", "job-789");
  expect(api.startMutate).toHaveBeenCalledWith({
    block_id: "block-1",
    criteria: "Make it more senior",
    name: undefined,
    preserve: false,
  });
});
