"use client";

import { useEffect } from "react";

/**
 * Sibling of the PublicHeader root that toggles `.is-scrolled` on the
 * parent `<header>` once the viewport has scrolled past 12px. The
 * parent stays a server component — we only hand it a tiny client
 * effect, not a full client tree, so the marketing bundle stays lean.
 */
export default function PublicHeaderScrollState() {
  useEffect(() => {
    const header = document.querySelector(".marketing-header");
    if (!header) return undefined;

    const update = () => {
      if (window.scrollY > 12) {
        header.classList.add("is-scrolled");
      } else {
        header.classList.remove("is-scrolled");
      }
    };

    update();
    window.addEventListener("scroll", update, { passive: true });
    return () => window.removeEventListener("scroll", update);
  }, []);

  return null;
}
