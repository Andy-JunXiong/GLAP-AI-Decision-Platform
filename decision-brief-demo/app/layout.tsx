import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";

const geistSans = Geist({ variable: "--font-geist-sans", subsets: ["latin"] });
const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });

export const metadata: Metadata = {
  title: "GLAP Port Disruption Decision Brief",
  description: "A traceable logistics decision demo for port congestion, strike risk, FCL storage exposure and inventory protection.",
  openGraph: {
    title: "GLAP Port Disruption Decision Brief",
    description: "See how an early port-diversion decision can protect inventory and avoid FCL storage exposure.",
    images: [{ url: "/og.png", width: 1536, height: 1024 }],
    type: "website",
  },
  twitter: {
    card: "summary_large_image",
    title: "GLAP Port Disruption Decision Brief",
    description: "A traceable logistics decision for congestion, strike risk, storage exposure and inventory protection.",
    images: ["/og.png"],
  },
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body className={`${geistSans.variable} ${geistMono.variable}`}>{children}</body>
    </html>
  );
}
