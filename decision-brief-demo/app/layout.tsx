import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";

const geistSans = Geist({ variable: "--font-geist-sans", subsets: ["latin"] });
const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });

export const metadata: Metadata = {
  title: "GLAP Logistics Decision Platform",
  description: "A customer-friendly control tower that turns logistics risk signals into traceable, human-reviewed decisions and measurable outcomes.",
  openGraph: {
    title: "GLAP Logistics Decision Platform",
    description: "From emerging logistics signals to human-reviewed decisions and measurable outcomes.",
    images: [{ url: "/og.png", width: 1536, height: 1024 }],
    type: "website",
  },
  twitter: {
    card: "summary_large_image",
    title: "GLAP Logistics Decision Platform",
    description: "A customer-friendly logistics control tower for signals, decisions, shipments and outcomes.",
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
