import type { Metadata } from "next";
import BaltimorePilot from "../baltimore/BaltimorePilot";

export const metadata: Metadata = {
  title: "GLAP Human Evaluation · Experience Preview",
  description: "Five operational decision stories for a browser-only human-evaluation experience preview.",
};

export const dynamic = "force-dynamic";

export default function HumanEvaluationPilotPage() {
  return <BaltimorePilot />;
}
