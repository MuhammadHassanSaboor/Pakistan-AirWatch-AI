import { motion } from "framer-motion";
import clsx from "clsx";
import { useEffect, useRef, useState } from "react";

/* ── motion presets ─────────────────────────────────────────
   One easing curve and one set of durations everywhere, so the whole
   interface feels like a single product rather than a pile of widgets. */

export const EASE = [0.22, 1, 0.36, 1];

export const fadeUp = {
  hidden: { opacity: 0, y: 12 },
  show: { opacity: 1, y: 0, transition: { duration: 0.45, ease: EASE } },
};

export const stagger = {
  hidden: {},
  show: { transition: { staggerChildren: 0.06, delayChildren: 0.04 } },
};

export function Panel({ className, children, delay = 0, ...rest }) {
  return (
    <motion.section
      initial={{ opacity: 0, y: 14 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.5, ease: EASE, delay }}
      className={clsx("panel", className)}
      {...rest}
    >
      {children}
    </motion.section>
  );
}

export function PanelHead({ title, icon: Icon, children }) {
  return (
    <header className="panel-head">
      <div className="flex items-center gap-2">
        {Icon ? <Icon size={14} className="text-accent" /> : null}
        <h2 className="panel-title">{title}</h2>
      </div>
      {children ? <div className="flex items-center gap-2">{children}</div> : null}
    </header>
  );
}

/* ── animated number ────────────────────────────────────────
   Counting up reads as "this value is live" far better than a number
   that simply swaps. Respects prefers-reduced-motion via the CSS rule
   in index.css, and snaps instantly for very large jumps. */

export function AnimatedNumber({ value, digits = 1, className }) {
  const [display, setDisplay] = useState(value ?? 0);
  const frame = useRef();
  const from = useRef(value ?? 0);

  useEffect(() => {
    if (value == null) return undefined;
    const start = performance.now();
    const initial = from.current;
    const delta = value - initial;
    const duration = 700;

    if (Math.abs(delta) < 0.01) {
      setDisplay(value);
      from.current = value;
      return undefined;
    }

    const tick = (now) => {
      const t = Math.min((now - start) / duration, 1);
      // easeOutExpo: fast start, gentle settle.
      const eased = t === 1 ? 1 : 1 - Math.pow(2, -10 * t);
      setDisplay(initial + delta * eased);
      if (t < 1) frame.current = requestAnimationFrame(tick);
      else from.current = value;
    };

    frame.current = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame.current);
  }, [value]);

  if (value == null) return <span className={className}>&mdash;</span>;

  return (
    <span className={className}>
      {display.toLocaleString("en-US", {
        minimumFractionDigits: digits,
        maximumFractionDigits: digits,
      })}
    </span>
  );
}

/* ── loading and empty states ───────────────────────────────── */

export function Skeleton({ className }) {
  return <div className={clsx("skeleton", className)} />;
}

export function ErrorState({ error, onRetry, compact = false }) {
  return (
    <div
      className={clsx(
        "flex flex-col items-center justify-center gap-3 text-center",
        compact ? "p-6" : "p-10",
      )}
    >
      <div className="flex h-10 w-10 items-center justify-center rounded-full bg-red-500/10 text-red-400">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <circle cx="12" cy="12" r="10" />
          <path d="M12 8v4M12 16h.01" />
        </svg>
      </div>
      <div>
        <p className="text-sm font-medium text-fg">Could not load this</p>
        <p className="mt-1 max-w-sm text-xs leading-relaxed text-fg-subtle">
          {error?.message ?? "Unexpected error."}
        </p>
      </div>
      {onRetry ? (
        <button type="button" onClick={onRetry} className="btn btn-accent">
          Try again
        </button>
      ) : null}
    </div>
  );
}

export function EmptyState({ title, hint, icon: Icon }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 p-10 text-center">
      {Icon ? <Icon size={22} className="text-fg-faint" /> : null}
      <p className="text-sm font-medium text-fg-muted">{title}</p>
      {hint ? <p className="max-w-xs text-xs text-fg-faint">{hint}</p> : null}
    </div>
  );
}

/* ── provenance badge ───────────────────────────────────────
   Used wherever a number is shown. Making provenance a first-class UI
   element is an explicit requirement, not decoration. */

const TONES = {
  accent: "border-accent/35 bg-accent/12 text-accent",
  blue: "border-sky-400/35 bg-sky-400/12 text-sky-300",
  green: "border-emerald-400/35 bg-emerald-400/12 text-emerald-300",
  slate: "border-line bg-raised text-fg-muted",
};

export function SourceBadge({ label, tone = "slate", title }) {
  return (
    <span
      title={title}
      className={clsx(
        "inline-flex items-center gap-1.5 rounded-md border px-2 py-0.5",
        "text-2xs font-semibold uppercase tracking-wider",
        TONES[tone] ?? TONES.slate,
      )}
    >
      <span className="h-1.5 w-1.5 rounded-full bg-current opacity-80" />
      {label}
    </span>
  );
}
