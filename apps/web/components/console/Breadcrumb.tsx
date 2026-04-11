"use client";

import { useMemo } from "react";
import { Link, usePathname } from "@/i18n/navigation";
import { useTranslations } from "next-intl";

function isUUID(s: string): boolean {
  return /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(s);
}

type TranslateFn = ReturnType<typeof useTranslations>;

function formatSegment(
  segment: string,
  previousSegment: string | undefined,
  t: TranslateFn,
  projectNames?: Map<string, string>,
): string {
  const decoded = decodeURIComponent(segment);
  if (decoded === "models" && previousSegment === "discover") {
    return t("discover.models");
  }
  if (projectNames?.has(decoded)) {
    return projectNames.get(decoded) || decoded;
  }
  if (t.has(`breadcrumb.${decoded}`)) {
    return t(`breadcrumb.${decoded}`);
  }
  if (isUUID(decoded)) {
    return `${decoded.slice(0, 8)}\u2026`;
  }
  return decoded;
}

interface BreadcrumbProps {
  projectNames?: Map<string, string>;
  className?: string;
}

export function Breadcrumb({
  projectNames,
  className = "console-topbar-breadcrumb",
}: BreadcrumbProps) {
  const pathname = usePathname();
  const t = useTranslations("console");

  const crumbs = useMemo(() => {
    const segments = pathname.replace(/^\//, "").split("/").filter(Boolean);
    return segments.map((segment, index) => {
      const decoded = decodeURIComponent(segment);
      const previousSegment =
        index > 0 ? decodeURIComponent(segments[index - 1]) : undefined;
      const isVirtualModelsCrumb =
        decoded === "models" && previousSegment === "discover";
      return {
        href: isVirtualModelsCrumb
          ? null
          : `/${segments.slice(0, index + 1).join("/")}`,
        label: formatSegment(segment, previousSegment, t, projectNames),
        isLast: index === segments.length - 1,
      };
    });
  }, [pathname, projectNames, t]);

  return (
    <div className={className} aria-label="Breadcrumb">
      {crumbs.map((crumb, index) => (
        <span key={crumb.href} className="flex items-center">
          {index > 0 && <span className="console-topbar-sep">/</span>}
          {crumb.isLast || !crumb.href ? (
            <span className="console-topbar-crumb is-current">
              {crumb.label}
            </span>
          ) : (
            <Link href={crumb.href} className="console-topbar-crumb">
              {crumb.label}
            </Link>
          )}
        </span>
      ))}
    </div>
  );
}
