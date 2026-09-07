import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { LoginScreen } from "@/shared/LoginScreen";

function mockFetchOnce(response: Partial<Response>) {
  const fetchMock = vi.fn().mockResolvedValue(response as Response);
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

test("valid submission calls onValidated with the entered key", async () => {
  const fetchMock = mockFetchOnce({ ok: true, status: 200 });
  const onValidated = vi.fn();
  const user = userEvent.setup();
  render(<LoginScreen onValidated={onValidated} />);

  await user.type(screen.getByLabelText(/secret/i), "correct-key");
  await user.click(screen.getByRole("button", { name: /submit|unlock|continue/i }));

  await waitFor(() => expect(onValidated).toHaveBeenCalledWith("correct-key"));
  expect(fetchMock).toHaveBeenCalledTimes(1);
  const calledUrl = fetchMock.mock.calls[0][0] as string;
  expect(calledUrl).toContain("/auth/check");
  expect(calledUrl).toContain("key=correct-key");
});

test("invalid submission shows a rejection message and does not call onValidated", async () => {
  mockFetchOnce({ ok: false, status: 401 });
  const onValidated = vi.fn();
  const user = userEvent.setup();
  render(<LoginScreen onValidated={onValidated} />);

  await user.type(screen.getByLabelText(/secret/i), "wrong-key");
  await user.click(screen.getByRole("button", { name: /submit|unlock|continue/i }));

  await screen.findByText(/incorrect|invalid|rejected|unauthorized/i);
  expect(onValidated).not.toHaveBeenCalled();
});

test("empty submission is rejected client-side with no network call", async () => {
  const fetchMock = mockFetchOnce({ ok: true, status: 200 });
  const onValidated = vi.fn();
  const user = userEvent.setup();
  render(<LoginScreen onValidated={onValidated} />);

  await user.click(screen.getByRole("button", { name: /submit|unlock|continue/i }));

  expect(fetchMock).not.toHaveBeenCalled();
  expect(onValidated).not.toHaveBeenCalled();
});
