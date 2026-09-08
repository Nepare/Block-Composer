import { useState } from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { DissectDialog } from "@/features/library/DissectDialog";
import * as api from "@/features/library/api";

function ControlledDialog({ onJobStarted }: { onJobStarted: (jobId: string, preserveRequested: boolean) => void }) {
  const [open, setOpen] = useState(true);
  return <DissectDialog open={open} onOpenChange={setOpen} onJobStarted={onJobStarted} />;
}

vi.mock("@/features/library/api", async () => {
  const actual = await vi.importActual<typeof import("@/features/library/api")>(
    "@/features/library/api"
  );
  return { ...actual, startDissect: vi.fn() };
});

afterEach(() => {
  vi.clearAllMocks();
  vi.restoreAllMocks();
});

test("offers a Connect Google Account action with no claim about connection state", () => {
  render(<DissectDialog open onOpenChange={vi.fn()} onJobStarted={vi.fn()} />);

  expect(screen.getByRole("button", { name: /connect google account/i })).toBeInTheDocument();
  expect(screen.queryByText(/not connected/i)).not.toBeInTheDocument();
  expect(screen.queryByText(/^connected$/i)).not.toBeInTheDocument();
});

test("clicking Connect Google Account opens the OAuth flow in a new tab", async () => {
  const openSpy = vi.spyOn(window, "open").mockImplementation(() => null);
  const user = userEvent.setup();

  render(<DissectDialog open onOpenChange={vi.fn()} onJobStarted={vi.fn()} />);
  await user.click(screen.getByRole("button", { name: /connect google account/i }));

  expect(openSpy).toHaveBeenCalledTimes(1);
  const [url, target] = openSpy.mock.calls[0];
  expect(String(url)).toContain("/auth/google/login");
  expect(target).toBe("_blank");
});

test("Populate stays disabled for a malformed doc reference and enables for a well-formed one", async () => {
  const user = userEvent.setup();
  render(<DissectDialog open onOpenChange={vi.fn()} onJobStarted={vi.fn()} />);

  const field = screen.getByLabelText(/document link or id/i);
  const submit = screen.getByRole("button", { name: /^populate$/i });
  expect(submit).toBeDisabled();

  await user.type(field, "this is just an ordinary sentence");
  expect(submit).toBeDisabled();

  await user.clear(field);
  await user.type(field, "https://docs.google.com/document/d/abc123XYZ/edit");
  expect(submit).toBeEnabled();

  await user.clear(field);
  await user.type(field, "a-bare-doc-id-1234567890");
  expect(submit).toBeEnabled();
});

test("submitting calls startDissect and reports the job before/regardless of dialog close", async () => {
  let resolveStart!: (value: Response) => void;
  vi.mocked(api.startDissect).mockReturnValue(
    new Promise<Response>((resolve) => {
      resolveStart = resolve;
    })
  );
  const onJobStarted = vi.fn();
  const user = userEvent.setup();

  render(<ControlledDialog onJobStarted={onJobStarted} />);

  await user.type(screen.getByLabelText(/document link or id/i), "https://docs.google.com/document/d/abc123XYZ/edit");
  await user.click(screen.getByRole("button", { name: /^populate$/i }));

  expect(screen.getByRole("dialog")).toBeInTheDocument();
  expect(onJobStarted).not.toHaveBeenCalled();

  resolveStart({ ok: true, json: async () => ({ job_id: "job-dissect-1" }) } as Response);

  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  expect(onJobStarted).toHaveBeenCalledTimes(1);
  expect(onJobStarted).toHaveBeenCalledWith("job-dissect-1", true);
  expect(api.startDissect).toHaveBeenCalledWith({ doc: "https://docs.google.com/document/d/abc123XYZ/edit" });
});

test("unchecking add as preserved is reflected in the job-started callback", async () => {
  vi.mocked(api.startDissect).mockResolvedValue({
    ok: true,
    json: async () => ({ job_id: "job-dissect-2" }),
  } as Response);
  const onJobStarted = vi.fn();
  const user = userEvent.setup();

  render(<ControlledDialog onJobStarted={onJobStarted} />);

  await user.type(screen.getByLabelText(/document link or id/i), "a-bare-doc-id-1234567890");
  await user.click(screen.getByRole("checkbox", { name: /add as preserved/i }));
  await user.click(screen.getByRole("button", { name: /^populate$/i }));

  await waitFor(() => expect(onJobStarted).toHaveBeenCalledWith("job-dissect-2", false));
});
