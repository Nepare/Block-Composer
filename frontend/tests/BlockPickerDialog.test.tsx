import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { BlockPickerDialog } from "@/features/compose/BlockPickerDialog";
import * as api from "@/features/library/api";

vi.mock("@/features/library/api", async () => {
  const actual = await vi.importActual<typeof import("@/features/library/api")>("@/features/library/api");
  return { ...actual, listBlocks: vi.fn(), getBlock: vi.fn() };
});

function summary(id: string, name: string) {
  return { id, name, tags: [], schema: null, source: "manual", created_at: null, preserved: false };
}

function detail(id: string, name: string) {
  return { ...summary(id, name), body: `# ${name}\n`, created_by: "manual", generation_criteria: null, mutated_from: null };
}

beforeEach(() => {
  localStorage.removeItem("cvdocs.libraryView");
  vi.mocked(api.listBlocks).mockResolvedValue([summary("b1", "Backend Engineer"), summary("b2", "Frontend Developer")]);
  vi.mocked(api.getBlock).mockImplementation(async (id: string) =>
    id === "b1" ? detail("b1", "Backend Engineer") : detail("b2", "Frontend Developer")
  );
});

afterEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
});

test("renders the same search/view-mode experience as Library's grid with a selection checkbox per tile and no library-management actions", async () => {
  render(<BlockPickerDialog open onOpenChange={vi.fn()} initialSelectedIds={[]} onDone={vi.fn()} />);

  expect(await screen.findByText("Backend Engineer")).toBeInTheDocument();
  expect(screen.getByPlaceholderText(/search/i)).toBeInTheDocument();
  expect(screen.getByRole("group", { name: /view mode/i })).toBeInTheDocument();
  expect(screen.getAllByRole("checkbox")).toHaveLength(2);
  expect(screen.queryByRole("button", { name: /populate the library/i })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /clear library/i })).not.toBeInTheDocument();
});

test("narrows to blocks matching a search term, same as Library's grid", async () => {
  const user = userEvent.setup();
  render(<BlockPickerDialog open onOpenChange={vi.fn()} initialSelectedIds={[]} onDone={vi.fn()} />);
  await screen.findByText("Backend Engineer");

  await user.type(screen.getByPlaceholderText(/search/i), "Frontend");

  expect(screen.queryByText("Backend Engineer")).not.toBeInTheDocument();
  expect(screen.getByText("Frontend Developer")).toBeInTheDocument();
});

test("reopening with an existing selection pre-checks those blocks", async () => {
  const { rerender } = render(
    <BlockPickerDialog open={false} onOpenChange={vi.fn()} initialSelectedIds={["b2"]} onDone={vi.fn()} />
  );
  rerender(<BlockPickerDialog open onOpenChange={vi.fn()} initialSelectedIds={["b2"]} onDone={vi.fn()} />);

  const checkedTile = (await screen.findByText("Frontend Developer")).closest('[data-testid="picker-tile"]') as HTMLElement;
  expect(within(checkedTile).getByRole("checkbox")).toBeChecked();
  const uncheckedTile = screen.getByText("Backend Engineer").closest('[data-testid="picker-tile"]') as HTMLElement;
  expect(within(uncheckedTile).getByRole("checkbox")).not.toBeChecked();
});

test("Done commits the selected id set", async () => {
  const user = userEvent.setup();
  const onDone = vi.fn();
  render(<BlockPickerDialog open onOpenChange={vi.fn()} initialSelectedIds={[]} onDone={onDone} />);

  const tile = (await screen.findByText("Backend Engineer")).closest('[data-testid="picker-tile"]') as HTMLElement;
  await user.click(within(tile).getByRole("checkbox"));
  await user.click(screen.getByRole("button", { name: /^done$/i }));

  expect(onDone).toHaveBeenCalledWith(["b1"]);
});

test("toggling a tile's checkbox does not toggle any other tile", async () => {
  const user = userEvent.setup();
  const onDone = vi.fn();
  render(<BlockPickerDialog open onOpenChange={vi.fn()} initialSelectedIds={[]} onDone={onDone} />);

  const tile = (await screen.findByText("Backend Engineer")).closest('[data-testid="picker-tile"]') as HTMLElement;
  await user.click(within(tile).getByRole("checkbox"));
  await user.click(within(tile).getByRole("checkbox"));

  await user.click(screen.getByRole("button", { name: /^done$/i }));
  expect(onDone).toHaveBeenCalledWith([]);
});
