"use client";

import { useState, useRef, useEffect } from "react";
import { Rnd } from "react-rnd";
import { MousePointer2 } from "lucide-react";
import { useTranslations } from "next-intl";

import MemoryMock from "./mocks/MemoryMock";
import FollowupMock from "./mocks/FollowupMock";
import DigestMock from "./mocks/DigestMock";

interface WindowSpec {
  id: string;
  x: number;
  y: number;
  component: React.ComponentType<{
    style?: React.CSSProperties;
    decorative?: boolean;
  }>;
}

// Starting layout is tuned for a 1100x520 canvas. We scale down
// proportionally when the container is narrower (mobile).
const INITIAL_LAYOUT: readonly WindowSpec[] = [
  { id: "memory",   x: 40,  y: 60,  component: MemoryMock },
  { id: "followup", x: 420, y: 180, component: FollowupMock },
  { id: "digest",   x: 200, y: 320, component: DigestMock },
] as const;

const WINDOW_WIDTH = 340;

/**
 * Below-the-fold interactive demo — the "it's really a canvas" proof.
 * Each mock is wrapped in react-rnd; drag-only (no resize). Position
 * lives in component state — intentionally not persisted, a fresh
 * visitor should see the same arrangement every load. Windows come
 * forward on click via a monotonic z-index counter.
 *
 * The mocks render as non-decorative (role="group" + aria-label) here
 * because the user is interacting with them — not just looking.
 */
export default function LiveCanvasDemo() {
  const t = useTranslations("marketing");
  const [positions, setPositions] = useState<
    Record<string, { x: number; y: number }>
  >(
    Object.fromEntries(
      INITIAL_LAYOUT.map((w) => [w.id, { x: w.x, y: w.y }]),
    ),
  );
  const [order, setOrder] = useState<string[]>(
    INITIAL_LAYOUT.map((w) => w.id),
  );

  // Scale positions for narrow viewports. Measure the container
  // width once on mount + on window resize.
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [scale, setScale] = useState(1);
  useEffect(() => {
    function update() {
      const el = containerRef.current;
      if (!el) return;
      const w = el.offsetWidth;
      setScale(Math.min(1, w / 1100));
    }
    update();
    window.addEventListener("resize", update);
    return () => window.removeEventListener("resize", update);
  }, []);

  function bringForward(id: string) {
    setOrder((prev) => [...prev.filter((x) => x !== id), id]);
  }

  return (
    <div className="marketing-live-canvas" ref={containerRef}>
      <div className="marketing-live-canvas__hint">
        <MousePointer2 size={14} strokeWidth={2} />
        {t("screenshot.canvas.hint")}
      </div>
      {INITIAL_LAYOUT.map((w) => {
        const Mock = w.component;
        const pos = positions[w.id];
        const z = order.indexOf(w.id) + 1;
        return (
          <Rnd
            key={w.id}
            size={{ width: WINDOW_WIDTH * scale, height: "auto" }}
            position={{ x: pos.x * scale, y: pos.y * scale }}
            onDragStart={() => bringForward(w.id)}
            onDragStop={(_, d) => {
              setPositions((p) => ({
                ...p,
                [w.id]: { x: d.x / scale, y: d.y / scale },
              }));
            }}
            bounds="parent"
            enableResizing={false}
            dragHandleClassName="marketing-mock__titlebar"
            style={{ zIndex: z, cursor: "grab" }}
          >
            <Mock decorative={false} />
          </Rnd>
        );
      })}
    </div>
  );
}
