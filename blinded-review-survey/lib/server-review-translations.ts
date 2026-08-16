import type { LocalizedDecisionContent, ReviewPackage } from "./review-types";

const titleZh: Record<string, string> = {
  "Port of Baltimore access disruption after the Francis Scott Key Bridge collapse": "弗朗西斯·斯科特·基桥坍塌后的巴尔的摩港通行中断",
  "Panama Canal transit-capacity restrictions during the 2023 drought": "2023 年干旱期间的巴拿马运河通航能力限制",
  "Commercial-shipping security disruption and rerouting in the Red Sea": "红海商船安全中断与改道",
  "United States air-traffic disruption during the January 2023 NOTAM outage": "2023 年 1 月 NOTAM 故障期间的美国空中交通中断",
  "United States freight-rail labor dispute resolved without an observed nationwide stoppage": "美国货运铁路劳资争议（未发生全国性停运）",
  "Switzerland road-network disruption during the September 2023 Gotthard tunnel closure": "2023 年 9 月圣哥达公路隧道关闭期间的瑞士路网中断",
  "Suez Canal disruption during the March 2021 Ever Given grounding": "2021 年 3 月“长赐号”搁浅期间的苏伊士运河中断",
  "New Zealand road-network disruption during Cyclone Gabrielle in February 2023": "2023 年 2 月加布里埃尔气旋期间的新西兰路网中断",
  "Singapore container-port congestion during May and June 2024": "2024 年 5–6 月新加坡集装箱港口拥堵",
  "Rio Grande do Sul federal-highway disruption during the May 2024 floods": "2024 年 5 月洪灾期间南里奥格兰德州联邦公路中断",
};

