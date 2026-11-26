/**
 * Band photography.
 *
 * One photograph per EPA category, chosen so the six form a visible
 * progression: clear alpine air, clear but hazier ranges, ridgelines
 * dissolving into atmosphere, a city under fog, dense smog, then a
 * skyline almost gone. A reader who never looks at the number still
 * learns which end of the scale they are on.
 *
 * All six are hosted on Unsplash's imgix CDN, which is how Unsplash
 * asks images to be served. Every URL below was verified by request
 * before being committed -- each returned HTTP 200, image/jpeg, and
 * between 37 KB and 177 KB at 1200x600 -- rather than assembled from a
 * pattern and hoped for. Photo ids are opaque and cannot be derived
 * from a photo's page slug, so a guessed id is simply a broken image.
 *
 * Sizing is done by the CDN, never by the browser: `w`/`h` crop server
 * side, `auto=format` serves AVIF or WebP to browsers that accept them,
 * and `q` trades a little detail for bytes. A card that needs a 640px
 * backdrop therefore downloads a 640px file, not a 4000px one.
 *
 * The Unsplash License does not require attribution, but crediting a
 * photographer whose work carries your UI costs one line, so the
 * credits are rendered in the footer.
 */

const CDN = "https://images.unsplash.com";

/** Band name -> { id, by, handle, alt } */
export const BAND_PHOTOS = {
  Good: {
    id: "photo-1484334425954-13bfb07a860a",
    by: "Marco Bonomo",
    handle: "radel",
    alt: "Mountain peaks under a clear blue sky",
  },
  Moderate: {
    id: "photo-1769626124735-80cb3bb31ecb",
    by: "Luise and Nic",
    handle: "lui_and_nic",
    alt: "Snow-capped mountains under a bright, clear sky",
  },
  "Unhealthy for Sensitive Groups": {
    id: "photo-1762036705777-a872d9171aa1",
    by: "Pete Alexopoulos",
    handle: "pete_a",
    alt: "Layered mountain ranges fading into atmospheric haze",
  },
  Unhealthy: {
    id: "photo-1649454470283-04e20945f4bf",
    by: "Javier Vinals",
    handle: "jvinals",
    alt: "A city skyline softened by thick fog",
  },
  "Very Unhealthy": {
    id: "photo-1741309695551-18af52f2fd49",
    by: "Alin Gavriliuc",
    handle: "alingavriliuc",
    alt: "A city skyline shrouded in dense smog",
  },
  Hazardous: {
    id: "photo-1755577540839-1daee6d0724c",
    by: "David Kristianto",
    handle: "davidkristianto",
    alt: "A city skyline almost completely obscured by smog and haze",
  },
};

/**
 * Build a CDN URL at exactly the size the element needs.
 *
 * @param {string} id   photo id from BAND_PHOTOS
 * @param {number} w    rendered width in CSS pixels
 * @param {number} h    rendered height in CSS pixels
 * @param {number} q    JPEG/WebP quality, 1-100
 * @param {number} dpr  device pixel ratio to serve for
 */
export function photoUrl(id, { w = 800, h = 400, q = 62, dpr = 2 } = {}) {
  const params = new URLSearchParams({
    auto: "format",
    fit: "crop",
    crop: "entropy", // keep the horizon, not the empty corner
    w: String(Math.round(w * dpr)),
    h: String(Math.round(h * dpr)),
    q: String(q),
  });
  return `${CDN}/${id}?${params.toString()}`;
}

/** The photo for a band, or the cleanest one when the band is unknown. */
export function bandPhoto(bandName) {
  return BAND_PHOTOS[bandName] ?? BAND_PHOTOS.Good;
}

/** Credits for the footer, de-duplicated and in band order. */
export function photoCredits() {
  const seen = new Set();
  return Object.values(BAND_PHOTOS).filter((p) => {
    if (seen.has(p.handle)) return false;
    seen.add(p.handle);
    return true;
  });
}
