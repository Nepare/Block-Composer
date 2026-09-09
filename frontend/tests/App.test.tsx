import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import App from "@/app/App";
import * as session from "@/shared/session";

beforeEach(() => {
  session.clear();
});

afterEach(() => {
  vi.unstubAllGlobals();
  session.clear();
});

test("a stored valid key skips the login prompt and reaches the shell", async () => {
  session.set("valid-key");
  const fetchMock = vi.fn((url: string) => {
    if (url.includes("/auth/check")) return Promise.resolve({ ok: true, status: 200 } as Response);
    return Promise.resolve({ ok: true, status: 200, json: async () => [] } as Response);
  });
  vi.stubGlobal("fetch", fetchMock);

  render(<App />);

  expect(screen.getByText(/checking/i)).toBeInTheDocument();

  await waitFor(() => expect(screen.getByRole("tab", { name: /compose/i })).toBeInTheDocument());
  expect(screen.queryByLabelText(/secret/i)).not.toBeInTheDocument();
  const authCheckCalls = fetchMock.mock.calls.filter(([url]) => (url as string).includes("/auth/check"));
  expect(authCheckCalls).toHaveLength(1);
});

test("a stored key the backend rejects returns to the login screen with an explanation", async () => {
  session.set("stale-key");
  const fetchMock = vi.fn().mockResolvedValue({ ok: false, status: 401 } as Response);
  vi.stubGlobal("fetch", fetchMock);

  render(<App />);

  await waitFor(() => expect(screen.getByLabelText(/secret/i)).toBeInTheDocument());
  expect(screen.getByText(/expired|rejected|sign in again|session/i)).toBeInTheDocument();
  expect(session.get()).toBeNull();
});

test("once authenticated, the user can switch between Compose and Library tabs and see each one's content", async () => {
  session.set("valid-key");
  const fetchMock = vi.fn((url: string) => {
    if (url.includes("/blocks") || url.includes("/results")) {
      return Promise.resolve({ ok: true, status: 200, json: async () => [] } as Response);
    }
    return Promise.resolve({ ok: true, status: 200 } as Response);
  });
  vi.stubGlobal("fetch", fetchMock);
  const user = userEvent.setup();

  render(<App />);

  await waitFor(() => expect(screen.getByRole("tab", { name: /compose/i })).toBeInTheDocument());

  expect(screen.getByText("Specifications")).toBeInTheDocument();

  await user.click(screen.getByRole("tab", { name: /library/i }));
  expect(await screen.findByPlaceholderText(/search blocks/i)).toBeInTheDocument();

  await user.click(screen.getByRole("tab", { name: /compose/i }));
  expect(await screen.findByText("Specifications")).toBeInTheDocument();
});
