import { useState } from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Modal } from "@/shared/ui/Modal";
import { OriginIcon } from "@/shared/icons/OriginIcon";

function ControlledModal() {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button onClick={() => setOpen(true)}>Open modal</button>
      <Modal open={open} onOpenChange={setOpen} title="Modal title" description="Modal description">
        <button>Inside modal</button>
      </Modal>
    </>
  );
}

test("Modal is closed until opened, then renders its title and content", async () => {
  const user = userEvent.setup();
  render(<ControlledModal />);

  expect(screen.queryByText("Modal title")).not.toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "Open modal" }));

  expect(await screen.findByText("Modal title")).toBeInTheDocument();
  expect(screen.getByText("Modal description")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Inside modal" })).toBeInTheDocument();
});

test("Modal traps focus inside the dialog while open", async () => {
  const user = userEvent.setup();
  render(<ControlledModal />);

  await user.click(screen.getByRole("button", { name: "Open modal" }));
  await screen.findByText("Modal title");

  await waitFor(() => {
    expect(document.activeElement).not.toBe(document.body);
    expect(screen.getByRole("dialog")).toContainElement(document.activeElement as HTMLElement);
  });
});

test("Modal closes via its close control and calls onOpenChange(false)", async () => {
  const user = userEvent.setup();
  render(<ControlledModal />);

  await user.click(screen.getByRole("button", { name: "Open modal" }));
  await screen.findByText("Modal title");

  await user.click(screen.getByRole("button", { name: /close/i }));

  expect(screen.queryByText("Modal title")).not.toBeInTheDocument();
});

test("OriginIcon renders the dissected badge", () => {
  render(<OriginIcon origin="dissected" />);
  const badge = screen.getByRole("img", { name: /dissected/i });
  expect(badge).toHaveTextContent("🌐");
});

test("OriginIcon renders the mutated badge", () => {
  render(<OriginIcon origin="mutated" />);
  const badge = screen.getByRole("img", { name: /mutated/i });
  expect(badge).toHaveTextContent("♻️");
});

test("OriginIcon renders the generated badge", () => {
  render(<OriginIcon origin="generated" />);
  const badge = screen.getByRole("img", { name: /generated/i });
  expect(badge).toHaveTextContent("🌱");
});
