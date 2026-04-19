import { CanvasTexture, Sprite, SpriteMaterial } from "three";
import type { GraphNode } from "../types";
import { ROLE_STYLE } from "../constants";
import {
  CARD_W, CARD_H, CARD_WORLD_W, CARD_WORLD_H, ROLE_GLYPH,
} from "./constants3d";

export function cardCacheKey(n: GraphNode): string {
  return `${n.id}:${n.role}:${n.conf.toFixed(2)}:${n.reuse}:${n.pinned ? 1 : 0}`;
}

function roundRect(ctx: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, r: number): void {
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.lineTo(x + w - r, y); ctx.quadraticCurveTo(x + w, y, x + w, y + r);
  ctx.lineTo(x + w, y + h - r); ctx.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
  ctx.lineTo(x + r, y + h); ctx.quadraticCurveTo(x, y + h, x, y + h - r);
  ctx.lineTo(x, y + r); ctx.quadraticCurveTo(x, y, x + r, y);
  ctx.closePath();
}

export function makeNodeCard(n: GraphNode): Sprite {
  const cfg = ROLE_STYLE[n.role];
  const c = document.createElement("canvas");
  c.width = CARD_W * 2;
  c.height = CARD_H * 2;
  const ctx = c.getContext("2d")!;
  ctx.scale(2, 2);

  const g = ctx.createLinearGradient(0, 0, 0, CARD_H);
  g.addColorStop(0, "rgba(255,255,255,0.96)");
  g.addColorStop(1, "rgba(245,250,252,0.90)");
  ctx.fillStyle = g;
  roundRect(ctx, 4, 4, CARD_W - 8, CARD_H - 8, 16);
  ctx.fill();

  const corner = ctx.createRadialGradient(CARD_W - 30, 30, 4, CARD_W - 30, 30, 140);
  corner.addColorStop(0, cfg.fill);
  corner.addColorStop(1, cfg.fill + "00");
  ctx.fillStyle = corner;
  roundRect(ctx, 4, 4, CARD_W - 8, CARD_H - 8, 16);
  ctx.fill();

  ctx.strokeStyle = "rgba(15,42,45,0.09)";
  ctx.lineWidth = 1;
  roundRect(ctx, 4.5, 4.5, CARD_W - 9, CARD_H - 9, 15.5);
  ctx.stroke();

  ctx.fillStyle = cfg.stroke;
  roundRect(ctx, 18, 18, 84, 24, 12);
  ctx.fill();
  ctx.fillStyle = "#fff";
  ctx.font = '600 13px "Plus Jakarta Sans", system-ui, sans-serif';
  ctx.textBaseline = "middle";
  ctx.fillText(`${ROLE_GLYPH[n.role]}  ${n.role}`, 28, 30);

  if (n.reuse) {
    ctx.fillStyle = "rgba(15,42,45,0.06)";
    roundRect(ctx, CARD_W - 70, 18, 50, 24, 12);
    ctx.fill();
    ctx.fillStyle = "#0f2a2d";
    ctx.font = '600 12px "Plus Jakarta Sans", system-ui, sans-serif';
    ctx.fillText(`×${n.reuse}`, CARD_W - 60, 30);
  }

  if (n.pinned) {
    ctx.fillStyle = "#f97316";
    ctx.beginPath();
    ctx.arc(CARD_W - 88, 30, 4, 0, Math.PI * 2);
    ctx.fill();
  }

  ctx.fillStyle = "#0f172a";
  ctx.font = '700 18px "Plus Jakarta Sans", system-ui, sans-serif';
  const label = n.label || "(untitled)";
  const chars = [...label];
  const lines: string[] = [];
  let line = "";
  const maxW = CARD_W - 40;
  for (const ch of chars) {
    const test = line + ch;
    if (ctx.measureText(test).width > maxW && line) {
      lines.push(line);
      line = ch;
      if (lines.length === 2) break;
    } else {
      line = test;
    }
  }
  if (lines.length < 2 && line) lines.push(line);
  lines.slice(0, 2).forEach((ln, i) => ctx.fillText(ln, 18, 64 + i * 24));

  ctx.fillStyle = "#64748b";
  ctx.font = '500 12px "Plus Jakarta Sans", system-ui, sans-serif';
  const summary = (n.raw?.content ?? "").trim();
  let sm = summary, smaxW = CARD_W - 36;
  while (ctx.measureText(sm + "…").width > smaxW && sm.length > 1) sm = sm.slice(0, -1);
  ctx.fillText(sm + (sm.length < summary.length ? "…" : ""), 18, 120);

  const cx = 38, cy = CARD_H - 34, rr = 16;
  ctx.strokeStyle = "rgba(15,42,45,0.08)";
  ctx.lineWidth = 4;
  ctx.beginPath();
  ctx.arc(cx, cy, rr, Math.PI * 0.75, Math.PI * 2.25);
  ctx.stroke();
  ctx.strokeStyle = cfg.stroke;
  ctx.lineCap = "round";
  ctx.beginPath();
  ctx.arc(cx, cy, rr, Math.PI * 0.75, Math.PI * 0.75 + Math.PI * 1.5 * (n.conf || 0.8));
  ctx.stroke();
  ctx.fillStyle = cfg.text;
  ctx.font = '700 11px "Plus Jakarta Sans", system-ui, sans-serif';
  ctx.textAlign = "center";
  ctx.fillText((n.conf || 0).toFixed(2), cx, cy + 4);
  ctx.textAlign = "left";
  ctx.lineCap = "butt";

  ctx.fillStyle = "#475569";
  ctx.font = '500 11px "JetBrains Mono", monospace';
  ctx.textAlign = "right";
  ctx.fillText(n.source || "—", CARD_W - 18, CARD_H - 28);
  ctx.fillStyle = "#94a3b8";
  ctx.fillText(n.lastUsed ? `${n.lastUsed} ago` : "—", CARD_W - 18, CARD_H - 14);
  ctx.textAlign = "left";

  const texture = new CanvasTexture(c);
  texture.needsUpdate = true;
  const material = new SpriteMaterial({
    map: texture, transparent: true, depthWrite: false, opacity: 1.0,
  });
  const sprite = new Sprite(material);
  sprite.scale.set(CARD_WORLD_W, CARD_WORLD_H, 1);
  sprite.userData.cacheKey = cardCacheKey(n);
  return sprite;
}
