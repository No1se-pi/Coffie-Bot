import type { ButtonHTMLAttributes, HTMLAttributes, ReactNode } from "react";
import { ApiError } from "../api/client";
import { initials } from "../utils/format";

export function Page({
  title,
  eyebrow,
  action,
  children,
}: {
  title: string;
  eyebrow?: string;
  action?: ReactNode;
  children: ReactNode;
}) {
  return (
    <main className="page">
      <header className="page__header">
        <div>
          {eyebrow && <p className="eyebrow">{eyebrow}</p>}
          <h1>{title}</h1>
        </div>
        {action}
      </header>
      {children}
    </main>
  );
}

export function Panel({
  className = "",
  children,
  ...props
}: HTMLAttributes<HTMLElement>) {
  return (
    <section className={`panel ${className}`.trim()} {...props}>
      {children}
    </section>
  );
}

export function Button({
  variant = "primary",
  className = "",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "ghost" | "danger";
}) {
  return (
    <button
      className={`button button--${variant} ${className}`.trim()}
      {...props}
    />
  );
}

export function Badge({
  tone = "neutral",
  children,
}: {
  tone?: "neutral" | "success" | "warning" | "danger" | "accent";
  children: ReactNode;
}) {
  return <span className={`badge badge--${tone}`}>{children}</span>;
}

export function Avatar({
  name,
  src,
  size = "normal",
}: {
  name: string;
  src?: string | null;
  size?: "small" | "normal" | "large";
}) {
  return src ? (
    <img className={`avatar avatar--${size}`} src={src} alt="" />
  ) : (
    <span className={`avatar avatar--${size}`} aria-hidden="true">
      {initials(name)}
    </span>
  );
}

export function Loader({ label = "Загружаем данные…" }: { label?: string }) {
  return (
    <div className="state" role="status" aria-live="polite">
      <span className="loader" aria-hidden="true" />
      <p>{label}</p>
    </div>
  );
}

export function EmptyState({
  title,
  text,
  action,
}: {
  title: string;
  text: string;
  action?: ReactNode;
}) {
  return (
    <div className="state state--card">
      <span className="state__icon" aria-hidden="true">
        ☕
      </span>
      <h2>{title}</h2>
      <p>{text}</p>
      {action}
    </div>
  );
}

export function ErrorState({
  error,
  onRetry,
  compact = false,
}: {
  error: Error;
  onRetry?: () => void;
  compact?: boolean;
}) {
  const requestId = error instanceof ApiError ? error.requestId : undefined;
  return (
    <div
      className={`state state--error ${compact ? "state--compact" : ""}`}
      role="alert"
    >
      <span className="state__icon" aria-hidden="true">
        !
      </span>
      <h2>Что-то пошло не так</h2>
      <p>{error.message}</p>
      {requestId && <p className="muted">Код обращения: {requestId}</p>}
      {onRetry && (
        <Button variant="secondary" onClick={onRetry}>
          Попробовать снова
        </Button>
      )}
    </div>
  );
}

export function Progress({
  value,
  max,
  label,
}: {
  value: number;
  max: number;
  label: string;
}) {
  const safeMax = Math.max(max, 1);
  const percent = Math.min(100, Math.max(0, (value / safeMax) * 100));
  return (
    <div className="progress-group">
      <div className="progress-group__label">
        <span>{label}</span>
        <strong>
          {value} из {max}
        </strong>
      </div>
      <div
        className="progress"
        role="progressbar"
        aria-label={label}
        aria-valuemin={0}
        aria-valuemax={max}
        aria-valuenow={value}
      >
        <span style={{ width: `${percent}%` }} />
      </div>
    </div>
  );
}

export function Metric({
  value,
  label,
  tone,
}: {
  value: ReactNode;
  label: string;
  tone?: "accent" | "warning";
}) {
  return (
    <div className={`metric ${tone ? `metric--${tone}` : ""}`}>
      <strong>{value}</strong>
      <span>{label}</span>
    </div>
  );
}

export function Field({
  label,
  hint,
  error,
  children,
}: {
  label: string;
  hint?: string;
  error?: string;
  children: ReactNode;
}) {
  return (
    <div className="field">
      <label className="field__control">
        <span className="field__label">{label}</span>
        {children}
      </label>
      {hint && <span className="field__hint">{hint}</span>}
      {error && <span className="field__error">{error}</span>}
    </div>
  );
}
