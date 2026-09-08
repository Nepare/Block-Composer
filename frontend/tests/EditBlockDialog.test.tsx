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
    "",
    "**Responsibilities:**",
    "- Designed the deployment pipeline",
    "- Mentored two junior engineers",
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

test("opens pre-filled with the block's name, description, and raw metadata", async () => {
  render(<EditBlockDialog blockId="block-1" open onOpenChange={vi.fn()} />);

  expect(await screen.findByDisplayValue("Platform Engineer")).toBeInTheDocument();
  expect(screen.getByDisplayValue("Runs the internal deployment platform.")).toBeInTheDocument();

  const metadata = screen.getByLabelText(/details/i) as HTMLTextAreaElement;
  expect(metadata.value).toContain("**Role:** Platform Lead");
  expect(metadata.value).toContain("**Period:** 2022-2024");
  expect(metadata.value).toContain("**Environment:** Kubernetes, AWS");
  expect(metadata.value).toContain("- Designed the deployment pipeline");
  expect(metadata.value).toContain("- Mentored two junior engineers");
});

test("editing the details textarea and saving persists the raw markdown as-is", async () => {
  vi.mocked(api.updateBlock).mockResolvedValue({ ok: true } as Response);
  const onSaved = vi.fn();
  const user = userEvent.setup();

  render(<EditBlockDialog blockId="block-1" open onOpenChange={vi.fn()} onSaved={onSaved} />);
  await screen.findByDisplayValue("Platform Engineer");

  const metadata = screen.getByLabelText(/details/i);
  await user.click(metadata);
  await user.paste("**Role:** Principal Engineer");

  await user.click(screen.getByRole("button", { name: /save/i }));

  await waitFor(() => expect(api.updateBlock).toHaveBeenCalledTimes(1));
  const [id, payload] = vi.mocked(api.updateBlock).mock.calls[0];
  expect(id).toBe("block-1");
  expect(payload.body).toContain("# Platform Engineer");
  expect(payload.body).toContain("Runs the internal deployment platform.");
  expect(payload.body).toContain("**Role:** Principal Engineer");
  await waitFor(() => expect(onSaved).toHaveBeenCalled());
});

test("copy full block writes the concatenated markdown to the clipboard", async () => {
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
  expect(written).toContain("- Designed the deployment pipeline");
});

test("pasting a whole block's text into Name distributes it across Name, Description, and Details, and toasts", async () => {
  const user = userEvent.setup();

  render(<EditBlockDialog blockId="block-1" open onOpenChange={vi.fn()} />);
  const nameInput = await screen.findByDisplayValue("Platform Engineer");

  await user.click(nameInput);
  await user.paste(WHOLE_BLOCK_TEXT);

  expect(await screen.findByDisplayValue("Backend Engineer")).toBeInTheDocument();
  expect(screen.getByDisplayValue("Owns the payments service.")).toBeInTheDocument();
  const metadata = screen.getByLabelText(/details/i) as HTMLTextAreaElement;
  expect(metadata.value).toContain("**Role:** Backend Lead");
  expect(metadata.value).toContain("**Environment:** Go, Postgres");
  expect(toast.info).toHaveBeenCalled();
});

test("pasting ordinary text into Description lands only in that field, without redistributing", async () => {
  const user = userEvent.setup();

  render(<EditBlockDialog blockId="block-1" open onOpenChange={vi.fn()} />);
  const description = await screen.findByDisplayValue("Runs the internal deployment platform.");

  await user.click(description);
  await user.clear(description);
  await user.paste("just fixing a typo here");

  expect(screen.getByDisplayValue("just fixing a typo here")).toBeInTheDocument();
  expect(screen.getByDisplayValue("Platform Engineer")).toBeInTheDocument();
  expect(toast.info).not.toHaveBeenCalled();
});
