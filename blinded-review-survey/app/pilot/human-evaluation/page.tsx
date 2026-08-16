import type { Metadata } from "next";
import SurveyClient from "../../SurveyClient";

export const metadata: Metadata = {
  title: "GLAP Human Evaluation · Formal Review",
  description: "The authenticated formal decision-quality review for the frozen GLAP historical replay corpus.",
};

export const dynamic = "force-dynamic";

export default function HumanEvaluationPage() {
  return <SurveyClient />;
}
