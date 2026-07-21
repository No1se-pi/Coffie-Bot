import { useCallback, useEffect, useRef, useState } from "react";

export interface ResourceState<T> {
  data: T | null;
  loading: boolean;
  error: Error | null;
  reload: () => Promise<void>;
}

export function useResource<T>(
  loader: () => Promise<T>,
  dependencies: readonly unknown[] = [],
): ResourceState<T> {
  const loaderRef = useRef(loader);
  loaderRef.current = loader;
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);

  const reload = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setData(await loaderRef.current());
    } catch (reason) {
      setError(
        reason instanceof Error ? reason : new Error("Неизвестная ошибка"),
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void reload();
    // The caller controls reload boundaries with explicit dependency values.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [reload, ...dependencies]);

  return { data, loading, error, reload };
}
