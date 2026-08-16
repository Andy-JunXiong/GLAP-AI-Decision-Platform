import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "GLAP Independent Blinded Review",
  description: "Private bilingual decision-quality review.",
  icons: { icon: "/favicon.svg", shortcut: "/favicon.svg" },
  openGraph: {
    title: "GLAP Independent Blinded Review",
    description: "Private bilingual decision-quality review.",
    images: [{ url: "/og.png", width: 1536, height: 1024 }],
  },
  twitter: {
    card: "summary_large_image",
    title: "GLAP Independent Blinded Review",
    description: "Private bilingual decision-quality review.",
    images: ["/og.png"],
  },
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="zh-CN"><body>{children}</body></html>;
}