const factZh: Record<string, string> = {
  "USACE activated emergency operations and began assessing channel debris removal needed to restore safe navigation at the Port of Baltimore.": "美国陆军工程兵团启动应急行动，并开始评估恢复巴尔的摩港安全通航所需的航道残骸清理工作。",
  "Preliminary underwater analysis was underway and the operational debris-removal plan had not yet been determined.": "初步水下分析正在进行，具体残骸清理方案尚未确定。",
  "USACE expected a limited one-way access channel by the end of April and aimed for full federal-channel access by the end of May.": "美国陆军工程兵团预计 4 月底前开放受限单向通道，并以 5 月底前全面恢复联邦航道为目标。",
  "The tentative reopening dates remained subject to weather and the complexity of the wreckage.": "暂定重开日期仍受天气和残骸复杂程度影响。",
  "The Panama Canal Authority extended one booking condition and scheduled a transition to a new condition for Panamax lock reservations.": "巴拿马运河管理局延长了一项预约条件，并安排巴拿马型船闸预约转入新条件。",
  "The authority reported unprecedented Gatun Lake levels for that time of year and October rainfall 41 percent below the recorded norm.": "管理局报告加通湖水位处于该时段前所未见的低位，10 月降雨量比历史常态低 41%。",
  "The authority announced progressive booking-slot reductions from November 2023 through February 2024, reaching 18 slots per day until further notice.": "管理局宣布从 2023 年 11 月至 2024 年 2 月逐步减少预约名额，最终降至每日 18 个，直至另行通知。",
  "IMO condemned attacks against international shipping and reported that several global operators were rerouting commercial shipping in response to the threat.": "国际海事组织谴责针对国际航运的袭击，并报告多家全球运营商因威胁而调整商船航线。",
  "IMO reported that at least 18 shipping companies had chosen routes around South Africa, adding about ten days to voyages and affecting trade and freight rates.": "国际海事组织报告至少 18 家航运公司选择绕行南非，航程增加约 10 天，并影响贸易与运价。",
  "The FAA command center activated an operational hotline for facilities, international counterparts, and customers in response to the NOTAM equipment outage.": "美国联邦航空局指挥中心因 NOTAM 设备故障，为设施、国际合作方和客户启用运营热线。",
  "The FAA command center reported that the United States NOTAM system had failed, new notices were not being processed, and no restoration estimate was available.": "美国联邦航空局指挥中心报告美国 NOTAM 系统故障，新通告无法处理，且暂无恢复时间预估。",
  "The FAA command center issued a nationwide ground stop covering all flights and destinations, except military and medical-evacuation flights, because the NOTAM system was down.": "因 NOTAM 系统宕机，美国联邦航空局指挥中心发布全国停飞令，除军用和医疗后送航班外覆盖所有航班与目的地。",
  "An emergency board was established after the unresolved railroad labor dispute was judged capable of substantially interrupting interstate transportation service.": "在未解决的铁路劳资争议被认定可能严重中断州际运输服务后，成立了紧急委员会。",
  "Presidential Emergency Board No. 250 submitted findings and recommendations intended to support an equitable negotiated resolution of the rail labor dispute.": "总统第 250 号紧急委员会提交调查结果和建议，以支持通过公平谈判解决铁路劳资争议。",
  "The Swiss Federal Roads Office reported that the Gotthard road tunnel had been closed since 10 September because of ceiling damage; the cause and exact extent were unknown and the tunnel would remain closed until further notice.": "瑞士联邦公路局报告，圣哥达公路隧道因顶部受损自 9 月 10 日起关闭；原因和确切范围尚不明确，隧道将继续关闭直至另行通知。",
  "After safety work, crews removed the damaged intermediate ceiling section overnight; the stated target remained reopening the tunnel by the end of that week.": "完成安全作业后，施工人员连夜拆除了受损的中间顶板；目标仍是在当周末前重开隧道。",
  "The tunnel remained closed while specialists worked on reopening it, and the Federal Roads Office said the reopening time would be communicated the following day.": "隧道仍处于关闭状态，专家正在推进重开工作；联邦公路局表示次日公布重开时间。",
  "The Suez Canal Authority said efforts to dislodge the grounded container ship were ongoing, welcomed assistance, and aimed to restore regular global maritime traffic through the canal as soon as possible.": "苏伊士运河管理局表示，搁浅集装箱船脱困工作仍在进行，欢迎外部援助，并力求尽快恢复运河正常的全球海运交通。",
  "New Zealand Transport Agency Waka Kotahi reported that Cyclone Gabrielle's wind and rain had left State Highway 25 blocked by fallen trees, flooding, and debris, with some sections fully closed and State Highway 25A closed over its full length.": "新西兰交通局报告，加布里埃尔气旋的风雨导致 25 号国道被倒木、洪水和碎片阻断，部分路段完全关闭，25A 国道全线关闭。",
  "New Zealand Transport Agency Waka Kotahi reported that Northland was largely isolated by multiple State Highway 1 slips and flooding on State Highways 16 and 14, with further closures on State Highways 15 and 12 and no heavy-vehicle detour available that night around the Brynderwyn-to-Waipu closure.": "新西兰交通局报告，1 号国道多处滑坡及 16、14 号国道洪水使北地大区基本隔离；15、12 号国道另有关闭，当晚布林德温至怀普关闭路段没有适合重型车辆的绕行路线。",
  "The Maritime and Port Authority of Singapore reported that off-schedule arrivals and increased container volumes had lengthened container-berth waits, with average waits of about two to three days when vessels could not be berthed on arrival.": "新加坡海事及港务管理局报告，非计划到港和集装箱量增加延长了集装箱泊位等待时间；船舶无法到港即靠泊时，平均等待约 2–3 天。",
  "The Maritime and Port Authority of Singapore reported 16.90 million TEUs handled in the first five months of 2024, 7.7 percent above the same period in 2023, and stated that demand for capacity remained strong.": "新加坡海事及港务管理局报告，2024 年前五个月处理 1690 万标准箱，比 2023 年同期增长 7.7%，并表示运力需求仍然强劲。",
  "Brazil's Ministry of Transport reported 40 fully closed sections across six federal highways in Rio Grande do Sul, nine partially closed sections, and five sections restricted to emergency vehicles.": "巴西交通部报告，南里奥格兰德州六条联邦公路共有 40 个路段完全关闭、9 个路段部分关闭，另有 5 个路段仅限应急车辆通行。",
  "Brazil's Ministry of Transport reported that 11 sections across three federal highways remained fully closed and 23 sections across seven highways remained partially closed, while 19 sections were still under work for reopening.": "巴西交通部报告，三条联邦公路的 11 个路段仍完全关闭，七条公路的 23 个路段仍部分关闭，另有 19 个路段仍在进行重开施工。",
};

