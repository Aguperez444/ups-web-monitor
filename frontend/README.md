# Dashboard UPS Monitor

Dashboard Next.js con vistas de flujo eléctrico, información e historial. La lectura actual se consulta dos segundos después de cada respuesta. Si NUT deja de responder, el dashboard marca la última lectura como desactualizada. Los gráficos de intervalos relativos se actualizan cada diez segundos mientras la vista está abierta.

## Ejecutar

Iniciá primero el [backend](../backend/README.md). Desde `frontend/`:

```sh
npm ci
npm run dev
```

Abrí el dashboard en el puerto `3000`. Copiá `.env.example` a `.env.local` y modificá `UPS_API_URL` si tu backend usa otro host o puerto. La dirección se interpreta desde el servidor de Next.js.

El navegador consulta `/api/ups/current` y `/api/metrics` en el mismo origen. El proxy de Next.js mantiene `/api/ups/summary` para compatibilidad, reenvía las consultas sin caché y devuelve el código HTTP y detalle JSON del backend. Un 502 indica que el backend no respondió correctamente y un 504 indica tiempo de espera vencido.

Los gráficos de Chart.js usan las muestras y los timestamps que devuelve la API. El selector solicita al backend el intervalo elegido. El eje y los tooltips muestran la hora local del navegador. En un gráfico enfocado podés usar las flechas izquierda y derecha para consultar muestras con el teclado.

## Verificación

```sh
npm run lint
npm test
npx tsc --noEmit
npm run build
```

Si el entorno restringe los sockets internos de Turbopack, podés compilar con `npm run build -- --webpack`.
