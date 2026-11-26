import { useCallback, useEffect, useState } from "react";

const STORAGE_KEY = "airwatch-theme";

/**
 * Theme state with a circular reveal transition.
 *
 * The swap is driven by the View Transitions API: the browser snapshots
 * the old frame, we repaint in the new theme, then animate a clip-path
 * circle growing from the toggle button so the new palette sweeps
 * across the page.
 *
 * Firefox and older Safari have no startViewTransition, so the theme
 * still changes instantly there — the animation is an enhancement, and
 * the app must never depend on it. Same for anyone who has asked for
 * reduced motion.
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
      // this session, which is all that matters.
    }
  }, [theme]);

  // Follow the OS only until the user makes a choice of their own.
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

  /**
   * @param {{x:number,y:number}} [origin] viewport point the circle
   *   grows from — normally the toggle button's centre, so the sweep
   *   visibly starts where the user clicked.
   */
  const toggle = useCallback((origin) => {
    const next = (t) => (t === "dark" ? "light" : "dark");

    const reduced =
      typeof window !== "undefined" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    if (
      reduced ||
      typeof document === "undefined" ||
      !document.startViewTransition
    ) {
      setTheme(next);
      return;
    }

    // Default to the top-right corner when no origin is supplied.
    const x = origin?.x ?? window.innerWidth - 56;
    const y = origin?.y ?? 56;

    // Radius must reach the farthest corner, or the old theme stays
    // visible in the corner the circle never covers.
    const radius = Math.hypot(
      Math.max(x, window.innerWidth - x),
      Math.max(y, window.innerHeight - y),
    );

    const transition = document.startViewTransition(() => {
      // flushSync is unnecessary: React 18 applies this before the
      // transition captures the new frame.
      setTheme(next);
    });

    transition.ready
      .then(() => {
        document.documentElement.animate(
          {
            clipPath: [
              `circle(0px at ${x}px ${y}px)`,
              `circle(${radius}px at ${x}px ${y}px)`,
            ],
          },
          {
            duration: 620,
            easing: "cubic-bezier(0.22, 1, 0.36, 1)",
            pseudoElement: "::view-transition-new(root)",
          },
        );
      })
      .catch(() => {
        // A transition can be skipped (another starts, tab hidden).
        // The theme has already changed, so there is nothing to undo.
      });
  }, []);

  return { theme, setTheme, toggle, isDark: theme === "dark" };
}