const disruptionZh: Record<string, string> = {
  INFRASTRUCTURE_FAILURE: "基础设施故障",
  DROUGHT_CAPACITY_RESTRICTION: "干旱导致的通航能力限制",
  MARITIME_SECURITY_THREAT: "海上安全威胁",
  AIR_TRAFFIC_SYSTEM_OUTAGE: "航空交通系统故障",
  RAIL_LABOR_DISPUTE: "铁路劳资争议",
  ROAD_TUNNEL_INFRASTRUCTURE_FAILURE: "公路隧道基础设施故障",
  CANAL_VESSEL_GROUNDING: "运河船舶搁浅",
  EXTREME_WEATHER_ROAD_NETWORK: "极端天气造成的公路网络中断",
  CONTAINER_PORT_CONGESTION: "集装箱港口拥堵",
  FLOOD_DAMAGED_HIGHWAY_NETWORK: "洪灾造成的公路网络中断",
};

const playbookZh: Record<string, { focus: string; short: string[]; long: string[] }> = {
  INFRASTRUCTURE_FAILURE: {
    focus: "港口通道、替代港和内陆衔接",
    short: ["比较替代港口与内陆衔接路径，覆盖当前暴露的货运窗口。", "记录运力、运输时效、清关、短驳和成本差距，供具名人员决策。"],
    long: ["建立包含负责人、触发条件和有效期的双港口应急方案。", "在韧性评审中定期检查关键基础设施节点的集中度。"],
  },
  DROUGHT_CAPACITY_RESTRICTION: {
    focus: "运河预约时段、船期与替代航线",
    short: ["比较受保护的预约窗口与替代航线，覆盖当前暴露的货运窗口。", "记录航程、燃油、运力和成本差距，供具名人员决策。"],
    long: ["建立季节性运河运力触发条件和预先定义的比较标准。", "在低水位季节前检查航线集中度与库存缓冲。"],
  },
  MARITIME_SECURITY_THREAT: {
    focus: "安全暴露、替代航线、保险与运输时效",
    short: ["比较当前航线与通过安全审查的替代航线。", "记录保险、时效、运力和成本差距，供具名人员决策。"],
    long: ["建立航线安全触发条件和受治理的替代航线方案。", "检查长期安全中断下的网络集中度和库存策略。"],
  },
  AIR_TRAFFIC_SYSTEM_OUTAGE: {
    focus: "航班可用性、替代机场与优先货物恢复",
    short: ["比较后续航班、邻近机场和范围受限的地面转运方案。", "记录运力、操作、时效和成本差距，供具名人员决策。"],
    long: ["建立关键空运货物的机场与承运人替代方案。", "识别哪些服务承诺需要预定义的系统故障应急措施。"],
  },
  RAIL_LABOR_DISPUTE: {
    focus: "铁路连续性、联运枢纽与公路替代运力",
    short: ["比较铁路连续性情景与范围受限的联运或公路替代方案。", "记录枢纽、运力、时效和成本差距，供具名人员决策。"],
    long: ["建立劳资中断触发条件和受治理的联运应急方案。", "检查关键铁路货流的运输方式集中度和库存策略。"],
  },
  ROAD_TUNNEL_INFRASTRUCTURE_FAILURE: {
    focus: "走廊关闭、安全绕行与铁路或公路替代路径",
    short: ["比较安全绕行和可行的替代运输方式。", "记录距离、运力、时效和成本差距，供具名人员决策。"],
    long: ["建立走廊故障触发条件和替代路线就绪检查。", "在网络韧性规划中检查单一走廊依赖。"],
  },
  CANAL_VESSEL_GROUNDING: {
    focus: "运河通行、排队暴露、中转与替代海运路线",
    short: ["比较等待、中转和替代海运路线情景。", "记录运力、时效、操作和成本差距，供具名人员决策。"],
    long: ["建立运河阻断触发条件和受治理的航线应急方案。", "检查依赖运河货流的航线集中度和库存缓冲。"],
  },
  EXTREME_WEATHER_ROAD_NETWORK: {
    focus: "道路安全、路网关闭、安全绕行与替代运输方式",
    short: ["仅比较主管机构确认安全的走廊和可行替代运输方式。", "记录通行、运力、时效和成本差距，供具名人员决策。"],
    long: ["建立天气触发的走廊控制和已验证绕行方案。", "检查天气暴露货流的地域集中度和库存策略。"],
  },
  CONTAINER_PORT_CONGESTION: {
    focus: "泊位等待、码头运力、船期与替代港口",
    short: ["比较码头、船期和替代港口方案。", "记录泊位、运力、时效、短驳和成本差距，供具名人员决策。"],
    long: ["建立拥堵触发条件和多港口应急方案。", "检查港口集中度和旺季库存策略。"],
  },
  FLOOD_DAMAGED_HIGHWAY_NETWORK: {
    focus: "道路关闭、安全通行、集结点与替代运输方式",
    short: ["比较主管机构确认安全的路线、集结点和替代运输方式。", "记录通行、运力、时效和成本差距，供具名人员决策。"],
    long: ["建立洪灾触发的走廊控制和已验证恢复方案。", "检查暴露货流的地域集中度和韧性集结点。"],
  },
};

