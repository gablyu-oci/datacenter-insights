import { useState, useEffect, useCallback } from "react";

const API_BASE = import.meta.env.VITE_API_BASE_URL || "";

function getErrorMessage(error: string): { title: string; message: string } {
  if (error.includes("500"))
    return { title: "Server error", message: "The API returned an internal error. Try again in a moment." };
  if (error.includes("404"))
    return { title: "Data not available", message: "This endpoint has not been implemented yet." };
  if (error.includes("501"))
    return { title: "Not yet implemented", message: "This feature is scheduled for a future phase." };
  if (error.includes("Failed to fetch") || error.includes("NetworkError"))
    return { title: "Network error", message: "Could not reach the server. Check your connection." };
  return { title: "Something went wrong", message: error };
}

export function useApi<T>(path: string) {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [errorInfo, setErrorInfo] = useState<{ title: string; message: string } | null>(null);
  const [lastFetchedAt, setLastFetchedAt] = useState<Date | null>(null);
  const [retryCount, setRetryCount] = useState(0);

  const doFetch = useCallback(() => {
    setLoading(true);
    setError(null);
    setErrorInfo(null);
    fetch(`${API_BASE}${path}`)
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then((d) => {
        setData(d);
        setLoading(false);
        setLastFetchedAt(new Date());
      })
      .catch((e) => {
        const msg = e.message || String(e);
        setError(msg);
        setErrorInfo(getErrorMessage(msg));
        setLoading(false);
      });
  }, [path]);

  useEffect(() => {
    doFetch();
  }, [doFetch]);

  const retry = useCallback(() => {
    setRetryCount((c) => c + 1);
    doFetch();
  }, [doFetch]);

  return { data, loading, error, errorInfo, lastFetchedAt, retry, retryCount };
}
