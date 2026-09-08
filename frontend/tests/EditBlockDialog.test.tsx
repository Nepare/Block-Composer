import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { toast } from "sonner";
import { EditBlockDialog } from "@/features/library/EditBlockDialog";
import * as api from "@/features/library/api";

vi.mock("@/features/library/api", async () => {
  const actual = await vi.importActual<typeof import("@/features/library/api")>(
    "@/features/library/api"
  );
  return { ...actual, getBlock: vi.fn(), updateBlock: vi.fn() };
});

vi.mock("sonner", () => ({
  toast: { info: vi.fn(), success: vi.fn(), error: vi.fn() },
}));

const BLOCK_DETAIL = {
  id: "block-1",
  name: "Platform Engineer",
  tags: [],
  schema: null,
  source: "manual",
  created_at: null,
  preserved: false,
  body: [
    "# Platform Engineer",
    "",
    "Runs the internal deployment platform.",
    "",
    "**Role:** Platform Lead",
    "",
    "**Period:** 2022-2024",
    "",
    "**Environment:** Kubernetes, AWS",
  ].join("\n"),
  created_by: "manual",
  generation_criteria: null,
  mutated_from: null,
};

const WHOLE_BLOCK_TEXT = [
  "# Backend Engineer",
  "",
  "Owns the payments service.",
  "",
  "**Role:** Backend Lead",
  "",
  "**Period:** 2019-2021",
  "",
  "**Environment:** Go, Postgres",
].join("\n");

beforeEach(() => {
  vi.mocked(api.getBlock).mockResolvedValue(BLOCK_DETAIL as api.BlockDetail);
  if (!("clipboard" in navigator)) {
    Object.assign(navigator, { clipboard: {} });
  }
  Object.assign(navigator.clipboard, { writeText: vi.fn().mockResolvedValue(undefined) });
});

afterEach(() => {
  vi.clearAllMocks();
});

test("opens pre-filled with the block's parsed fields", async () => {
  render(<EditBlockDialog blockId="block-1" open onOpenChange={vi.fn()} />);

  expect(await screen.findByDisplayValue("Platform Engineer")).toBeInTheDocument();
  expect(screen.getByDisplayValue("Runs the internal deployment platform.")).toBeInTheDocument();
  expect(screen.getByDisplayValue("Platform Lead")).toBeInTheDocument();
  expect(screen.getByDisplayValue("2022-2024")).toBeInTheDocument();
  expect(screen.getByDisplayValue("Kubernetes, AWS")).toBeInTheDocument();
});

test("editing one field and saving calls updateBlock with the reassembled body", async () => {
  vi.mocked(api.updateBlock).mockResolvedValue({ ok: true } as Response);
  const onSaved = vi.fn();
  const user = userEvent.setup();

  render(<EditBlockDialog blockId="block-1" open onOpenChange={vi.fn()} onSaved={onSaved} />);
  await screen.findByDisplayValue("Platform Engineer");

  const roleInput = screen.getByLabelText(/^role$/i);
  await user.clear(roleInput);
  await user.type(roleInput, "Principal Engineer");

  await user.click(screen.getByRole("button", { name: /save/i }));

  await waitFor(() => expect(api.updateBlock).toHaveBeenCalledTimes(1));
  const [id, payload] = vi.mocked(api.updateBlock).mock.calls[0];
  expect(id).toBe("block-1");
  expect(payload.body).toContain("**Role:** Principal Engineer");
  expect(payload.body).toContain("# Platform Engineer");
  expect(payload.body).toContain("**Environment:** Kubernetes, AWS");
  await waitFor(() => expect(onSaved).toHaveBeenCalled());
});

test("copy full block writes the reassembled markdown to the clipboard", async () => {
  const user = userEvent.setup();

  render(<EditBlockDialog blockId="block-1" open onOpenChange={vi.fn()} />);
  await screen.findByDisplayValue("Platform Engineer");

  await user.click(screen.getByRole("button", { name: /copy full block/i }));

  await waitFor(() => expect(navigator.clipboard.writeText).toHaveBeenCalledTimes(1));
  const written = vi.mocked(navigator.clipboard.writeText).mock.calls[0][0];
  expect(written).toContain("# Platform Engineer");
  expect(written).toContain("**Role:** Platform Lead");
  expect(written).toContain("**Period:** 2022-2024");
  expect(written).toContain("**Environment:** Kubernetes, AWS");
});

test("pasting a whole block's text into a single field distributes it across all fields and toasts", async () => {
  const user = userEvent.setup();

  render(<EditBlockDialog blockId="block-1" open onOpenChange={vi.fn()} />);
  const description = await screen.findByDisplayValue("Runs the internal deployment platform.");

  await user.click(description);
  await user.paste(WHOLE_BLOCK_TEXT);

  expect(await screen.findByDisplayValue("Backend Engineer")).toBeInTheDocument();
  expect(screen.getByDisplayValue("Owns the payments service.")).toBeInTheDocument();
  expect(screen.getByDisplayValue("Backend Lead")).toBeInTheDocument();
  expect(screen.getByDisplayValue("2019-2021")).toBeInTheDocument();
  expect(screen.getByDisplayValue("Go, Postgres")).toBeInTheDocument();
  expect(toast.info).toHaveBeenCalled();
});

test("pasting ordinary text into one field lands only in that field", async () => {
  const user = userEvent.setup();

  render(<EditBlockDialog blockId="block-1" open onOpenChange={vi.fn()} />);
  const description = await screen.findByDisplayValue("Runs the internal deployment platform.");

  await user.click(description);
  await user.clear(description);
  await user.paste("just fixing a typo here");

  expect(screen.getByDisplayValue("just fixing a typo here")).toBeInTheDocument();
  expect(screen.getByDisplayValue("Platform Engineer")).toBeInTheDocument();
  expect(screen.getByDisplayValue("Platform Lead")).toBeInTheDocument();
  expect(screen.getByDisplayValue("2022-2024")).toBeInTheDocument();
  expect(screen.getByDisplayValue("Kubernetes, AWS")).toBeInTheDocument();
  expect(toast.info).not.toHaveBeenCalled();
});
