import { ExternalLink, Github } from "lucide-react";

import { photoCredits } from "../lib/photos";

/**
 * A single compact credit line.
 *
 * The long disclaimer and the paragraph of source notes were removed at
 * the owner's request. What remains is only what the licences actually
 * oblige: Open-Meteo, PAQI and GeoNames are all CC BY 4.0, which grants
 * the right to use the data *on condition* that the source is credited,
 * and the Open-Meteo free tier is non-commercial. Dropping these names
 * would not be a style choice, it would end the permission the project
 * relies on, so they are kept -- at one line, in the quietest type on
 * the page.
 */
function Credit({ href, children }) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noreferrer noopener"
      className="text-fg-subtle transition-colors hover:text-accent hover:underline"
    >
      {children}
    </a>
  );
}

export default function Footer({ modelInfo }) {
  const photographers = photoCredits()
    .map((p) => p.by)
    .join(", ");

  return (
    <footer className="mt-auto border-t border-line">
      <div
        className="mx-auto flex max-w-[1680px] flex-wrap items-center justify-between
                   gap-x-6 gap-y-2 px-4 py-3.5 text-2xs text-fg-faint sm:px-6"
      >
        <p className="leading-relaxed">
          Data <Credit href="https://open-meteo.com">Open-Meteo</Credit>,{" "}
          <Credit href="https://openaq.org">OpenAQ</Credit>,{" "}
          <Credit href="https://pakairquality.hawanama.org">PAQI</Credit>,
          GeoNames &middot; CC BY 4.0, non-commercial &middot; maps &copy;
          OpenStreetMap and Esri &middot; photos{" "}
          <Credit href="https://unsplash.com/license">{photographers}</Credit>
        </p>

        <div className="flex items-center gap-4">
          {modelInfo?.model_version ? (
            <span className="font-mono">
              {modelInfo.algorithm} v{modelInfo.model_version}
              {modelInfo.metrics?.test_mae
                ? ` · MAE ${modelInfo.metrics.test_mae}`
                : ""}
            </span>
          ) : null}
          <a
            href="https://github.com/MuhammadHassanSaboor/Pakistan-AirWatch-AI"
            target="_blank"
            rel="noreferrer noopener"
            className="inline-flex items-center gap-1.5 transition-colors hover:text-accent"
          >
            <Github size={12} />
            Source
            <ExternalLink size={9} />
          </a>
        </div>
      </div>
    </footer>
  );
}
