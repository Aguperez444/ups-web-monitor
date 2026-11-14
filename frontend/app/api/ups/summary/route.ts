import { proxyUps } from "@/app/lib/ups-proxy";

export const dynamic = "force-dynamic";

export function GET() {
  return proxyUps("/ups/summary");
}
