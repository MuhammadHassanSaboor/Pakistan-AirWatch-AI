import { useState } from "react";
import { motion } from "framer-motion";

import { photoUrl } from "../lib/photos";

/**
 * A photograph used as a card backdrop.
 *
 * Three things make the difference between photography that looks
 * designed and photography that looks pasted in:
 *
 *  1. The file is cropped server side to the box it fills, so a 640px
 *     card downloads a 640px image.
 *  2. Text never sits on raw photo. A two-stop scrim keeps the written
 *     side near-opaque and lets the image breathe where nothing is
 *     written, which is why the card still reads as a card.
 *  3. It fades in. A photo that pops in after the layout has settled
 *     is the single clearest sign of a page assembled from parts.
 *
 * The network can always fail, so the image is strictly decorative:
 * on error it is removed and the card falls back to its own surface
 * plus the band tint. Nothing in the card depends on it loading.
 */
export default function PhotoBackdrop({
  photo,
  width = 800,
  height = 400,
  quality = 80,
  /** 0 = scrim only; 1 = full strength. Tunes how loud the image is. */
  strength = 1,
  /** "strong" under unplated text, "soft" under cards that plate it. */
  scrim = "strong",
  /** Slow Ken Burns drift. Off for small decorative corners. */
  pan = true,
  className = "",
}) {
  const [state, setState] = useState("loading");

  if (state === "error" || !photo?.id) {
    return null;
  }

  return (
    <div
      aria-hidden
      className={`pointer-events-none absolute inset-0 overflow-hidden ${className}`}
    >
      <motion.img
        src={photoUrl(photo.id, { w: width, h: height, q: quality })}
        alt=""
        loading="lazy"
        decoding="async"
        draggable={false}
        onLoad={() => setState("ready")}
        onError={() => setState("error")}
        className="h-full w-full object-cover"
        initial={{ opacity: 0, scale: 1.02 }}
        animate={
          state === "ready"
            ? {
                opacity: strength,
                // The drift stays within a few percent. The earlier
                // 1.06-1.12 range enlarged a CDN image already sized
                // for the box, and an upscaled photo looks soft no
                // matter how good the source is.
                scale: pan ? [1, 1.035, 1] : 1,
              }
            : { opacity: 0, scale: 1.02 }
        }
        transition={{
          opacity: { duration: 0.9, ease: "easeOut" },
          scale: pan
            ? { duration: 34, repeat: Infinity, ease: "easeInOut" }
            : { duration: 0.9, ease: "easeOut" },
        }}
      />
      <div
        className="absolute inset-0"
        style={{
          background:
            scrim === "soft" ? "var(--photo-scrim-soft)" : "var(--photo-scrim)",
        }}
      />
    </div>
  );
}
