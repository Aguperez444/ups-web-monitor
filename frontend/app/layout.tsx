import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "UPS Monitor",
  description: "Estado, flujo de alimentación e historial de métricas de tu UPS.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="es-AR"><body>{children}</body></html>;
}
