import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { afterEach, test } from "node:test";
import ts from "typescript";

// Compile the actual handlers without starting Next.js or requiring a live UPS.
function asModule(source) {
    const { outputText } = ts.transpileModule(source, {
        compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 },
    });
    return `data:text/javascript;base64,${Buffer.from(outputText).toString("base64")}`;
}

const proxyModule = asModule(await readFile(new URL("../app/lib/ups-proxy.ts", import.meta.url), "utf8"));

async function loadGet(route) {
    const source = await readFile(new URL(`../app/api/${route}/route.ts`, import.meta.url), "utf8");
    return (await import(asModule(source.replace("@/app/lib/ups-proxy", proxyModule)))).GET;
}

const [GET, getCurrent, getMetrics] = await Promise.all([
    loadGet("ups/summary"), loadGet("ups/current"), loadGet("metrics"),
]);

const originalFetch = globalThis.fetch;
const originalUrl = process.env.UPS_API_URL;

afterEach(() => {
    globalThis.fetch = originalFetch;
    if (originalUrl === undefined) delete process.env.UPS_API_URL;
    else process.env.UPS_API_URL = originalUrl;
});

test("returns the UPS summary without caching using the default backend", async () => {
    delete process.env.UPS_API_URL;
    const summary = { status: "OL", battery_charge: 100, output_voltage: null };
    globalThis.fetch = async (url, options) => {
        assert.equal(url, "http://127.0.0.1:5601/ups/summary");
        assert.equal(options.cache, "no-store");
        assert.equal(options.headers.Accept, "application/json");
        assert.ok(options.signal instanceof AbortSignal);
        return Response.json(summary);
    };

    const response = await GET();
    assert.equal(response.status, 200);
    assert.equal(response.headers.get("Cache-Control"), "no-store");
    assert.deepEqual(await response.json(), summary);
});

test("accepts a different backend address and port with a trailing slash", async () => {
    process.env.UPS_API_URL = "http://ups-server:8000/";
    globalThis.fetch = async (url) => {
        assert.equal(url, "http://ups-server:8000/ups/summary");
        return Response.json({ status: "OB" });
    };

    assert.equal((await GET()).status, 200);
});

test("preserves HTTP errors and NUT error details from the backend", async () => {
    const detail = { detail: "Error ejecutando upsc: Error: Driver not connected" };
    globalThis.fetch = async () => Response.json(detail, { status: 500 });

    const response = await GET();
    assert.equal(response.status, 500);
    assert.deepEqual(await response.json(), detail);
});

test("returns a readable 502 when the backend is unreachable", async () => {
    globalThis.fetch = async () => { throw new TypeError("fetch failed"); };

    const response = await GET();
    assert.equal(response.status, 502);
    assert.equal(response.headers.get("Cache-Control"), "no-store");
    assert.match((await response.json()).detail, /No se pudo consultar/);
});

test("returns a readable 504 when the backend times out", async () => {
    globalThis.fetch = async () => { throw new DOMException("Timed out", "TimeoutError"); };

    const response = await GET();
    assert.equal(response.status, 504);
    assert.match((await response.json()).detail, /tardó demasiado/);
});

test("returns JSON even if the upstream response is not JSON", async () => {
    globalThis.fetch = async () => new Response("<html>Bad Gateway</html>", { status: 502 });

    const response = await GET();
    assert.equal(response.status, 502);
    assert.equal(typeof (await response.json()).detail, "string");
});

test("proxies the live endpoint and preserves the unavailable state", async () => {
    delete process.env.UPS_API_URL;
    globalThis.fetch = async url => {
        assert.equal(url, "http://127.0.0.1:5601/api/ups/current");
        return Response.json({ detail: "NUT no está disponible" }, { status: 503 });
    };

    const response = await getCurrent();
    assert.equal(response.status, 503);
    assert.deepEqual(await response.json(), { detail: "NUT no está disponible" });
});

test("forwards exact ranges and limits to the history endpoint", async () => {
    process.env.UPS_API_URL = "http://ups-server:5601/";
    const query = "?start=2026-01-01T12%3A00%3A00%2B00%3A00&end=2026-01-01T13%3A00%3A00Z&max_points=75";
    globalThis.fetch = async url => {
        assert.equal(url, `http://ups-server:5601/api/metrics${query}`);
        return Response.json({ samples: [], bucket_seconds: null });
    };

    const response = await getMetrics(new Request(`http://monitor.local/api/metrics${query}`));
    assert.equal(response.status, 200);
    assert.equal(response.headers.get("Cache-Control"), "no-store");
    assert.deepEqual(await response.json(), { samples: [], bucket_seconds: null });
});

test("forwards a relative interval to the history endpoint", async () => {
    delete process.env.UPS_API_URL;
    globalThis.fetch = async url => {
        assert.equal(url, "http://127.0.0.1:5601/api/metrics?window_minutes=30");
        return Response.json({ samples: [] });
    };

    const response = await getMetrics(new Request("http://monitor.local/api/metrics?window_minutes=30"));
    assert.equal(response.status, 200);
});
