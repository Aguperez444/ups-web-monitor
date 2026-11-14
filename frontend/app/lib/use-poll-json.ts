"use client";

import { useEffect, useState } from "react";

interface PollState<T> {
  url: string;
  data: T | null;
  error: string | null;
}

export function usePollJson<T>(url: string | null, interval: number) {
  const [state, setState] = useState<PollState<T> | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    if (!url) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;

    async function poll(requestUrl: string) {
      try {
        const response = await fetch(requestUrl, {
          cache: "no-store",
          signal: AbortSignal.any([controller.signal, AbortSignal.timeout(10000)]),
        });
        const json = await response.json();
        if (!response.ok) {
          throw new Error(typeof json?.detail === "string"
            ? json.detail
            : `La consulta falló (HTTP ${response.status}).`);
        }
        if (!controller.signal.aborted) {
          setState({ url: requestUrl, data: json as T, error: null });
        }
      } catch (error) {
        if (!controller.signal.aborted) {
          setState(previous => ({
            url: requestUrl,
            data: previous?.url === requestUrl ? previous.data : null,
            error: error instanceof Error && error.name !== "TypeError" && error.name !== "TimeoutError"
              ? error.message
              : "No se pudo obtener una respuesta del servicio del UPS.",
          }));
        }
      } finally {
        if (!controller.signal.aborted && interval > 0) {
          timer = setTimeout(() => void poll(requestUrl), interval);
        }
      }
    }

    void poll(url);
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [url, interval, attempt]);

  const result = state?.url === url ? state : null;
  return {
    data: result?.data ?? null,
    error: result?.error ?? null,
    loading: url !== null && !result,
    retry: () => setAttempt(previous => previous + 1),
  };
}
