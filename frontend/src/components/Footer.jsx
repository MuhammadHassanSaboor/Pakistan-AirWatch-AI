import { ExternalLink, Github } from "lucide-react";

/**
 * Attribution is a licence condition, not decoration: Open-Meteo,
 * OpenAQ, PAQI and GeoNames are all CC BY, and the free Open-Meteo
 * tier is non-commercial. The disclaimer is here for the same reason
 * it is in the header -- this must never read as official guidance.
 */
export default function Footer({ modelInfo }) {
  return (
    <footer className="mt-auto border-t border-white/[0.06] bg-ink-950/60">
      <div className="mx-auto max-w-[1800px] px-4 py-5 sm:px-6">
        <div className="flex flex-wrap items-start justify-between gap-6">
          <div className="max-w-2xl space-y-2">
            <p className="text-[11px] leading-relaxed text-ink-400">
              Air-quality and weather data{" "}
              <a
                href="https://open-meteo.com"
                target="_blank"
                rel="noreferrer noopener"
                className="text-accent-soft hover:underline"
              >
                &copy; Open-Meteo.com
              </a>{" "}
              (CC BY 4.0, non-commercial use). Ground-station observations via{" "}
              <a
                href="https://openaq.org"
                target="_blank"
                rel="noreferrer noopener"
                className="text-accent-soft hover:underline"
              >
                OpenAQ
              </a>{" "}
              and their underlying providers. Pakistan context data &copy;{" "}
              <a
                href="https://pakairquality.hawanama.org"
                target="_blank"
                rel="noreferrer noopener"
                className="text-accent-soft hover:underline"
              >
                PAQI
              </a>{" "}
              (CC BY 4.0). City coordinates &copy; GeoNames (CC BY 4.0). Base map
              &copy; OpenStreetMap contributors, &copy; CARTO.
            </p>
            <p className="text-[11px] leading-relaxed text-ink-500">
              Pakistan AirWatch AI is a non-commercial academic MLOps project. It
              is <strong className="text-ink-400">not</strong> an official
              public-health warning system and does not provide medical advice.
              Forecast accuracy varies by region: cities without nearby
              monitoring stations carry greater uncertainty than the map alone
              can convey.
            </p>
          </div>

          <div className="space-y-2 text-right">
            {modelInfo?.model_version ? (
              <div className="font-mono text-[10px] leading-relaxed text-ink-500">
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
              className="inline-flex items-center gap-1.5 text-[11px] text-ink-400 transition-colors hover:text-accent-soft"
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
