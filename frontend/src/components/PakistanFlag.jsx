/**
 * The flag of Pakistan, drawn to its official specification.
 *
 * Built as SVG rather than fetched as an image for the same reasons
 * the AQI scenes are: it is crisp at 20px and at 200px, needs no
 * network request, and cannot arrive half a second after the header
 * has painted. It also means the proportions are right rather than
 * whatever a stock photo happened to crop to.
 *
 * Specification (Pakistan Flag Resolution, 1947):
 *   - ratio 3:2
 *   - a white hoist bar occupying one quarter of the width
 *   - dark green field, #01411C
 *   - a white crescent and five-pointed star centred on the green
 *
 * The crescent is drawn the way it is actually defined -- a circle
 * with a second, smaller circle cut out of it and offset -- rather
 * than as a hand-drawn arc, so the horns taper correctly instead of
 * ending bluntly.
 */
export default function PakistanFlag({
  width = 30,
  className = "",
  wave = true,
}) {
  const height = (width * 2) / 3;
  const uid = `pk-flag-${width}`;

  return (
    <svg
      width={width}
      height={height}
      viewBox="0 0 900 600"
      role="img"
      aria-label="Flag of Pakistan"
      className={`shrink-0 overflow-hidden rounded-[3px] ${
        wave ? "flag-wave" : ""
      } ${className}`}
      style={{ boxShadow: "0 1px 3px rgb(0 0 0 / 0.35)" }}
    >
      <defs>
        {/* The crescent: a disc with an offset disc removed. */}
        <mask id={`${uid}-crescent`}>
          <rect width="900" height="600" fill="black" />
          <circle cx="520" cy="300" r="165" fill="white" />
          <circle cx="585" cy="255" r="150" fill="black" />
        </mask>
      </defs>

      {/* dark green field */}
      <rect width="900" height="600" fill="#01411C" />
      {/* white hoist bar, one quarter of the width */}
      <rect width="225" height="600" fill="#FFFFFF" />

      <g fill="#FFFFFF">
        <circle cx="520" cy="300" r="165" mask={`url(#${uid}-crescent)`} />
        {/* five-pointed star, rotated so one point faces the hoist */}
        <g transform="translate(639 210) rotate(-45) scale(2.15)">
          <path d="M0 -32 L9.4 -9.9 L33 -6.9 L15.4 9.3 L20.2 32 L0 20.4 L-20.2 32 L-15.4 9.3 L-33 -6.9 L-9.4 -9.9 Z" />
        </g>
      </g>
    </svg>
  );
}
