"use client";

import { Link } from "@/i18n/navigation";
import { useCallback, useEffect, useRef, type MouseEvent, type ReactNode } from "react";

export function MagneticButton({
  children,
  href,
  className = "",
  strength = 0.2,
  onClick,
}: {
  children: ReactNode;
  href?: string;
  className?: string;
  strength?: number;
  onClick?: () => void;
}) {
  const rootRef = useRef<HTMLElement>(null);
  const contentRef = useRef<HTMLSpanElement>(null);
  const frameRef = useRef<number | null>(null);
  const rectRef = useRef<DOMRect | null>(null);

  const commitTransform = useCallback((value: string) => {
    if (frameRef.current !== null) {
      window.cancelAnimationFrame(frameRef.current);
    }
    frameRef.current = window.requestAnimationFrame(() => {
      const el = contentRef.current;
      if (!el) return;
      el.style.transform = value;
      frameRef.current = null;
    });
  }, []);

  useEffect(
    () => () => {
      if (frameRef.current !== null) {
        window.cancelAnimationFrame(frameRef.current);
      }
    },
    [],
  );

  const refreshBounds = useCallback(() => {
    const el = rootRef.current;
    rectRef.current = el ? el.getBoundingClientRect() : null;
  }, []);

  const handleMouseMove = useCallback(
    (e: MouseEvent) => {
      if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
      const rect = rectRef.current ?? rootRef.current?.getBoundingClientRect();
      if (!rect) return;
      const cx = rect.left + rect.width / 2;
      const cy = rect.top + rect.height / 2;
      const dx = (e.clientX - cx) * strength;
      const dy = (e.clientY - cy) * strength;
      commitTransform(`translate(${dx}px, ${dy}px)`);
    },
    [commitTransform, strength],
  );

  const handleMouseEnter = useCallback(() => {
    refreshBounds();
  }, [refreshBounds]);

  const handleMouseLeave = useCallback(() => {
    rectRef.current = null;
    commitTransform("");
  }, [commitTransform]);

  const isInternalHref = Boolean(href?.startsWith("/"));
  const content = <span ref={contentRef} className="magnetic-button-content">{children}</span>;

  if (href && isInternalHref) {
    return (
      <Link
        ref={rootRef as never}
        href={href}
        className={`magnetic-button ${className}`}
        onMouseEnter={handleMouseEnter}
        onMouseMove={handleMouseMove}
        onMouseLeave={handleMouseLeave}
        onClick={onClick}
      >
        {content}
      </Link>
    );
  }

  const Tag = href ? "a" : "button";

  return (
    <Tag
      ref={rootRef as never}
      href={href}
      className={`magnetic-button ${className}`}
      onMouseEnter={handleMouseEnter}
      onMouseMove={handleMouseMove}
      onMouseLeave={handleMouseLeave}
      onClick={onClick}
    >
      {content}
    </Tag>
  );
}
