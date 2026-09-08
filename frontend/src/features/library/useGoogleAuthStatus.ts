import { useCallback, useEffect, useRef, useState } from "react";
import { getGoogleAuthStatus } from "@/features/library/api";

export const POLL_INTERVAL_MS = 2000;
export const POLL_TIMEOUT_MS = 120000;

export interface UseGoogleAuthStatusResult {
  connected: boolean;
  checking: boolean;
  startPolling: () => void;
}

// Reinstates the connection feedback loop spec 016 deferred: the connect popup itself has no
// way to signal the tab that opened it, so this polls /auth/google/status instead. Gated on
// `active` (the dialog's own open state) rather than firing on mount — this component stays
// mounted-but-hidden the whole time the app is up, and a real Google connection check has no
// reason to run while nobody's looking at the connect button.
export function useGoogleAuthStatus(active: boolean): UseGoogleAuthStatusResult {
  const [connected, setConnected] = useState(false);
  const [checking, setChecking] = useState(active);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const stopPolling = useCallback(() => {
    if (intervalRef.current !== null) {
      clearInterval(intervalRef.current);
      intervalRef.current = null;
    }
    if (timeoutRef.current !== null) {
      clearTimeout(timeoutRef.current);
      timeoutRef.current = null;
    }
  }, []);

  const refresh = useCallback(async () => {
    try {
      const status = await getGoogleAuthStatus();
      setConnected(status.connected);
      if (status.connected) stopPolling();
    } finally {
      setChecking(false);
    }
  }, [stopPolling]);

  useEffect(() => {
    if (!active) {
      stopPolling();
      return;
    }
    setChecking(true);
    refresh();
    return stopPolling;
  }, [active, refresh, stopPolling]);

  const startPolling = useCallback(() => {
    if (!active) return;
    stopPolling();
    intervalRef.current = setInterval(refresh, POLL_INTERVAL_MS);
    timeoutRef.current = setTimeout(stopPolling, POLL_TIMEOUT_MS);
  }, [active, refresh, stopPolling]);

  return { connected, checking, startPolling };
}
