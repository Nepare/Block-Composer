import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { BlockGrid } from "@/features/library/BlockGrid";
import { BlockTile, type LibraryBlockRecord } from "@/features/library/BlockTile";
import type { PendingJob } from "@/features/library/useLibraryJobs";
import { TooltipProvider } from "@/shared/ui/tooltip";
import * as session from "@/shared/session";
import * as api from "@/features/library/api";
import { toast } from "sonner";

vi.mock("@/features/library/api", async () => {
  const actual = await vi.importActual<typeof import("@/features/library/api")>(
    "@/features/library/api"
  );
  return { ...actual, preserveBlock: vi.fn(), unpreserveBlock: vi.fn(), clearBlocks: vi.fn() };
});

vi.mock("sonner", () => ({
  toast: { info: vi.fn(), success: vi.fn(), error: vi.fn() },
}));

interface FixtureBlock {
  id: string;
  name: string;
  created_at: string;
  created_by: string;
  body: string;
  preserved: boolean;
}

function fixture(overrides: Partial<FixtureBlock> = {}): FixtureBlock {
  return {
    id: "block-1",
    name: "Sample Block",
    created_at: "2026-01-01T00:00:00Z",
    created_by: "manual",
    body: "# Sample Block\nA description.\n**Environment:** Python, Docker\n",
    preserved: false,
    ...overrides,
  };
}

function summaryOf(block: FixtureBlock) {
  return {
    id: block.id,
    name: block.name,
    tags: [],
    schema: null,
    source: "manual",
    created_at: block.created_at,
    preserved: block.preserved,
  };
}

function detailOf(block: FixtureBlock) {
  return {
    ...summaryOf(block),
    body: block.body,
    created_by: block.created_by,
    generation_criteria: null,
    mutated_from: null,
  };
}

function mockLibraryFetch(blocks: FixtureBlock[]) {
  return vi.fn((url: string) => {
    const path = url.split("?")[0];
    if (path === "/blocks") {
      return Promise.resolve({
        ok: true,
        status: 200,
        json: async () => blocks.map(summaryOf),
      } as Response);
    }
    const match = path.match(/^\/blocks\/(.+)$/);
    if (match) {
      const block = blocks.find((b) => b.id === decodeURIComponent(match[1]));
      return Promise.resolve({
        ok: true,
        status: 200,
        json: async () => detailOf(block!),
      } as Response);
    }
    return Promise.resolve({ ok: false, status: 404 } as Response);
  });
}

beforeEach(() => {
  session.set("test-key");
  localStorage.removeItem("cvdocs.libraryView");
  vi.mocked(api.preserveBlock).mockResolvedValue({ ok: true } as Response);
  vi.mocked(api.unpreserveBlock).mockResolvedValue({ ok: true } as Response);
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.clearAllMocks();
  session.clear();
  localStorage.clear();
});

test("renders one tile per fetched block, showing title, environment, and origin", async () => {
  const blocks = [
    fixture({
      id: "b1",
      name: "Backend Engineer",
      created_by: "generated",
      body: "# Backend Engineer\nDesc.\n**Environment:** Python, Docker\n",
    }),
    fixture({
      id: "b2",
      name: "Frontend Developer",
      created_by: "dissected",
      body: "# Frontend Developer\nDesc.\n**Environment:** React, TypeScript\n",
    }),
  ];
  vi.stubGlobal("fetch", mockLibraryFetch(blocks));

  render(
    <TooltipProvider>
      <BlockGrid />
    </TooltipProvider>
  );

  expect(await screen.findByText("Backend Engineer")).toBeInTheDocument();
  expect(screen.getByText("Frontend Developer")).toBeInTheDocument();
  expect(screen.getByText("Python, Docker")).toBeInTheDocument();
  expect(screen.getByText("React, TypeScript")).toBeInTheDocument();
  expect(screen.getByRole("img", { name: /generated/i })).toBeInTheDocument();
  expect(screen.getByRole("img", { name: /dissected/i })).toBeInTheDocument();
});

