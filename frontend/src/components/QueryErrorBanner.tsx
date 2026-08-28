import "./QueryErrorBanner.css";

export function queryErrorMessage(error: unknown): string {
  if (error instanceof Error) return error.message;
  if (typeof error === "string") return error;
  return "";
}

export function QueryErrorBanner({
  isError,
  error,
  label = "加载失败",
}: {
  isError: boolean;
  error: unknown;
  label?: string;
}) {
  if (!isError) return null;
  const detail = queryErrorMessage(error);
  return (
    <div className="queryErr" title={detail || undefined}>
      {detail ? `${label}：${detail}` : label}
    </div>
  );
}
