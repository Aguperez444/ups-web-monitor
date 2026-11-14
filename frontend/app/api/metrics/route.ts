import { proxyUps } from "@/app/lib/ups-proxy";

export const dynamic = "force-dynamic";

export function GET(request: Request) {
  return proxyUps(`/api/metrics${new URL(request.url).search}`);
}
