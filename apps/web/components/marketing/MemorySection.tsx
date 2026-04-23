import { getTranslations } from "next-intl/server";

/**
 * MemorySection — dark memory-graph section (mirrors `.memory` in MRNote
 * prototype `sections.css`). Two-column layout:
 *
 *   Left  — eyebrow + headline + lead + 3 stats
 *   Right — aspect-ratio graph canvas with 8 pill "nodes" arranged on a
 *           circle around a pulsing root node, plus SVG edges connecting
 *           each satellite to the root. One root node uses teal bg + white
 *           text; satellites are translucent teal pills.
 *
 * Animations are purely CSS-driven (`marketing-memory-pulse`) so the
 * component stays a Server Component with zero client JS. A
 * `@media (prefers-reduced-motion: reduce)` block in marketing.css
 * suppresses the pulse when the user asks for less motion.
 */

// Satellite nodes arranged roughly on a circle of radius 38% around the
// root (center). 7 satellites + 1 root = 8 total pills. The `labelKey`
// points at `memorySection.node.<id>` in marketing.json so zh/en copy can
// diverge. `icon` is a single emoji glyph for zero-dep visual anchoring
// (we avoid loading another icon set for this one section).
type Node = {
  id: "root" | "pages" | "ai" | "study" | "files" | "flashcard" | "digest" | "evidence";
  labelKey: string;
  // percent positions inside the graph container (0–100)
  x: number;
  y: number;
  icon: string;
  variant?: "root" | "accent";
  // animation delay so pulses don't fire in lockstep
  delay: string;
};

const NODES: Node[] = [
  { id: "root", labelKey: "memorySection.node.root", x: 50, y: 50, icon: "◆", variant: "root", delay: "0s" },
  { id: "pages", labelKey: "memorySection.node.pages", x: 22, y: 22, icon: "▤", delay: "0.2s" },
  { id: "ai", labelKey: "memorySection.node.ai", x: 78, y: 20, icon: "✦", delay: "0.4s" },
  { id: "study", labelKey: "memorySection.node.study", x: 18, y: 72, icon: "❖", delay: "0.6s" },
  { id: "files", labelKey: "memorySection.node.files", x: 84, y: 54, icon: "◇", delay: "0.8s" },
  { id: "flashcard", labelKey: "memorySection.node.flashcard", x: 72, y: 86, icon: "▲", variant: "accent", delay: "1.0s" },
  { id: "evidence", labelKey: "memorySection.node.evidence", x: 32, y: 88, icon: "●", variant: "accent", delay: "1.2s" },
  { id: "digest", labelKey: "memorySection.node.digest", x: 52, y: 10, icon: "◐", delay: "1.4s" },
];

// Every satellite is connected to the root, plus a handful of lateral
// edges to make the graph feel woven rather than star-shaped.
const EDGES: Array<[Node["id"], Node["id"]]> = [
  ["root", "pages"],
  ["root", "ai"],
  ["root", "study"],
  ["root", "files"],
  ["root", "flashcard"],
  ["root", "evidence"],
  ["root", "digest"],
  ["pages", "ai"],
  ["study", "flashcard"],
  ["files", "ai"],
  ["evidence", "study"],
];

const STAT_KEYS = ["a", "b", "c"] as const;

export default async function MemorySection() {
  const t = await getTranslations("marketing");
  const nodeById = Object.fromEntries(NODES.map((n) => [n.id, n]));

  return (
    <section className="marketing-memory" id="memory">
      <div className="marketing-memory__inner">
        <div className="marketing-memory__copy">
          <span className="marketing-eyebrow marketing-memory__eyebrow">
            {t("memorySection.eyebrow")}
          </span>
          <h2 className="marketing-h2 marketing-memory__title">
            {t("memorySection.title")}
          </h2>
          <p className="marketing-memory__lead">{t("memorySection.lead")}</p>

          <dl className="marketing-memory__stats">
            {STAT_KEYS.map((k) => (
              <div key={k} className="marketing-memory__stat">
                <dt className="marketing-memory__stat-num">
                  {t(`memorySection.stats.${k}.num`)}
                </dt>
                <dd className="marketing-memory__stat-label">
                  {t(`memorySection.stats.${k}.label`)}
                </dd>
              </div>
            ))}
          </dl>
        </div>

        <div
          className="marketing-memory__graph"
          role="img"
          aria-label={t("memorySection.graphAria")}
        >
          <svg
            className="marketing-memory__graph-svg"
            viewBox="0 0 100 100"
            preserveAspectRatio="none"
            aria-hidden="true"
          >
            <defs>
              <radialGradient id="marketing-memory-pulse-gradient">
                <stop offset="0%" stopColor="#14B8A6" stopOpacity="0.45" />
                <stop offset="100%" stopColor="#14B8A6" stopOpacity="0" />
              </radialGradient>
            </defs>
            <circle cx="50" cy="50" r="26" fill="url(#marketing-memory-pulse-gradient)">
              <animate
                attributeName="r"
                values="22;34;22"
                dur="4s"
                repeatCount="indefinite"
              />
              <animate
                attributeName="opacity"
                values="0.55;0.15;0.55"
                dur="4s"
                repeatCount="indefinite"
              />
            </circle>
            {EDGES.map(([a, b], i) => {
              const na = nodeById[a];
              const nb = nodeById[b];
              return (
                <line
                  key={i}
                  x1={na.x}
                  y1={na.y}
                  x2={nb.x}
                  y2={nb.y}
                  stroke="#14B8A6"
                  strokeWidth="0.2"
                  strokeOpacity="0.4"
                  strokeDasharray="0.8 0.6"
                />
              );
            })}
          </svg>

          {NODES.map((n) => {
            const modifier =
              n.variant === "root"
                ? "marketing-memory-node--root"
                : n.variant === "accent"
                  ? "marketing-memory-node--accent"
                  : "";
            return (
              <span
                key={n.id}
                className={`marketing-memory-node ${modifier}`}
                style={{
                  left: `${n.x}%`,
                  top: `${n.y}%`,
                  animationDelay: n.delay,
                }}
              >
                <span className="marketing-memory-node__icon" aria-hidden="true">
                  {n.icon}
                </span>
                <span>{t(n.labelKey)}</span>
              </span>
            );
          })}
        </div>
      </div>
    </section>
  );
}
