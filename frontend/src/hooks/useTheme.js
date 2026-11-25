import { useCallback, useEffect, useState } from "react";

const STORAGE_KEY = "airwatch-theme";

/**
 * Theme state, persisted and applied to <html data-theme>.
 *
 * Honours the OS preference on first visit, then remembers whatever
 * the user chose. The attribute is also set synchronously in
 * index.html before paint, so the page never flashes the wrong theme.
 */
export function useTheme() {
  const [theme, setTheme] = useState(() => {
    if (typeof document === "undefined") return "dark";
    return document.documentElement.dataset.theme || "dark";
  });

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try {
      localStorage.setItem(STORAGE_KEY, theme);
    } catch {
      // Private browsing blocks storage; the theme still applies for
      // this session, which is all we need.
    }
  }, [theme]);

  // Follow the OS only while the user has not made a choice.
  useEffect(() => {
    let stored = null;
    try {
      stored = localStorage.getItem(STORAGE_KEY);
    } catch {
      stored = null;
    }
    if (stored) return undefined;

    const mq = window.matchMedia("(prefers-color-scheme: light)");
    const onChange = (e) => setTheme(e.matches ? "light" : "dark");
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);

  const toggle = useCallback(
    () => setTheme((t) => (t === "dark" ? "light" : "dark")),
    [],
  );

  return { theme, setTheme, toggle, isDark: theme === "dark" };
}
