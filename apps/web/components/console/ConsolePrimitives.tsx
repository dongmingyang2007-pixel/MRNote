import clsx from "clsx";
import type { ReactNode } from "react";

interface ConsoleMetric {
  label: ReactNode;
  value: ReactNode;
}

interface ConsolePageHeaderProps {
  eyebrow?: ReactNode;
  title: ReactNode;
  description?: ReactNode;
  metrics?: ConsoleMetric[];
  actions?: ReactNode;
  className?: string;
}

export function ConsolePageHeader({
  eyebrow,
  title,
  description,
  metrics,
  actions,
  className,
}: ConsolePageHeaderProps) {
  return (
    <header className={clsx("console-page-header-v2", className)}>
      <div className="console-page-header-v2-main">
        {eyebrow ? <p className="console-page-header-v2-eyebrow">{eyebrow}</p> : null}
        <h1 className="console-page-header-v2-title">{title}</h1>
        {description ? (
          <p className="console-page-header-v2-description">{description}</p>
        ) : null}
      </div>

      {metrics?.length ? (
        <div className="console-page-header-v2-metrics">
          {metrics.map((metric, index) => (
            <div key={index} className="console-page-header-v2-metric">
              <span className="console-page-header-v2-metric-value">{metric.value}</span>
              <span className="console-page-header-v2-metric-label">{metric.label}</span>
            </div>
          ))}
        </div>
      ) : null}

      {actions ? <div className="console-page-header-v2-actions">{actions}</div> : null}
    </header>
  );
}

interface ConsoleSectionBlockProps {
  eyebrow?: ReactNode;
  title?: ReactNode;
  description?: ReactNode;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
  headerClassName?: string;
}

export function ConsoleSectionBlock({
  eyebrow,
  title,
  description,
  action,
  children,
  className,
  headerClassName,
}: ConsoleSectionBlockProps) {
  return (
    <section className={clsx("console-section-block", className)}>
      {eyebrow || title || description || action ? (
        <div className={clsx("console-section-block-header", headerClassName)}>
          <div className="console-section-block-copy">
            {eyebrow ? (
              <p className="console-section-block-eyebrow">{eyebrow}</p>
            ) : null}
            {title ? <h2 className="console-section-block-title">{title}</h2> : null}
            {description ? (
              <p className="console-section-block-description">{description}</p>
            ) : null}
          </div>
          {action ? <div className="console-section-block-action">{action}</div> : null}
        </div>
      ) : null}

      <div className="console-section-block-body">{children}</div>
    </section>
  );
}

interface ConsoleRailListProps {
  title?: ReactNode;
  description?: ReactNode;
  footer?: ReactNode;
  children: ReactNode;
  className?: string;
}

export function ConsoleRailList({
  title,
  description,
  footer,
  children,
  className,
}: ConsoleRailListProps) {
  return (
    <aside className={clsx("console-rail-list", className)}>
      {title || description ? (
        <div className="console-rail-list-header">
          {title ? <h2 className="console-rail-list-title">{title}</h2> : null}
          {description ? (
            <p className="console-rail-list-description">{description}</p>
          ) : null}
        </div>
      ) : null}

      <div className="console-rail-list-body">{children}</div>

      {footer ? <div className="console-rail-list-footer">{footer}</div> : null}
    </aside>
  );
}

interface ConsoleInspectorPanelProps {
  title?: ReactNode;
  description?: ReactNode;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
}

export function ConsoleInspectorPanel({
  title,
  description,
  action,
  children,
  className,
}: ConsoleInspectorPanelProps) {
  return (
    <aside className={clsx("console-inspector-panel", className)}>
      {title || description || action ? (
        <div className="console-inspector-panel-header">
          <div>
            {title ? <h2 className="console-inspector-panel-title">{title}</h2> : null}
            {description ? (
              <p className="console-inspector-panel-description">{description}</p>
            ) : null}
          </div>
          {action ? <div className="console-inspector-panel-action">{action}</div> : null}
        </div>
      ) : null}

      <div className="console-inspector-panel-body">{children}</div>
    </aside>
  );
}

interface ConsoleEmptyStateProps {
  title: ReactNode;
  description?: ReactNode;
  action?: ReactNode;
  icon?: ReactNode;
  className?: string;
}

export function ConsoleEmptyState({
  title,
  description,
  action,
  icon,
  className,
}: ConsoleEmptyStateProps) {
  return (
    <div className={clsx("console-empty-state", className)}>
      {icon ? <div className="console-empty-state-icon">{icon}</div> : null}
      <div className="console-empty-state-copy">
        <div className="console-empty-state-title">{title}</div>
        {description ? (
          <p className="console-empty-state-description">{description}</p>
        ) : null}
      </div>
      {action ? <div className="console-empty-state-action">{action}</div> : null}
    </div>
  );
}
