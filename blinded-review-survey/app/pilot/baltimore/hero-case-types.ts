export type LocalText = { zh: string; en: string };

export type PilotOption = {
  id: "A" | "B";
  title: LocalText;
  body: LocalText;
  tradeoff: LocalText;
};

export type HeroStage = {
  moment: "T0" | "T1" | "T2";
  date: LocalText;
  status: LocalText;
  context: LocalText;
  newEvidence: LocalText[];
  operationalFacts: Array<{
    label: LocalText;
    value: LocalText;
    tone?: "warning" | "positive";
  }>;
  question: LocalText;
  options: [PilotOption, PilotOption];
};

export type HeroCase = {
  id: string;
  title: LocalText;
  shortTitle: LocalText;
  role: LocalText;
  mode: "OCEAN" | "AIR" | "RAIL" | "ROAD";
  disruption: LocalText;
  region: LocalText;
  decisionLens: LocalText;
  stages: [HeroStage, HeroStage, HeroStage];
};
