import { ExternalLink, Github } from "lucide-react";

import { photoCredits } from "../lib/photos";

/**
 * Attribution is a licence condition, not decoration: Open-Meteo,
 * OpenAQ, PAQI and GeoNames are all CC BY, and the free Open-Meteo
 * tier is non-commercial. The disclaimer is here for the same reason
 * it is in the header -- this must never read as official guidance.
 */
export default function Footer({ modelInfo }) {
  return (
    <footer className="mt-auto border-t border-line bg-canvas/60">
      <div className="mx-auto max-w-[1800px] px-4 py-5 sm:px-6">
        <div className="flex flex-wrap items-start justify-between gap-6">
          <div className="max-w-2xl space-y-2">
            <p className="text-xs leading-relaxed text-fg-subtle">
              Air-quality and weather data{" "}
              <a
                href="https://open-meteo.com"
                target="_blank"
                rel="noreferrer noopener"
                className="text-accent hover:underline"
              >
                &copy; Open-Meteo.com
              </a>{" "}
              (CC BY 4.0, non-commercial use). Ground-station observations via{" "}
              <a
                href="https://openaq.org"
                target="_blank"
                rel="noreferrer noopener"
                className="text-accent hover:underline"
              >
                OpenAQ
              </a>{" "}
              and their underlying providers. Pakistan context data &copy;{" "}
              <a
                href="https://pakairquality.hawanama.org"
                target="_blank"
                rel="noreferrer noopener"
                className="text-accent hover:underline"
              >
                PAQI
              </a>{" "}
              (CC BY 4.0). City coordinates &copy; GeoNames (CC BY 4.0). Base
              maps &copy; OpenStreetMap contributors and Esri.
            </p>
            {/* The Unsplash License waives attribution, but a photograph
                carrying the look of the page has earned its credit. */}
            <p className="text-xs leading-relaxed text-fg-subtle">
              Category photography by{" "}
              {photoCredits().map((p, i, all) => (
                <span key={p.handle}>
                  <a
                    href={`https://unsplash.com/@${p.handle}`}
                    target="_blank"
                    rel="noreferrer noopener"
                    className="text-accent hover:underline"
                  >
                    {p.by}
                  </a>
                  {i < all.length - 2
                    ? ", "
                    : i === all.length - 2
                      ? " and "
                      : ""}
                </span>
              ))}{" "}
              on{" "}
              <a
                href="https://unsplash.com/license"
                target="_blank"
                rel="noreferrer noopener"
                className="text-accent hover:underline"
              >
                Unsplash
              </a>
              .
            </p>
            <p className="text-xs leading-relaxed text-fg-faint">
              Pakistan AirWatch AI is a non-commercial academic MLOps project.
              It is <strong className="text-fg-subtle">not</strong> an official
              public-health warning system and does not provide medical advice.
              Forecast accuracy varies by region: cities without nearby
              monitoring stations carry greater uncertainty than the map alone
              can convey.
            </p>
          </div>

          <div className="space-y-2 text-right">
            {modelInfo?.model_version ? (
              <div className="font-mono text-2xs leading-relaxed text-fg-faint">
                <div>
                  model {modelInfo.algorithm} v{modelInfo.model_version}
                </div>
                <div>{modelInfo.n_features} features</div>
                {modelInfo.metrics?.test_mae ? (
                  <div>test MAE {modelInfo.metrics.test_mae} ug/m3</div>
                ) : null}
              </div>
            ) : null}
            <a
              href="https://github.com/MuhammadHassanSaboor/Pakistan-AirWatch-AI"
              target="_blank"
              rel="noreferrer noopener"
              className="inline-flex items-center gap-1.5 text-xs text-fg-subtle transition-colors hover:text-accent"
            >
              <Github size={12} />
              Source
              <ExternalLink size={10} />
            </a>
          </div>
        </div>
      </div>
    </footer>
  );
}