test("shows the same per-block information across all three view modes", async () => {
  const blocks = [
    fixture({
      id: "b1",
      name: "Backend Engineer",
      created_by: "generated",
      body: "# Backend Engineer\nDesc.\n**Environment:** Python, Docker\n",
    }),
  ];
  vi.stubGlobal("fetch", mockLibraryFetch(blocks));
  const user = userEvent.setup();

  render(
    <TooltipProvider>
      <BlockGrid />
    </TooltipProvider>
  );
  await screen.findByText("Backend Engineer");

  for (const label of ["List", "2-column", "3-column"]) {
    await user.click(screen.getByRole("button", { name: label }));
    expect(screen.getByText("Backend Engineer")).toBeInTheDocument();
    expect(screen.getByText("Python, Docker")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: /generated/i })).toBeInTheDocument();
  }
});

test("narrows the grid to blocks matching a search term", async () => {
  const blocks = [
    fixture({ id: "b1", name: "Backend Engineer", body: "# Backend Engineer\n" }),
    fixture({ id: "b2", name: "Frontend Developer", body: "# Frontend Developer\n" }),
  ];
  vi.stubGlobal("fetch", mockLibraryFetch(blocks));
  const user = userEvent.setup();

  render(
    <TooltipProvider>
      <BlockGrid />
    </TooltipProvider>
  );
  await screen.findByText("Backend Engineer");
  expect(screen.getByText("Frontend Developer")).toBeInTheDocument();

  await user.type(screen.getByPlaceholderText(/search/i), "Frontend");

  expect(screen.queryByText("Backend Engineer")).not.toBeInTheDocument();
  expect(screen.getByText("Frontend Developer")).toBeInTheDocument();
});

test("orders blocks newest-first by default", async () => {
  const blocks = [
    fixture({ id: "old", name: "Older Block", created_at: "2025-01-01T00:00:00Z", body: "# Older Block\n" }),
    fixture({ id: "new", name: "Newer Block", created_at: "2026-05-01T00:00:00Z", body: "# Newer Block\n" }),
  ];
  vi.stubGlobal("fetch", mockLibraryFetch(blocks));

  render(
    <TooltipProvider>
      <BlockGrid />
    </TooltipProvider>
  );
  await screen.findByText("Newer Block");

  const tiles = screen.getAllByTestId("block-tile");
  expect(within(tiles[0]).getByText("Newer Block")).toBeInTheDocument();
  expect(within(tiles[1]).getByText("Older Block")).toBeInTheDocument();
});

test("persists the chosen view mode to localStorage and restores it on remount", async () => {
  const blocks = [fixture({ id: "b1", name: "Backend Engineer", body: "# Backend Engineer\n" })];
  vi.stubGlobal("fetch", mockLibraryFetch(blocks));
  const user = userEvent.setup();

  const { unmount } = render(
    <TooltipProvider>
      <BlockGrid />
    </TooltipProvider>
  );
  await screen.findByText("Backend Engineer");

  await user.click(screen.getByRole("button", { name: "3-column" }));
  expect(localStorage.getItem("cvdocs.libraryView")).toBe("grid-3");
  unmount();

  render(
    <TooltipProvider>
      <BlockGrid />
    </TooltipProvider>
  );
  await screen.findByText("Backend Engineer");
  expect(screen.getByRole("button", { name: "3-column" })).toHaveAttribute("aria-pressed", "true");
});

test("BlockTile clamps a long environment list to two lines and exposes the full text via a title attribute", () => {
  const longEnvironment = [
    "Python",
    "Docker",
    "Kubernetes",
    "AWS",
    "Postgres",
    "Redis",
    "Terraform",
    "GraphQL",
    "gRPC",
    "Kafka",
  ];
  const block: LibraryBlockRecord = {
    id: "b1",
    name: "Platform Engineer",
    created_at: "2026-01-01T00:00:00Z",
    created_by: "manual",
    environment: longEnvironment,
    preserved: false,
  };

  render(
    <TooltipProvider>
      <BlockTile block={block} viewMode="grid-2" />
    </TooltipProvider>
  );

  const fullText = longEnvironment.join(", ");
  const environmentEl = screen.getByTitle(fullText);
  expect(environmentEl).toHaveClass("line-clamp-2");
  expect(environmentEl).toHaveClass("w-fit");
  expect(environmentEl).toHaveTextContent(fullText);
});

