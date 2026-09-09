import { useState } from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ConfirmDialog } from "@/shared/ui/ConfirmDialog";

afterEach(() => {
  localStorage.clear();
});

test("shows the dialog by default when opened", () => {
  render(
    <ConfirmDialog open onOpenChange={vi.fn()} title="Delete block" onConfirm={vi.fn()} />
  );

  expect(screen.getByText("Delete block")).toBeInTheDocument();
});

test("renders a don't-show-again checkbox only when a suppressionKey is supplied", () => {
  const { rerender } = render(
    <ConfirmDialog open onOpenChange={vi.fn()} title="Delete block" onConfirm={vi.fn()} />
  );
  expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();

  rerender(
    <ConfirmDialog
      open
      onOpenChange={vi.fn()}
      title="Delete block"
      onConfirm={vi.fn()}
      suppressionKey="test.suppress"
    />
  );
  expect(screen.getByRole("checkbox")).toBeInTheDocument();
});

test("checking don't-show-again and confirming persists the preference to localStorage and calls onConfirm", async () => {
  const user = userEvent.setup();
  const onConfirm = vi.fn();

  render(
    <ConfirmDialog
      open
      onOpenChange={vi.fn()}
      title="Delete block"
      onConfirm={onConfirm}
      suppressionKey="cvdocs.skipDeleteWarning"
    />
  );

  await user.click(screen.getByRole("checkbox"));
  await user.click(screen.getByRole("button", { name: /confirm/i }));

  expect(onConfirm).toHaveBeenCalledTimes(1);
  expect(localStorage.getItem("cvdocs.skipDeleteWarning")).toBe("true");
});

test("confirming without checking don't-show-again leaves localStorage untouched", async () => {
  const user = userEvent.setup();
  const onConfirm = vi.fn();

  render(
    <ConfirmDialog
      open
      onOpenChange={vi.fn()}
      title="Delete block"
      onConfirm={onConfirm}
      suppressionKey="cvdocs.skipDeleteWarning"
    />
  );

  await user.click(screen.getByRole("button", { name: /confirm/i }));

  expect(onConfirm).toHaveBeenCalledTimes(1);
  expect(localStorage.getItem("cvdocs.skipDeleteWarning")).toBeNull();
});

// The caller — not ConfirmDialog itself — is responsible for checking the suppression key
// before opening the dialog at all. This harness mirrors BlockGrid's delete-request contract.
function DeleteCaller({ onConfirm }: { onConfirm: () => void }) {
  const [open, setOpen] = useState(false);

  function requestDelete() {
    if (localStorage.getItem("cvdocs.skipDeleteWarning") === "true") {
      onConfirm();
      return;
    }
    setOpen(true);
  }

  return (
    <>
      <button type="button" onClick={requestDelete}>
        Delete
      </button>
      <ConfirmDialog
        open={open}
        onOpenChange={setOpen}
        title="Delete block"
        onConfirm={onConfirm}
        suppressionKey="cvdocs.skipDeleteWarning"
      />
    </>
  );
}

test("a caller that checks the suppression key skips the dialog on a later call once suppressed", async () => {
  const user = userEvent.setup();
  const onConfirm = vi.fn();

  const { unmount } = render(<DeleteCaller onConfirm={onConfirm} />);
  await user.click(screen.getByRole("button", { name: "Delete" }));
  expect(screen.getByText("Delete block")).toBeInTheDocument();

  await user.click(screen.getByRole("checkbox"));
  await user.click(screen.getByRole("button", { name: /confirm/i }));
  await waitFor(() => expect(localStorage.getItem("cvdocs.skipDeleteWarning")).toBe("true"));
  unmount();

  // Simulates a later visit / a fresh mount: the caller now checks localStorage up front.
  render(<DeleteCaller onConfirm={onConfirm} />);
  await user.click(screen.getByRole("button", { name: "Delete" }));

  expect(screen.queryByText("Delete block")).not.toBeInTheDocument();
  expect(onConfirm).toHaveBeenCalledTimes(2);
});

test("omitting suppressionKey never renders a checkbox, even after confirming", async () => {
  const user = userEvent.setup();
  const onConfirm = vi.fn();

  render(<ConfirmDialog open onOpenChange={vi.fn()} title="Clear library" onConfirm={onConfirm} />);

  expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: /confirm/i }));
  expect(onConfirm).toHaveBeenCalledTimes(1);
});
