import { act, renderHook, waitFor } from "@testing-library/react";
import {
  useGoogleAuthStatus,
  POLL_INTERVAL_MS,
  POLL_TIMEOUT_MS,
} from "@/features/library/useGoogleAuthStatus";
import * as api from "@/features/library/api";

vi.mock("@/features/library/api", async () => {
  const actual = await vi.importActual<typeof import("@/features/library/api")>(
    "@/features/library/api"
  );
  return { ...actual, getGoogleAuthStatus: vi.fn() };
});

afterEach(() => {
  vi.clearAllMocks();
  vi.restoreAllMocks();
  vi.useRealTimers();
});

test("checking is true until the initial status fetch resolves", async () => {
  let resolveStatus!: (value: api.GoogleAuthStatus) => void;
  vi.mocked(api.getGoogleAuthStatus).mockReturnValue(
    new Promise((resolve) => {
      resolveStatus = resolve;
    })
  );

  const { result } = renderHook(() => useGoogleAuthStatus(true));

  expect(result.current.checking).toBe(true);
  expect(result.current.connected).toBe(false);

  await act(async () => {
    resolveStatus({ connected: true });
  });

  expect(result.current.checking).toBe(false);
  expect(result.current.connected).toBe(true);
});

test("reflects connected:false from the initial fetch", async () => {
  vi.mocked(api.getGoogleAuthStatus).mockResolvedValue({ connected: false });

  const { result } = renderHook(() => useGoogleAuthStatus(true));

  await waitFor(() => expect(result.current.checking).toBe(false));
  expect(result.current.connected).toBe(false);
  expect(api.getGoogleAuthStatus).toHaveBeenCalledTimes(1);
});

test("startPolling re-checks status on an interval until connected, then stops", async () => {
  vi.useFakeTimers();
  const calls = [{ connected: false }, { connected: false }, { connected: true }];
  vi.mocked(api.getGoogleAuthStatus).mockImplementation(() => Promise.resolve(calls.shift()!));

  const { result } = renderHook(() => useGoogleAuthStatus(true));
  await act(async () => {
    await vi.advanceTimersByTimeAsync(0);
  });
  expect(api.getGoogleAuthStatus).toHaveBeenCalledTimes(1); // the initial mount fetch

  act(() => result.current.startPolling());

  await act(async () => {
    await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS);
  });
  expect(result.current.connected).toBe(false);
  expect(api.getGoogleAuthStatus).toHaveBeenCalledTimes(2);

  await act(async () => {
    await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS);
  });
  expect(result.current.connected).toBe(true);
  expect(api.getGoogleAuthStatus).toHaveBeenCalledTimes(3);

  // further ticks must not keep polling once connected
  await act(async () => {
    await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS * 3);
  });
  expect(api.getGoogleAuthStatus).toHaveBeenCalledTimes(3);
});

test("startPolling gives up after the timeout without ever becoming connected", async () => {
  vi.useFakeTimers();
  vi.mocked(api.getGoogleAuthStatus).mockResolvedValue({ connected: false });

  const { result } = renderHook(() => useGoogleAuthStatus(true));
  await act(async () => {
    await vi.advanceTimersByTimeAsync(0);
  });

  act(() => result.current.startPolling());
  const callsAtStart = vi.mocked(api.getGoogleAuthStatus).mock.calls.length;

  await act(async () => {
    await vi.advanceTimersByTimeAsync(POLL_TIMEOUT_MS + POLL_INTERVAL_MS * 2);
  });

  expect(result.current.connected).toBe(false);
  const callsDuringTimeout = vi.mocked(api.getGoogleAuthStatus).mock.calls.length - callsAtStart;

  // one more tick well past the timeout must not add another call
  const callsAfterTimeout = vi.mocked(api.getGoogleAuthStatus).mock.calls.length;
  await act(async () => {
    await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS * 2);
  });
  expect(vi.mocked(api.getGoogleAuthStatus).mock.calls.length).toBe(callsAfterTimeout);
  expect(callsDuringTimeout).toBeGreaterThan(0);
});

test("does not fetch status while inactive", async () => {
  vi.mocked(api.getGoogleAuthStatus).mockResolvedValue({ connected: false });

  const { result } = renderHook(() => useGoogleAuthStatus(false));

  expect(result.current.checking).toBe(false);
  await new Promise((resolve) => setTimeout(resolve, 0));
  expect(api.getGoogleAuthStatus).not.toHaveBeenCalled();
});

test("fetches status once active flips from false to true", async () => {
  vi.mocked(api.getGoogleAuthStatus).mockResolvedValue({ connected: true });

  const { result, rerender } = renderHook(({ active }) => useGoogleAuthStatus(active), {
    initialProps: { active: false },
  });
  expect(api.getGoogleAuthStatus).not.toHaveBeenCalled();

  rerender({ active: true });

  await waitFor(() => expect(result.current.connected).toBe(true));
  expect(api.getGoogleAuthStatus).toHaveBeenCalledTimes(1);
});

test("going inactive stops an in-flight poll", async () => {
  vi.useFakeTimers();
  vi.mocked(api.getGoogleAuthStatus).mockResolvedValue({ connected: false });

  const { result, rerender } = renderHook(({ active }) => useGoogleAuthStatus(active), {
    initialProps: { active: true },
  });
  await act(async () => {
    await vi.advanceTimersByTimeAsync(0);
  });

  act(() => result.current.startPolling());
  const callsBeforeInactive = vi.mocked(api.getGoogleAuthStatus).mock.calls.length;

  rerender({ active: false });

  await act(async () => {
    await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS * 5);
  });
  expect(vi.mocked(api.getGoogleAuthStatus).mock.calls.length).toBe(callsBeforeInactive);
});

test("cleans up the polling interval on unmount", async () => {
  vi.useFakeTimers();
  vi.mocked(api.getGoogleAuthStatus).mockResolvedValue({ connected: false });

  const { result, unmount } = renderHook(() => useGoogleAuthStatus(true));
  await act(async () => {
    await vi.advanceTimersByTimeAsync(0);
  });

  act(() => result.current.startPolling());
  const callsBeforeUnmount = vi.mocked(api.getGoogleAuthStatus).mock.calls.length;

  unmount();

  await act(async () => {
    await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS * 5);
  });
  expect(vi.mocked(api.getGoogleAuthStatus).mock.calls.length).toBe(callsBeforeUnmount);
});