test("BlockTile's environment text is wrapped in a Tooltip trigger carrying the full text", () => {
  const block: LibraryBlockRecord = {
    id: "b1",
    name: "Platform Engineer",
    created_at: "2026-01-01T00:00:00Z",
    created_by: "manual",
    environment: ["Python", "Docker", "Kubernetes"],
    preserved: false,
  };

  render(
    <TooltipProvider>
      <BlockTile block={block} viewMode="grid-2" />
    </TooltipProvider>
  );

  const fullText = "Python, Docker, Kubernetes";
  const trigger = screen.getByText(fullText);
  expect(trigger).toHaveAttribute("title", fullText);
  expect(trigger.tagName).toBe("P");
});

function runningJob(overrides: Partial<PendingJob> = {}): PendingJob {
  return {
    jobId: "job-1",
    kind: "generate",
    messages: [],
    status: "running",
    resultBlockId: null,
    errorMessage: null,
    ...overrides,
  };
}

test("a pending-job placeholder tile renders fully inert — no clickable controls at all", async () => {
  vi.stubGlobal("fetch", mockLibraryFetch([]));
  const onDismissJob = vi.fn();

  render(
    <TooltipProvider>
      <BlockGrid pendingJobs={[runningJob({ messages: ["Thinking..."] })]} onDismissJob={onDismissJob} />
    </TooltipProvider>
  );

  const tile = await screen.findByTestId("pending-block-tile");
  expect(within(tile).queryAllByRole("button")).toHaveLength(0);
  expect(screen.getByText("Thinking...")).toBeInTheDocument();

  await userEvent.setup().click(tile);
  expect(onDismissJob).not.toHaveBeenCalled();
});

test("a pending-job placeholder shows a live-updating message queue as new events are supplied", async () => {
  vi.stubGlobal("fetch", mockLibraryFetch([]));

  const { rerender } = render(
    <TooltipProvider>
      <BlockGrid pendingJobs={[runningJob({ messages: ["step 1"] })]} />
    </TooltipProvider>
  );
  await screen.findByTestId("pending-block-tile");
  expect(screen.getByText("step 1")).toBeInTheDocument();

  rerender(
    <TooltipProvider>
      <BlockGrid pendingJobs={[runningJob({ messages: ["step 1", "step 2"] })]} />
    </TooltipProvider>
  );
  expect(screen.getByText("step 1")).toBeInTheDocument();
  expect(screen.getByText("step 2")).toBeInTheDocument();
});

test("an error-status pending tile shows the failure and a working dismiss control", async () => {
  vi.stubGlobal("fetch", mockLibraryFetch([]));
  const onDismissJob = vi.fn();
  const user = userEvent.setup();

  render(
    <TooltipProvider>
      <BlockGrid
        pendingJobs={[runningJob({ status: "error", errorMessage: "The LLM timed out." })]}
        onDismissJob={onDismissJob}
      />
    </TooltipProvider>
  );

  await screen.findByText("The LLM timed out.");
  await user.click(screen.getByRole("button", { name: /dismiss/i }));
  expect(onDismissJob).toHaveBeenCalledWith("job-1");
});

test("a resolving pending job is confirmed once the refetched list contains its resultBlockId, and disappears once removed from pendingJobs", async () => {
  let includeNewBlock = false;
  const fetchMock = vi.fn((url: string) => {
    const path = url.split("?")[0];
    if (path === "/blocks") {
      const blocks = includeNewBlock
        ? [fixture({ id: "new-block", name: "New Block", body: "# New Block\n" })]
        : [];
      return Promise.resolve({ ok: true, status: 200, json: async () => blocks.map(summaryOf) } as Response);
    }
    const match = path.match(/^\/blocks\/(.+)$/);
    if (match && match[1] === "new-block") {
      return Promise.resolve({
        ok: true,
        status: 200,
        json: async () => detailOf(fixture({ id: "new-block", name: "New Block", body: "# New Block\n" })),
      } as Response);
    }
    return Promise.resolve({ ok: false, status: 404 } as Response);
  });
  vi.stubGlobal("fetch", fetchMock);
  const onJobResolved = vi.fn();
  const job = runningJob({ status: "resolving", resultBlockId: "new-block" });

  const { rerender } = render(
    <TooltipProvider>
      <BlockGrid pendingJobs={[job]} onJobResolved={onJobResolved} refetchToken={0} />
    </TooltipProvider>
  );
  await screen.findByTestId("pending-block-tile");
  expect(onJobResolved).not.toHaveBeenCalled();

  includeNewBlock = true;
  rerender(
    <TooltipProvider>
      <BlockGrid pendingJobs={[job]} onJobResolved={onJobResolved} refetchToken={1} />
    </TooltipProvider>
  );

  await waitFor(() => expect(onJobResolved).toHaveBeenCalledWith("job-1"));

  rerender(
    <TooltipProvider>
      <BlockGrid pendingJobs={[]} onJobResolved={onJobResolved} refetchToken={1} />
    </TooltipProvider>
  );
  expect(screen.queryByTestId("pending-block-tile")).not.toBeInTheDocument();
  expect(await screen.findByText("New Block")).toBeInTheDocument();
});

