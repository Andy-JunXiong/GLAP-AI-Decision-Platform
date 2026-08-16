// Test-only bridge from the UX pilot to the exact reviewer-safe frozen bundle.
// Hidden owner identities intentionally do not exist in this repository.
export const HERO_CASE_SOURCE_MANIFEST = [
  { caseId: "baltimore-key-bridge", moment: "T0", reviewId: "f2a0ca874499f3f4fba57e0e", cutoff: "T0_PRE_EVENT", recommendations: ["MONITOR", "MONITOR"], identical: true },
  { caseId: "baltimore-key-bridge", moment: "T1", reviewId: "7069f2800d0db7b40a8687c6", cutoff: "T1_CONFIRMED_DISRUPTION", recommendations: ["RISK_MITIGATION", "MONITOR"], identical: false },
  { caseId: "baltimore-key-bridge", moment: "T2", reviewId: "f220399b6a70a3e5c43ab6e8", cutoff: "T2_RECOVERY_TIMELINE", recommendations: ["MONITOR", "RISK_MITIGATION"], identical: false },
  { caseId: "panama-canal-drought", moment: "T0", reviewId: "182de75a3dd1c53e8d7a59b0", cutoff: "T0_BEFORE_BOOKING_CHANGE", recommendations: ["MONITOR", "MONITOR"], identical: true },
  { caseId: "panama-canal-drought", moment: "T1", reviewId: "82a53042e047009dd5d99ff8", cutoff: "T1_MEDIUM_CAPACITY_SIGNAL", recommendations: ["MONITOR", "MONITOR"], identical: true },
  { caseId: "panama-canal-drought", moment: "T2", reviewId: "e2ac2bb8f8d19f642be26c5e", cutoff: "T2_HIGH_DROUGHT_CAPACITY_RISK", recommendations: ["MONITOR", "RISK_MITIGATION"], identical: false },
  { caseId: "red-sea-security", moment: "T0", reviewId: "364a38412b8753f7f2b2261b", cutoff: "T0_BEFORE_OFFICIAL_STATEMENT", recommendations: ["MONITOR", "MONITOR"], identical: true },
  { caseId: "red-sea-security", moment: "T1", reviewId: "4fbe86c2abb09f6717733eb9", cutoff: "T1_ATTACKS_AND_REROUTING", recommendations: ["RISK_MITIGATION", "MONITOR"], identical: false },
  { caseId: "red-sea-security", moment: "T2", reviewId: "e14aad588544c3193a18f6a4", cutoff: "T2_REROUTING_SCALE_CONFIRMED", recommendations: ["RISK_MITIGATION", "MONITOR"], identical: false },
  { caseId: "faa-notam-outage", moment: "T0", reviewId: "ab88d65ae5bb6602950af2e0", cutoff: "T0_BEFORE_OUTAGE_ADVISORY", recommendations: ["MONITOR", "MONITOR"], identical: true },
  { caseId: "faa-notam-outage", moment: "T1", reviewId: "2160ec6d87a96d8dff54bbfc", cutoff: "T1_OUTAGE_WITHOUT_GROUND_STOP", recommendations: ["MONITOR", "MONITOR"], identical: true },
  { caseId: "faa-notam-outage", moment: "T2", reviewId: "72441c4cff801e9325791c1a", cutoff: "T2_NATIONWIDE_GROUND_STOP", recommendations: ["RISK_MITIGATION", "MONITOR"], identical: false },
  { caseId: "cyclone-gabrielle-roads", moment: "T0", reviewId: "3cf2527dd43593f923e692db", cutoff: "T0_BEFORE_FIRST_NZTA_CYCLONE_SOURCE_AVAILABLE", recommendations: ["MONITOR", "MONITOR"], identical: true },
  { caseId: "cyclone-gabrielle-roads", moment: "T1", reviewId: "91753061d940f8fa9be70d81", cutoff: "T1_COROMANDEL_HIGHWAY_CLOSURES_CONFIRMED", recommendations: ["RISK_MITIGATION", "MONITOR"], identical: false },
  { caseId: "cyclone-gabrielle-roads", moment: "T2", reviewId: "f065f154bf704bbd7b07c49f", cutoff: "T2_NORTHLAND_NETWORK_ISOLATION_CONFIRMED", recommendations: ["MONITOR", "RISK_MITIGATION"], identical: false },
];

export const IDENTICAL_PAIR_ALLOWLIST = new Set(
  HERO_CASE_SOURCE_MANIFEST.filter((item) => item.identical).map((item) => item.reviewId),
);