const modeZh: Record<string, string> = {
  OCEAN: "海运",
  AIR: "空运",
  RAIL: "铁路运输",
  ROAD: "公路运输",
};

function localizedDecision(
  item: ReviewPackage,
  option: ReviewPackage["options"][number],
): LocalizedDecisionContent {
  const content = option.content;
  const state = item.scenario.operational_state;
  const highRisk = content.risk_assessment.risk_level === "HIGH";
  const mitigation = option.recommendation === "RISK_MITIGATION";
  const disruption = disruptionZh[item.scenario.scenario_profile.disruption_type]
    ?? item.scenario.scenario_profile.disruption_type.replaceAll("_", " ");
  const mode = modeZh[item.scenario.scenario_profile.transport_mode]
    ?? item.scenario.scenario_profile.transport_mode;
  const sourceCount = item.scenario.visible_evidence.length;
  const playbook = playbookZh[item.scenario.scenario_profile.disruption_type] ?? {
    focus: `${mode}连续性、运力与替代路线`,
    short: ["比较当前暴露窗口内的可行连续性方案。", "记录运力、时效、服务和成本差距，供具名人员决策。"],
    long: ["建立包含负责人、触发条件和有效期的受治理应急方案。", "在韧性规划中检查网络集中度和库存缓冲。"],
  };

  const basisSummary = sourceCount === 0
    ? "截止时间前没有符合条件的权威中断证据，因此该方案不能确认存在重大路线风险。"
    : highRisk && mitigation
      ? "截止时间前可用的高严重度中断证据与受控货运暴露同时存在，支持提出一项范围受限的缓解建议。"
      : highRisk
        ? "虽然截止时间前已有高严重度中断证据且受控货运存在暴露，该方案仍选择继续监测。"
        : "可见证据尚未达到冻结政策规定的高路线风险条件，因此该方案继续监测。";
  const riskStatement = sourceCount === 0
    ? "由于尚无符合条件的公开证据，当前无法确认重大中断风险。"
    : highRisk && mitigation
      ? "高严重度证据与受控暴露同时存在，已形成高路线风险条件。"
      : highRisk
        ? "当前存在高路线风险，但该方案在本次截止点没有提出缓解措施。"
        : "本次截止点的可见信号仍低于高路线风险阈值。";
  const exposureStatement = `受控聚合群组 ${state.shipment_scope} ${state.exposed_to_disruption_node ? "已暴露" : "未暴露"}于中断节点；库存覆盖 ${state.inventory_cover_days} 天，SLA 关键度为 ${state.sla_criticality}，${state.alternate_capacity_available ? "已有替代运力记录" : "没有替代运力记录"}。`;

  const capacityStep = state.alternate_capacity_available
    ? "将已记录的替代运力与当前暴露、库存覆盖和 SLA 关键度进行比较，并记录成本与运输时效缺口。"
    : "在任何缓解方案可被视为可执行之前，先识别并验证可行的替代运力。";
  const objective = mitigation
    ? `针对${disruption}，为 ${state.shipment_scope} 准备一项范围受限且不会自动执行的缓解建议。`
    : `继续对该${mode}${disruption}进行受治理监测，不作运营变更。`;
  const steps = mitigation
    ? [
        "仅引用决策依据中列出的截止时间前可用证据，准备缓解建议。",
        capacityStep,
        "将范围受限的建议提交给具名人员审批；不得预订运力、改道或承诺支出。",
      ]
    : [
        "在下一个受治理复核点，仅更新新近符合截止条件的权威证据。",
        `重新检查 ${state.shipment_scope} 的暴露、库存覆盖、SLA 关键度和替代运力。`,
        "如果高严重度中断证据与受控暴露同时出现，应提交范围受限的缓解建议供具名人员复核。",
      ];
  const tradeoffs = mitigation
    ? [
        state.alternate_capacity_available
          ? "若获批准，缓解措施可能降低暴露，但运力、成本和服务权衡尚未量化。"
          : "该建议没有可用的替代运力记录，因此必须由人工先确认可行性。",
        "较早介入可能有助于保护 SLA 或库存覆盖，但本方案不估算也不声称任何业务结果。",
      ]
    : [
        highRisk
          ? "继续监测可避免未经批准的运营变更，但已确认的高暴露会持续到下一次复核。"
          : "继续监测可避免依据不足时过早行动，但如果情况在下次复核前恶化，响应可能延迟。",
        "本方案不估算也不声称成本、延误、服务或业务结果影响。",
      ];
  tradeoffs.push(
    "货运暴露、库存、SLA 和运力字段均为受控合成状态，不是真实企业记录。",
    `截止时间前仅有 ${sourceCount} 个权威来源符合条件；之后的恢复或结果证据已被排除。`,
    state.alternate_capacity_available
      ? "替代运力虽有记录，但成本、时效和可行性尚未评估。"
      : "没有替代运力记录，因此缓解措施的可行性仍未解决。",
  );

  const difficultyPoints = [
    `本次判断只有 ${sourceCount} 个截止时间前可用的权威来源；不得使用后来事实或结果。`,
    `合成货运组合只有 ${state.inventory_cover_days} 天库存覆盖且 SLA 关键度为 ${state.sla_criticality}，时间压力存在，但结果尚未发生。`,
    state.alternate_capacity_available ? "替代运力虽有记录，但成本、时效和可行性尚未验证。" : "没有替代运力记录，方案可行性仍未解决。",
    "任何高影响响应都只能先形成建议，必须由具名人员批准。",
  ];
  const impactPathways = [
    `如果${disruption}影响该合成货运组合，延误可能消耗 ${state.inventory_cover_days} 天库存缓冲，并使 ${state.sla_criticality} SLA 承诺承压。`,
    `如果对${playbook.focus}的依赖长期得不到解决，积压、加急成本、客户服务和网络韧性压力可能继续累积。`,
  ];
  const immediate = mitigation
    ? {
        horizon: content.solution_horizons.immediate.horizon,
        objective: "在不执行运营变更的前提下，形成可供审批的缓解决策包。",
        steps: ["识别暴露货运窗口、SLA 关键范围和剩余库存缓冲。", "把每项建议与截止时间前证据和合成状态假设逐一绑定。", "明确具名决策人和最迟安全复核时间。"],
      }
    : {
        horizon: content.solution_horizons.immediate.horizon,
        objective: "建立严格的证据监测，并在不改变运营的情况下核实合成暴露。",
        steps: ["确认下一次受治理证据复核时间和需要更新的权威来源。", "核对暴露范围、库存缓冲、SLA 关键度和替代运力记录。", "写明触发升级所需的高严重度证据与暴露条件。"],
      };
  const solutionHorizons = {
    immediate,
    short_term: {
      horizon: content.solution_horizons.short_term.horizon,
      objective: mitigation ? `验证${playbook.focus}中的范围受限替代方案，供具名人员决策。` : `保持${playbook.focus}的可比较应急视图，但不预订或改道。`,
      steps: mitigation ? playbook.short : [`持续维护${playbook.focus}的决策输入，并标记缺失的可行性信息。`, "准备范围受限的决策包模板，使触发条件满足时可快速提交人工复核。"],
    },
    long_term: {
      horizon: content.solution_horizons.long_term.horizon,
      objective: mitigation ? "在不预先授权执行的前提下，降低重复决策延迟与集中度风险。" : "提高证据纪律和应急准备度，但不把监测转化为长期执行权限。",
      steps: playbook.long,
    },
  };
  const intendedBenefits = mitigation
    ? {
        short_term: [
          { benefit: "缩短从确认高风险到具名人员获得完整决策包的时间。", measurement_signal: "从高严重度证据符合条件到形成完整审批建议所需时间。", claim_status: content.intended_benefits.short_term[0].claim_status },
          { benefit: "在合成库存缓冲下降前保留可行的路线或运力选择。", measurement_signal: "已完成运力、时效、服务和成本比较的 SLA 关键范围占比。", claim_status: content.intended_benefits.short_term[1].claim_status },
        ],
        long_term: [
          { benefit: `通过可重复使用的受治理方案，提高${playbook.focus}的韧性准备度。`, measurement_signal: "具有负责人、触发条件、证据来源和复核日期的已验证替代方案数量。", claim_status: content.intended_benefits.long_term[0].claim_status },
          { benefit: "让未来中断决策更快、更一致、更容易审计。", measurement_signal: "使用受批准触发条件和决策包模板的后续评审占比。", claim_status: content.intended_benefits.long_term[1].claim_status },
        ],
      }
    : {
        short_term: [
          { benefit: "避免依据不足时过早改变运营，同时保留清晰的人工升级路径。", measurement_signal: "新增合格证据出现后到下一次受治理复核的时间。", claim_status: content.intended_benefits.short_term[0].claim_status },
          { benefit: "明确暴露与可行性缺口，提高后续决策准备度。", measurement_signal: "复核时暴露、库存、SLA、运力和触发条件字段的完整度。", claim_status: content.intended_benefits.short_term[1].claim_status },
        ],
        long_term: [
          { benefit: "为类似中断建立可重复的证据监测和升级纪律。", measurement_signal: "具有可追溯证据、具名负责人和明确触发条件的评审占比。", claim_status: content.intended_benefits.long_term[0].claim_status },
          { benefit: `在不提前承诺资源的情况下，保持${playbook.focus}的可重复使用应急准备。`, measurement_signal: "具有已知信息缺口、负责人和复核日期的当前替代方案数量。", claim_status: content.intended_benefits.long_term[1].claim_status },
        ],
      };

  return {
    decision_basis: {
      summary: basisSummary,
      evidence_citations: content.decision_basis.evidence_citations.map((citation) => ({
        ...citation,
        why_relevant: `该来源中截止时间前可用的事实，为本方案提供 ${content.decision_basis.strongest_visible_severity} 严重度的中断或恢复依据。`,
      })),
    },
    problem_response: {
      primary_problem: mitigation
        ? `已确认的高严重度中断证据与合成货运暴露重合，但${playbook.focus}的可行性尚未验证。`
        : sourceCount === 0
          ? "权威证据尚不足以支持中断响应，但合成业务暴露仍需要明确的监测与升级路径。"
          : `本方案必须判断现有证据是否足以针对${playbook.focus}采取行动，同时避免反应过度或错失时机。`,
      difficulty_points: difficultyPoints,
      impact_pathways: impactPathways,
    },
    risk_assessment: { risk_statement: riskStatement, exposure_statement: exposureStatement },
    action_plan: {
      objective,
      steps: steps.map((instruction, index) => ({ sequence: index + 1, instruction })),
      review_trigger: mitigation
        ? "人工审批结果、新增合格证据、恢复证据，或暴露与运力发生变化。"
        : "新增高严重度合格证据、暴露变化、库存覆盖下降、SLA 关键度上升或运力变化。",
    },
    solution_horizons: solutionHorizons,
    intended_benefits: intendedBenefits,
    tradeoffs_and_uncertainty: tradeoffs,
  };
}

