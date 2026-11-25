import { useCallback, useEffect, useRef, useState } from "react";

/**
 * Fetch-on-mount hook with loading, error and refetch.
 *
 * `enabled` lets a caller defer a request until its dependencies are
 * ready, and the mounted ref prevents a state update after unmount
 * (a common React warning when a user clicks away mid-request).
 */
export function useApi(fn, deps = [], { enabled = true } = {}) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(enabled);
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const run = useCallback(async () => {
    if (!enabled) return;
    setLoading(true);
    setError(null);
    try {
      const result = await fn();
      if (mounted.current) setData(result);
    } catch (err) {
      if (mounted.current) setError(err);
    } finally {
      if (mounted.current) setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, ...deps]);

  useEffect(() => {
    run();
  }, [run]);

  return { data, error, loading, refetch: run };
}

/** Re-run a callback on an interval, pausing while the tab is hidden. */
export function usePolling(callback, intervalMs) {
  const saved = useRef(callback);

  useEffect(() => {
    saved.current = callback;
  }, [callback]);

  useEffect(() => {
    if (!intervalMs) return undefined;
    const tick = () => {
      if (document.visibilityState === "visible") saved.current();
    };
    const id = setInterval(tick, intervalMs);
    return () => clearInterval(id);
  }, [intervalMs]);
}
