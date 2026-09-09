import { render, screen } from "@testing-library/react";
import { ComposePlan } from "@/features/compose/ComposePlan";
import type { PlanStep } from "@/features/compose/useComposeJob";

function step(overrides: Partial<PlanStep> = {}): PlanStep {
  return { order: 1, action: "generate", blockId: null, criteria: null, liveStatus: "pending", ...overrides };
}

test("renders one row per plan step, in order, with a distinct visual per status", () => {
  const planSteps = [
    step({ order: 2, liveStatus: "running", action: "mutate", criteria: "senior" }),
    step({ order: 1, liveStatus: "done", action: "use", blockId: "b1" }),
    step({ order: 3, liveStatus: "pending", action: "generate" }),
  ];

  render(<ComposePlan planSteps={planSteps} />);

  const rows = screen.getAllByTestId("plan-step");
  expect(rows).toHaveLength(3);
  // rendered in `order`, not array order
  expect(rows[0]).toHaveAttribute("data-status", "done");
  expect(rows[1]).toHaveAttribute("data-status", "running");
  expect(rows[2]).toHaveAttribute("data-status", "pending");

  expect(rows[0].querySelector("svg")).not.toBeNull();
  expect(rows[1].querySelector("svg")).not.toBeNull();
  expect(rows[2].querySelector("svg")).not.toBeNull();
});

test("renders nothing when there are no plan steps yet", () => {
  const { container } = render(<ComposePlan planSteps={[]} />);
  expect(container).toBeEmptyDOMElement();
});