function localizedScenarioBrief(item: ReviewPackage): ReviewPackage["scenario"]["brief"] {
  const scenario = item.scenario;
  const state = scenario.operational_state;
  const disruption = disruptionZh[scenario.scenario_profile.disruption_type]
    ?? scenario.scenario_profile.disruption_type.replaceAll("_", " ");
  const mode = modeZh[scenario.scenario_profile.transport_mode]
    ?? scenario.scenario_profile.transport_mode;
  const facts = scenario.visible_evidence.flatMap((evidence) => evidence.facts);
  const displayedFacts = facts.slice(0, 2).map((fact) => factZh[fact.summary] ?? fact.summary);
  return {
    story_summary: displayedFacts.length > 0
      ? `故事发展到这一时点，共有 ${scenario.visible_evidence.length} 个截止时间前可用的权威来源。关键事实：${displayedFacts.join("；")}`
      : "这是事件被权威信息确认前的对照时点。标题用于标识完整历史案例，但截止时间前没有可用的权威事件事实；此时只能从受控合成业务暴露出发判断。",
    decision_pressure: `匿名合成${mode}货运组合${state.exposed_to_disruption_node ? "已" : "未"}暴露于相关节点，库存覆盖 ${state.inventory_cover_days} 天，SLA 关键度为 ${state.sla_criticality}，${state.alternate_capacity_available ? "替代运力有记录但尚未验证" : "尚无替代运力记录"}。`,
    difficulty_points: [
      "必须把截止时间前真正可见的事实与后来才知道的完整历史故事分开。",
      `需要在 ${state.inventory_cover_days} 天合成库存缓冲、${state.sla_criticality} SLA 压力与不完整的成本、时效和可行性信息之间权衡。`,
      "既要考虑响应速度和韧性，也要避免过早行动，并保留具名人员的最终权限。",
    ],
    downstream_risks: [
      `如果${disruption}影响该合成货运组合，延误可能消耗库存缓冲并使服务承诺承压。`,
      "如果关键依赖长期得不到解决，积压、加急成本、客户服务和网络韧性压力可能继续累积。",
    ],
    decision_question: "哪个方案能更可信地回应当前问题，兼顾立即、短期和长期路径，同时把收益保持为待验证假设并保留人工执行权限？",
    fact_boundary: `只能使用本页列出的 ${scenario.visible_evidence.length} 个来源和 ${facts.length} 条事实；之后的恢复与结果信息均被排除。`,
  };
}

export function localizeReviewPackages(packages: ReviewPackage[]): ReviewPackage[] {
  return packages.map((item) => ({
    ...item,
    scenario: {
      ...item.scenario,
      scenario_title_zh: titleZh[item.scenario.scenario_title] ?? item.scenario.scenario_title,
      brief_zh: localizedScenarioBrief(item),
      visible_evidence: item.scenario.visible_evidence.map((evidence) => ({
        ...evidence,
        facts: evidence.facts.map((fact) => ({
          ...fact,
          summary_zh: factZh[fact.summary] ?? fact.summary,
        })),
      })),
    },
    options: item.options.map((option) => ({
      ...option,
      content_zh: localizedDecision(item, option),
    })),
  }));
}
