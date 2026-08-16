import type { Metadata } from "next";
import SurveyClient from "./SurveyClient";

export const metadata: Metadata = {
  title: "GLAP Independent Blinded Review",
  description: "A private bilingual decision-quality review for the frozen GLAP historical replay corpus.",
};

export default function Home() {
  return <SurveyClient />;
}
