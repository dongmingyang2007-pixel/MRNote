"use client";

import { useEffect, useState } from "react";
import { Menu, X } from "lucide-react";
import { Link } from "@/i18n/navigation";
import { logout } from "@/lib/api";

interface MobileNavProps {
  openLabel: string;
  closeLabel: string;
  featuresLabel: string;
  pricingLabel: string;
  loginLabel: string;
  startLabel: string;
  loggedIn?: boolean;
  openWorkspaceLabel?: string;
  settingsLabel?: string;
  logoutLabel?: string;
}

export default function MobileNav({
  openLabel,
  closeLabel,
  featuresLabel,
  pricingLabel,
  loginLabel,
  startLabel,
  loggedIn = false,
  openWorkspaceLabel,
  settingsLabel,
  logoutLabel,
}: MobileNavProps) {
  const [open, setOpen] = useState(false);

  useEffect(() => {
    if (open) {
      const previousOverflow = document.body.style.overflow;
      document.body.style.overflow = "hidden";
      return () => {
        document.body.style.overflow = previousOverflow;
      };
    }
    return undefined;
  }, [open]);

  const close = () => setOpen(false);

  return (
    <>
      <button
        type="button"
        className="marketing-header__mobile-toggle"
        aria-expanded={open}
        aria-label={open ? closeLabel : openLabel}
        onClick={() => setOpen((prev) => !prev)}
      >
        {open ? <X size={18} /> : <Menu size={18} />}
      </button>

      {open && (
        <div className="marketing-mobile-panel" role="dialog" aria-modal="true">
          <Link href="/#features" className="marketing-mobile-panel__link" onClick={close}>
            {featuresLabel}
          </Link>
          <Link href="/pricing" className="marketing-mobile-panel__link" onClick={close}>
            {pricingLabel}
          </Link>
          {loggedIn ? (
            <>
              <Link href="/app/settings" className="marketing-mobile-panel__link" onClick={close}>
                {settingsLabel}
              </Link>
              <button
                type="button"
                className="marketing-mobile-panel__link"
                style={{ background: "none", border: "none", textAlign: "left", cursor: "pointer", width: "100%" }}
                onClick={() => {
                  close();
                  void logout();
                }}
              >
                {logoutLabel}
              </button>
              <Link
                href="/app"
                className="marketing-btn marketing-btn--primary marketing-btn--lg"
                style={{ marginTop: 16 }}
                onClick={close}
              >
                {openWorkspaceLabel}
              </Link>
            </>
          ) : (
            <>
              <Link href="/login" className="marketing-mobile-panel__link" onClick={close}>
                {loginLabel}
              </Link>
              <Link
                href="/register"
                className="marketing-btn marketing-btn--primary marketing-btn--lg"
                style={{ marginTop: 16 }}
                onClick={close}
              >
                {startLabel}
              </Link>
            </>
          )}
        </div>
      )}
    </>
  );
}
