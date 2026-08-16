import type { Metadata } from "next";
import { notFound } from "next/navigation";
import BaltimorePilot from "./BaltimorePilot";

export const metadata: Metadata = {
  title: "GLAP Human Evaluation · Local UX pilot",
  description: "Five local-only operational decision stories for human evaluation.",
};

export const dynamic = "force-dynamic";

export default function BaltimorePilotPage() {
  if (process.env.NODE_ENV !== "development") {
    notFound();
  }

  return <BaltimorePilot />;
}