test("preserving a block calls preserveBlock, thickens its tile border, and disables its Delete control", async () => {
  const blocks = [fixture({ id: "b1", name: "Backend Engineer", body: "# Backend Engineer\n" })];
  vi.stubGlobal("fetch", mockLibraryFetch(blocks));
  const user = userEvent.setup();

  render(
    <TooltipProvider>
      <BlockGrid />
    </TooltipProvider>
  );
  await screen.findByText("Backend Engineer");

  const tile = screen.getByTestId("block-tile");
  expect(tile).toHaveClass("border-border");

  await user.click(within(tile).getByRole("button", { name: "Preserve" }));

  expect(api.preserveBlock).toHaveBeenCalledWith("b1");
  await waitFor(() => expect(tile).toHaveClass("border-primary"));
  expect(within(tile).getByRole("button", { name: "Unpreserve" })).toBeInTheDocument();
  expect(within(tile).getByRole("button", { name: "Delete" })).toBeDisabled();
});

test("unpreserving a previously preserved block calls unpreserveBlock and restores normal appearance", async () => {
  const blocks = [fixture({ id: "b1", name: "Backend Engineer", body: "# Backend Engineer\n", preserved: true })];
  vi.stubGlobal("fetch", mockLibraryFetch(blocks));
  const user = userEvent.setup();

  render(
    <TooltipProvider>
      <BlockGrid />
    </TooltipProvider>
  );
  await screen.findByText("Backend Engineer");

  const tile = screen.getByTestId("block-tile");
  expect(tile).toHaveClass("border-primary");
  expect(within(tile).getByRole("button", { name: "Delete" })).toBeDisabled();

  await user.click(within(tile).getByRole("button", { name: "Unpreserve" }));

  expect(api.unpreserveBlock).toHaveBeenCalledWith("b1");
  await waitFor(() => expect(tile).toHaveClass("border-border"));
  expect(within(tile).getByRole("button", { name: "Preserve" })).toBeInTheDocument();
  expect(within(tile).getByRole("button", { name: "Delete" })).not.toBeDisabled();
});

test("clearing the library always shows its own warning even when the per-block delete warning is suppressed, then clears and toasts", async () => {
  localStorage.setItem("cvdocs.skipDeleteWarning", "true");
  const blocks = [
    fixture({ id: "b1", name: "Backend Engineer", body: "# Backend Engineer\n" }),
    fixture({ id: "b2", name: "Preserved One", body: "# Preserved One\n", preserved: true }),
  ];
  vi.stubGlobal("fetch", mockLibraryFetch(blocks));
  vi.mocked(api.clearBlocks).mockImplementation(async () => {
    blocks.splice(
      0,
      blocks.length,
      ...blocks.filter((b) => b.preserved)
    );
    return {
      ok: true,
      status: 200,
      json: async () => ({ deleted: 1, skipped_preserved: 1 }),
    } as Response;
  });
  const user = userEvent.setup();

  render(
    <TooltipProvider>
      <BlockGrid />
    </TooltipProvider>
  );
  await screen.findByText("Backend Engineer");

  await user.click(screen.getByRole("button", { name: "Clear library" }));

  expect(screen.getByRole("heading", { name: "Clear library" })).toBeInTheDocument();
  expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: /confirm/i }));

  expect(api.clearBlocks).toHaveBeenCalledTimes(1);
  await waitFor(() => expect(screen.queryByText("Backend Engineer")).not.toBeInTheDocument());
  expect(screen.getByText("Preserved One")).toBeInTheDocument();
  expect(toast.success).toHaveBeenCalledWith("Cleared 1 block(s), kept 1 preserved.");
});
