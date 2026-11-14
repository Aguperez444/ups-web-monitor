export async function proxyUps(path: string) {
  const backend = (process.env.UPS_API_URL || "http://127.0.0.1:5601").replace(/\/+$/, "");
  const headers = { "Cache-Control": "no-store" };

  try {
    const response = await fetch(`${backend}${path}`, {
      cache: "no-store",
      headers: { Accept: "application/json" },
      signal: AbortSignal.timeout(5000),
    });
    const data = await response.json();
    return Response.json(data, { status: response.status, headers });
  } catch (error) {
    const timedOut = error instanceof Error && error.name === "TimeoutError";
    return Response.json(
      {
        detail: timedOut
          ? "El servicio del UPS tardó demasiado en responder."
          : "No se pudo consultar el servicio del UPS. Verificá que el backend esté encendido y su dirección configurada correctamente.",
      },
      { status: timedOut ? 504 : 502, headers },
    );
  }
}
