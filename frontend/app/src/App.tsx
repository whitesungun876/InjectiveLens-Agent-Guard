import {
  AlertTriangle,
  Bot,
  CheckCircle2,
  ClipboardCheck,
  Database,
  ExternalLink,
  Eye,
  History,
  ListChecks,
  Play,
  ShieldCheck,
  Zap
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import {
  getAgentAudit,
  getLatestPreflightAssessment,
  getPreflightHistory,
  recordInjectiveProof,
  runInjectivePreflight,
  verifyInjectiveProof
} from "./injectivePreflightApi";

type Mode = "demo" | "live";
type TabId = "overview" | "evidence" | "history" | "audit";
type Decision = "allow" | "warn" | "block";
type RiskLevel = "low" | "moderate" | "high" | "critical" | "unknown";

type TradeIntent = {
  market: string;
  side: "long" | "short" | "buy" | "sell";
  orderType: "market" | "limit";
  leverage: number;
  marginUsagePct: number;
  notionalUsd: number;
  slippageBps: number;
};

type EvidenceItem = {
  id: string;
  source: string;
  claim: string;
  verification: string;
  dataQuality: string;
  mode: "demo_replay" | "live_read_only" | "simulated";
  adapter: string;
  sourceKind: string;
  scope: string;
  rawRef?: string;
  timestamp: string;
};

type RiskSignal = {
  id: string;
  title: string;
  severity: RiskLevel;
  claim: string;
  confidence: number;
  evidenceIds: string[];
};

type ToolTrace = {
  step: number;
  tool: string;
  status: "completed" | "allow" | "block" | "skipped" | "failed";
  summary: string;
  evidenceIds?: string[];
  actionType?: string;
  timestamp?: string;
};

type Simulation = {
  before: TradeIntent;
  after: TradeIntent;
  riskBefore: number;
  riskAfter: number;
  riskDelta: number;
  explanation: string;
  noBroadcast: true;
};

type ProofRecord = {
  status:
    | "not_recorded"
    | "ready_to_record"
    | "pending"
    | "recorded"
    | "verified_matched"
    | "verified_mismatch"
    | "unavailable";
  network: "Injective testnet";
  method: "tx memo proof" | "testnet memo proof";
  txHash?: string;
  explorerUrl?: string;
  localAssessmentHash?: string;
  onchainAssessmentHash?: string;
  blockHeight?: number;
  message: string;
};

type PreflightAssessment = {
  assessmentId: string;
  assessmentHash: string;
  prompt: string;
  mode: Mode;
  network: "Injective testnet";
  account: string;
  subaccountId: string;
  parsedIntent: TradeIntent;
  decision: Decision;
  riskScore: number;
  riskLevel: RiskLevel;
  action: string;
  reason: string;
  topRisks: RiskSignal[];
  evidence: EvidenceItem[];
  simulation: Simulation;
  proof: ProofRecord;
  injectiveContext: {
    account: string;
    subaccountId: string;
    subaccountKind?: string;
    accountSourceKind?: string;
    accountSourceDisclosure?: string;
    availableMarginUsd?: number;
    marketId?: string;
    marketSourceKind?: string;
    marketSourceDisclosure?: string;
    markPrice?: number;
    oraclePrice?: number;
    fundingRatePct?: number;
    spreadBps?: number;
    maxLeverage?: number;
    openPositionCount?: number;
  };
  sourceCoverage: {
    status: "full" | "partial" | "replay";
    summary: string;
    modeSummary?: string;
    sources: Array<{ name: string; status: "available" | "partial" | "replay" | "simulated" }>;
  };
  allowedActions: string[];
  blockedActions: string[];
  toolTrace: ToolTrace[];
  createdAt: string;
};

type HistoryRecord = {
  id: string;
  createdAt: string;
  market: string;
  decision: Decision;
  score: number;
  riskLevel?: RiskLevel;
  risks: string[];
  proofStatus: string;
  txHash?: string;
  dataMode?: "demo_replay" | "live_read_only";
  sourceMode?: string;
  marketSource?: string;
  simulatedMarket?: boolean;
  proofRecorded?: boolean;
  proofVerified?: boolean;
};

type AgentAuditState = {
  assessmentId: string;
  allowedActions: string[];
  blockedActions: string[];
  llmBoundary: string;
  agentIdentity: {
    agentName: string;
    agentCardUrl: string;
    registryUrl: string;
    mcpUrl?: string;
  };
  toolTrace: ToolTrace[];
};

type EvidenceSlot = {
  id: "E1" | "E2" | "E3" | "E4" | "E5" | "E6";
  title: string;
  source: string;
  claim: string;
  verification: string;
  dataQuality: string;
  mode: string;
  timestamp: string;
};

const DEFAULT_PROMPT = "Open a 10x long INJ-PERP using 60% of available margin.";
const DEFAULT_ACCOUNT = "inj1wrse2035wdnxrq4gwhnxp0nmeyg6u3vss5uvlp";
const DEFAULT_SUBACCOUNT =
  "0x0000000000000000000000000000000000000000000000000000000000000000";
const PROOF_SCOPE_HEADLINE = "Proof of assessment, not proof of trade execution.";
const PROOF_SCOPE_NOTE =
  "This proof verifies the guard assessment record only, not trade profitability, execution safety, or wallet outcome.";

const scenarios = [
  {
    id: "approve_low_risk",
    label: "Approve · 2x / 10% margin",
    prompt: "Open a 2x long INJ-PERP using 10% of available margin.",
    summary: "Low-risk preview. The guard should approve a human-confirmed execution preview."
  },
  {
    id: "require_review",
    label: "Require review · 4x / 25% margin",
    prompt: "Open a 4x long INJ-PERP using 25% of available margin.",
    summary: "Medium-risk request. The guard should require review before execution."
  },
  {
    id: "critical_block",
    label: "Block · 10x / 60% margin",
    prompt: DEFAULT_PROMPT,
    summary: "Critical leverage and margin usage. The guard should block execution."
  }
];

function decisionLabel(decision: Decision): string {
  if (decision === "allow") return "APPROVE";
  if (decision === "warn") return "REQUIRE REVIEW";
  return "BLOCK";
}

function decisionTitle(assessment: PreflightAssessment): string {
  if (assessment.decision === "allow") return "APPROVE: human-confirmed preview is acceptable";
  if (assessment.decision === "warn") return "REQUIRE REVIEW: human approval needed before execution";
  return "BLOCK: high-risk trading request";
}

function severityClass(severity: RiskLevel | Decision): string {
  if (severity === "critical" || severity === "block") return "danger";
  if (severity === "high" || severity === "warn") return "warning";
  if (severity === "low" || severity === "allow") return "success";
  return "neutral";
}

function formatIntent(intent: TradeIntent): string {
  return `${intent.side.toUpperCase()} ${intent.market} · ${intent.leverage}x · ${intent.marginUsagePct}% margin · ${intent.orderType}`;
}

function shortValue(value?: string): string {
  if (!value) return "Unavailable";
  if (value.length <= 24) return value;
  return `${value.slice(0, 12)}...${value.slice(-8)}`;
}

function formatUsd(value?: number): string {
  if (typeof value !== "number") return "Unavailable";
  return `US$${value.toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
}

function formatPercent(value?: number): string {
  if (typeof value !== "number") return "Unavailable";
  return `${value.toLocaleString(undefined, { maximumFractionDigits: 4 })}%`;
}

function formatPricePair(mark?: number, oracle?: number): string {
  if (typeof mark !== "number" && typeof oracle !== "number") return "Unavailable";
  const markText = typeof mark === "number" ? `$${mark.toLocaleString(undefined, { maximumFractionDigits: 4 })}` : "n/a";
  const oracleText = typeof oracle === "number" ? `$${oracle.toLocaleString(undefined, { maximumFractionDigits: 4 })}` : "n/a";
  return `${markText} / ${oracleText}`;
}

function proofLabel(proof: ProofRecord): string {
  if (isProofVerified(proof)) return "Proof verified";
  if (proof.status === "verified_matched") return "Proof verification incomplete";
  if (proof.status === "ready_to_record") return "Assessment hash generated";
  if (proof.status === "pending") return "Awaiting proof recording";
  if (proof.status === "recorded" && proof.txHash) return "Proof recorded on Injective testnet";
  if (proof.status === "recorded") return "Proof record missing tx";
  if (proof.status === "verified_mismatch") return "Proof mismatch";
  if (proof.status === "unavailable") return "Unavailable";
  return "Not recorded";
}

function proofTone(proof: ProofRecord): "success" | "warning" | "danger" | "neutral" {
  if (isProofVerified(proof) || (proof.status === "recorded" && proof.txHash)) return "success";
  if (proof.status === "ready_to_record" || proof.status === "pending") return "warning";
  if (proof.status === "verified_mismatch" || proof.status === "unavailable") return "danger";
  return "neutral";
}

function isProofRecorded(proof: ProofRecord): boolean {
  return Boolean(proof.txHash) && ["recorded", "verified_matched"].includes(proof.status);
}

function isProofVerified(proof: ProofRecord): boolean {
  return proof.status === "verified_matched" && Boolean(proof.txHash && proof.onchainAssessmentHash);
}

function traceStatusClass(status: ToolTrace["status"]): "success" | "warning" | "danger" | "neutral" {
  if (status === "block" || status === "failed") return "danger";
  if (status === "skipped") return "neutral";
  if (status === "allow" || status === "completed") return "success";
  return "neutral";
}

function usesSimulatedFixture(assessment: PreflightAssessment): boolean {
  const marketId = assessment.injectiveContext.marketId || "";
  return (
    marketId.startsWith("demo_fixture:") ||
    marketId.startsWith("simulated_fixture:") ||
    assessment.evidence.some((item) =>
      ["live_unavailable_fixture_fallback", "simulated_market_fixture", "simulated_fixture"].includes(item.sourceKind)
    )
  );
}

function isLivePartialFallback(assessment: PreflightAssessment): boolean {
  return assessment.mode === "live" && (assessment.sourceCoverage.status !== "full" || usesSimulatedFixture(assessment));
}

function dataModeLabel(assessment: PreflightAssessment): string {
  if (assessment.mode === "demo") return "Demo replay + Injective testnet proof";
  return "Live read-only Injective testnet check";
}

function sourceStatusLabel(assessment: PreflightAssessment): string {
  if (assessment.mode === "demo") return "Demo replay fixture; proof record can be verified on Injective testnet";
  if (isLivePartialFallback(assessment)) return "Live source partial · using disclosed simulated fallback";
  return "Injective testnet adapter";
}

function sourceStatusTone(assessment: PreflightAssessment): "success" | "warning" | "danger" | "neutral" {
  if (assessment.mode === "demo") return "neutral";
  if (isLivePartialFallback(assessment)) return "warning";
  return "success";
}

function marketLabel(assessment: PreflightAssessment): string {
  const market = assessment.parsedIntent.market;
  const marketId = assessment.injectiveContext.marketId;
  if (assessment.mode === "demo") return `${market} demo market fixture`;
  if (!marketId || marketId.startsWith("demo_fixture:") || marketId.startsWith("simulated_fixture:")) return `${market} simulated market fixture`;
  return marketId;
}

function subaccountLabel(assessment: PreflightAssessment): string {
  if (assessment.injectiveContext.subaccountKind === "simulation_placeholder") {
    return "Simulation subaccount placeholder";
  }
  return shortValue(assessment.injectiveContext.subaccountId);
}

function historyDataModeLabel(record: HistoryRecord): string {
  if (record.dataMode === "demo_replay") return "Demo replay + testnet proof record";
  if (record.dataMode === "live_read_only") return "Live read-only Injective testnet check";
  if (record.sourceMode) return record.sourceMode;
  return "Unknown mode";
}

function decisionTone(decision: Decision): "success" | "warning" | "danger" | "neutral" {
  if (decision === "allow") return "success";
  if (decision === "warn") return "warning";
  if (decision === "block") return "danger";
  return "neutral";
}

function evidenceById(assessment: PreflightAssessment, id: string): EvidenceItem | undefined {
  return assessment.evidence.find((item) => item.id === id);
}

function buildEvidenceSlots(assessment: PreflightAssessment): EvidenceSlot[] {
  const account = evidenceById(assessment, "ev_account_001");
  const market = evidenceById(assessment, "ev_market_001");
  const policy = evidenceById(assessment, "ev_policy_001");
  const simulation = evidenceById(assessment, "ev_simulation_001");
  const fallbackTimestamp = assessment.createdAt;
  const marketIsLive = market?.sourceKind === "live_read_only" && !usesSimulatedFixture(assessment);
  const fixtureLabel = assessment.mode === "demo" ? "Demo market fixture" : "Simulated market/account fixture";
  const marketClaim =
    market?.claim ||
    (marketIsLive
      ? `Live Injective testnet market snapshot was read for ${assessment.parsedIntent.market}.`
      : `${fixtureLabel} disclosed for ${assessment.parsedIntent.market}.`);
  const proofClaim = isProofVerified(assessment.proof)
    ? "Assessment hash is recorded and verified against the Injective testnet proof transaction."
    : isProofRecorded(assessment.proof)
      ? "Assessment hash has a recorded Injective testnet proof transaction and is ready to verify."
      : "Assessment hash has been generated and waits for explicit proof recording.";

  return [
    {
      id: "E1",
      title: "Account",
      source: account?.source || "Injective account state",
      claim: account?.claim || "Read-only account and subaccount context used for margin checks.",
      verification: account?.verification || "Account adapter read",
      dataQuality: account?.dataQuality || "Read-only account context",
      mode: account?.mode || (assessment.mode === "demo" ? "demo replay" : "live read-only"),
      timestamp: account?.timestamp || fallbackTimestamp
    },
    {
      id: "E2",
      title: marketIsLive ? "Market source" : "Market fixture",
      source: market?.source || "Injective market snapshot",
      claim: marketClaim,
      verification: market?.verification || "Market adapter read",
      dataQuality: market?.dataQuality || sourceStatusLabel(assessment),
      mode: market?.mode || (assessment.mode === "demo" ? "demo replay" : "live read-only"),
      timestamp: market?.timestamp || fallbackTimestamp
    },
    {
      id: "E3",
      title: "Mark/oracle price",
      source: "Injective market price context",
      claim: `Mark/oracle price pair used by the guard: ${formatPricePair(assessment.injectiveContext.markPrice, assessment.injectiveContext.oraclePrice)}.`,
      verification: market?.verification || "Market adapter read",
      dataQuality: market?.dataQuality || "Price context disclosed",
      mode: market?.mode || (assessment.mode === "demo" ? "demo replay" : "live read-only"),
      timestamp: market?.timestamp || fallbackTimestamp
    },
    {
      id: "E4",
      title: "Funding",
      source: "Injective funding context",
      claim: `Funding rate context used by the guard: ${formatPercent(assessment.injectiveContext.fundingRatePct)}.`,
      verification: market?.verification || "Market adapter read",
      dataQuality: market?.dataQuality || "Funding context disclosed",
      mode: market?.mode || (assessment.mode === "demo" ? "demo replay" : "live read-only"),
      timestamp: market?.timestamp || fallbackTimestamp
    },
    {
      id: "E5",
      title: "Guard policy",
      source: policy?.source || "Guard policy threshold",
      claim: policy?.claim || "Leverage, margin usage, coverage risk, and execution boundaries are scored before any order path.",
      verification: policy?.verification || "Deterministic policy evaluation",
      dataQuality: policy?.dataQuality || "Policy rule",
      mode: policy?.mode || "simulated",
      timestamp: policy?.timestamp || fallbackTimestamp
    },
    {
      id: "E6",
      title: "Assessment/proof record",
      source: simulation?.source || "Assessment proof state",
      claim: proofClaim,
      verification: assessment.proof.txHash ? `Tx ${shortValue(assessment.proof.txHash)}` : "Assessment hash generated locally",
      dataQuality: proofLabel(assessment.proof),
      mode: assessment.proof.txHash ? "injective testnet proof" : simulation?.mode || "proof pending",
      timestamp: simulation?.timestamp || fallbackTimestamp
    }
  ];
}

function evidenceRefsForRisk(risk: RiskSignal): string {
  const refs = new Set<string>();
  risk.evidenceIds.forEach((id) => {
    if (id === "ev_account_001") refs.add("E1");
    if (id === "ev_market_001") {
      refs.add("E2");
      refs.add("E3");
      refs.add("E4");
    }
    if (id === "ev_position_001") refs.add("E3");
    if (id === "ev_policy_001" || id === "ev_intent_001") refs.add("E5");
    if (id === "ev_simulation_001") refs.add("E6");
  });
  if (!refs.size) refs.add("E5");
  return Array.from(refs).join(", ");
}

function auditIntro(assessment: PreflightAssessment): string {
  if (assessment.decision === "block") {
    return "This audit view shows why the agent was blocked, which evidence was used, which actions remain allowed, and why no order was placed.";
  }
  return "This audit view shows how the guard reached its decision, which evidence was used, which actions remain allowed, and why no order was placed automatically.";
}

function boundaryActionLabel(action: string): string {
  if (action === "Record assessment hash") return "Record assessment hash after explicit confirmation";
  return action;
}

function auditPhaseSummaries(assessment: PreflightAssessment) {
  const evidenceCount = buildEvidenceSlots(assessment).length;
  const decision = decisionLabel(assessment.decision);
  const proofState = isProofVerified(assessment.proof)
    ? "proof verified on Injective testnet"
    : isProofRecorded(assessment.proof)
      ? "proof recorded and ready to verify"
      : "assessment hash generated; proof recording awaits explicit confirmation";

  return [
    {
      title: "Parse intent",
      status: "Completed",
      tone: "success",
      body: `Parsed the natural-language request into ${formatIntent(assessment.parsedIntent)}.`
    },
    {
      title: "Bind Injective evidence",
      status: `${evidenceCount} bound`,
      tone: sourceStatusTone(assessment),
      body: `${dataModeLabel(assessment)} · ${sourceStatusLabel(assessment)}.`
    },
    {
      title: assessment.decision === "block" ? "Evaluate risk & block unsafe execution" : "Evaluate risk & set execution boundary",
      status: `${decision} · ${assessment.riskScore}/100`,
      tone: decisionTone(assessment.decision),
      body:
        assessment.decision === "block"
          ? "Policy blocks order placement while keeping evidence review, simulation, proof recording, and verification available."
          : "Policy keeps execution preview gated by human confirmation; no autonomous order is placed."
    },
    {
      title: "Generate assessment hash / wait for proof recording",
      status: proofLabel(assessment.proof),
      tone: proofTone(assessment.proof),
      body: `${shortValue(assessment.assessmentHash)} · ${proofState}.`
    }
  ];
}

function traceEmphasisClass(event: ToolTrace): string {
  const keyTools = new Set([
    "EvaluateTradeRisk",
    "DecideExecutionBoundary",
    "GenerateAssessmentHash",
    "RecordAssessment",
    "VerifyAssessment"
  ]);
  const tone = traceStatusClass(event.status);
  return `${keyTools.has(event.tool) ? "trace-key" : "trace-subtle"} trace-${tone}`;
}

export function App() {
  const [mode, setMode] = useState<Mode>("demo");
  const [scenarioId, setScenarioId] = useState(scenarios[0].id);
  const [prompt, setPrompt] = useState(DEFAULT_PROMPT);
  const [account, setAccount] = useState(DEFAULT_ACCOUNT);
  const [activeTab, setActiveTab] = useState<TabId>("overview");
  const [assessment, setAssessment] = useState<PreflightAssessment | null>(null);
  const [historyRecords, setHistoryRecords] = useState<HistoryRecord[]>([]);
  const [audit, setAudit] = useState<AgentAuditState | null>(null);
  const [simulationVisible, setSimulationVisible] = useState(false);
  const [isRunning, setIsRunning] = useState(false);
  const [isProofBusy, setIsProofBusy] = useState(false);
  const [isRestoring, setIsRestoring] = useState(true);
  const [apiError, setApiError] = useState<string | null>(null);
  const [runFeedback, setRunFeedback] = useState<string | null>(null);

  const selectedScenario = useMemo(
    () => scenarios.find((scenario) => scenario.id === scenarioId) ?? scenarios[0],
    [scenarioId]
  );
  const resultModeMismatch = assessment ? assessment.mode !== mode : false;

  useEffect(() => {
    let isActive = true;

    async function restoreLatestAssessment() {
      try {
        const latest = await getLatestPreflightAssessment();
        if (!isActive || !latest) return;

        const restoredScenario = scenarios.find((scenario) => scenario.prompt === latest.prompt);
        if (restoredScenario) {
          setScenarioId(restoredScenario.id);
        }
        setPrompt(latest.prompt);
        setAccount(latest.account);
        setMode(latest.mode as Mode);
        setAssessment(latest as PreflightAssessment);
        setSimulationVisible(false);
        setActiveTab("overview");

        const [records, auditState] = await Promise.all([
          getPreflightHistory(),
          getAgentAudit(latest.assessmentId)
        ]);
        if (!isActive) return;
        setHistoryRecords(records as HistoryRecord[]);
        setAudit(auditState as AgentAuditState);
      } catch (error) {
        if (isActive) {
          setApiError(error instanceof Error ? error.message : "Latest pre-flight restore failed");
        }
      } finally {
        if (isActive) {
          setIsRestoring(false);
        }
      }
    }

    void restoreLatestAssessment();

    return () => {
      isActive = false;
    };
  }, []);

  function clearActiveResult() {
    setAssessment(null);
    setAudit(null);
    setSimulationVisible(false);
    setActiveTab("overview");
    setRunFeedback(null);
    setApiError(null);
  }

  function handleScenarioChange(id: string) {
    const scenario = scenarios.find((item) => item.id === id) ?? scenarios[0];
    setScenarioId(scenario.id);
    setPrompt(scenario.prompt);
    clearActiveResult();
  }

  function handleModeChange(nextMode: Mode) {
    if (nextMode === mode) return;
    setMode(nextMode);
    clearActiveResult();
  }

  function handlePromptChange(nextPrompt: string) {
    setPrompt(nextPrompt);
    clearActiveResult();
  }

  function handleAccountChange(nextAccount: string) {
    setAccount(nextAccount);
    clearActiveResult();
  }

  async function refreshHistory() {
    const records = await getPreflightHistory();
    setHistoryRecords(records as HistoryRecord[]);
  }

  async function refreshAudit(assessmentId = assessment?.assessmentId) {
    if (!assessmentId) return;
    const response = await getAgentAudit(assessmentId);
    setAudit(response as AgentAuditState);
  }

  async function selectTab(tab: TabId) {
    setActiveTab(tab);
    try {
      if (tab === "history") await refreshHistory();
      if (tab === "audit") await refreshAudit();
    } catch (error) {
      setApiError(error instanceof Error ? error.message : "Tab request failed");
    }
  }

  async function runPreflight() {
    setIsRunning(true);
    setApiError(null);
    setRunFeedback("Running guard check...");
    try {
      const result = await runInjectivePreflight({
        prompt,
        address: account,
        subaccountId: DEFAULT_SUBACCOUNT,
        network: "injective_testnet",
        mode: mode === "live" ? "live_read_only" : "demo_scenario"
      });
      setAssessment(result as PreflightAssessment);
      setSimulationVisible(false);
      setActiveTab("overview");
      await Promise.all([refreshHistory(), refreshAudit(result.assessmentId)]);
      setRunFeedback(`Guard check complete · refreshed at ${new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })}`);
    } catch (error) {
      setRunFeedback(null);
      setApiError(error instanceof Error ? error.message : "Pre-flight API request failed");
    } finally {
      setIsRunning(false);
    }
  }

  async function recordProof() {
    if (!assessment) return;
    setIsProofBusy(true);
    setApiError(null);
    try {
      const proof = await recordInjectiveProof({
        assessmentId: assessment.assessmentId,
        assessmentHash: assessment.assessmentHash,
        network: "injective_testnet"
      });
      const next = { ...assessment, proof: proof as ProofRecord };
      setAssessment(next);
      await Promise.all([refreshHistory(), refreshAudit(next.assessmentId)]);
    } catch (error) {
      setApiError(error instanceof Error ? error.message : "Proof record request failed");
    } finally {
      setIsProofBusy(false);
    }
  }

  async function verifyProof() {
    if (!assessment) return;
    setIsProofBusy(true);
    setApiError(null);
    try {
      const proof = await verifyInjectiveProof({
        assessmentHash: assessment.assessmentHash,
        txHash: assessment.proof.txHash,
        network: "injective_testnet"
      });
      const next = { ...assessment, proof: proof as ProofRecord };
      setAssessment(next);
      await Promise.all([refreshHistory(), refreshAudit(next.assessmentId)]);
    } catch (error) {
      setApiError(error instanceof Error ? error.message : "Proof verify request failed");
    } finally {
      setIsProofBusy(false);
    }
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <div>
          <p className="eyebrow">Injective Nova build</p>
          <h1>InjectiveLens Agent Guard</h1>
          <p className="subtitle">A safety and proof layer before AI agents execute trades on Injective.</p>
        </div>
      </header>

      <main className="page">
        <section className="preflight-card" aria-label="Pre-flight check">
          <div className="preflight-heading">
            <p className="eyebrow">Pre-flight check</p>
            <h2>Review an AI trading action before execution.</h2>
            <p>
              The guard parses intent, checks Injective account and market evidence, blocks unsafe actions,
              simulates a safer alternative, and verifies an assessment proof.
            </p>
          </div>

          <div className="preflight-grid">
            <div className="control-column">
              <div className="field">
                <span>Mode</span>
                <div className="segmented">
                  <button className={mode === "demo" ? "active" : ""} onClick={() => handleModeChange("demo")}>
                    Demo trading scenario
                  </button>
                  <button className={mode === "live" ? "active" : ""} onClick={() => handleModeChange("live")}>
                    Live testnet check
                  </button>
                </div>
              </div>

              <label className="field">
                <span>Injective account</span>
                <input value={account} onChange={(event) => handleAccountChange(event.target.value)} />
              </label>

              <p className="safety-note">
                {mode === "live"
                  ? "Read-only check. No wallet connection, private key, seed phrase, signing, order placement, or transaction broadcast."
                  : "Demo replay walkthrough. Proof recording still requires explicit confirmation."}
              </p>

              <div className="status-chips">
                {mode === "demo" ? (
                  <>
                    <span>Mode: demo replay</span>
                    <span>Evidence required</span>
                    <span>No decision until run</span>
                  </>
                ) : (
                  <>
                    <span>Mode: live read-only</span>
                    <span>Sources: Injective endpoints</span>
                    <span>No decision until run</span>
                  </>
                )}
              </div>

              <button className="primary-action" onClick={runPreflight} disabled={isRunning}>
                <Play size={18} /> {isRunning ? "Running guard check..." : "Run agent guard check"}
              </button>

              {apiError && (
                <div className="api-error" role="alert">
                  <AlertTriangle size={17} />
                  <span>{apiError}</span>
                </div>
              )}

              {runFeedback && !apiError && (
                <div className={`run-feedback ${isRunning ? "warning" : "success"}`} role="status">
                  <CheckCircle2 size={17} />
                  <span>{runFeedback}</span>
                </div>
              )}

              {assessment && resultModeMismatch && !apiError && (
                <div className="mode-warning" role="status">
                  <AlertTriangle size={17} />
                  <span>
                    Showing the previous {assessment.mode === "demo" ? "demo replay" : "live read-only"} result.
                    Run the guard check to refresh this view for {mode === "demo" ? "demo replay" : "live read-only"} mode.
                  </span>
                </div>
              )}
            </div>

            <div className="request-column">
              {mode === "demo" ? (
                <>
                  <label className="field">
                    <span>Agent action template</span>
                    <select value={scenarioId} onChange={(event) => handleScenarioChange(event.target.value)}>
                      {scenarios.map((scenario) => (
                        <option key={scenario.id} value={scenario.id}>
                          {scenario.label}
                        </option>
                      ))}
                    </select>
                  </label>

                  <div className="live-source-card demo-source-card">
                    <span>Demo replay context</span>
                    <strong>Scenario fixture · no live execution</strong>
                    <p>{selectedScenario.summary}</p>
                  </div>
                </>
              ) : (
                <div className="live-source-card">
                  <span>Live read-only target</span>
                  <strong>Injective testnet · injective-888</strong>
                  <p>
                    Uses configured read-only account, market, and positions endpoints. If a source is missing,
                    the result is marked partial/unknown instead of safe.
                  </p>
                </div>
              )}

              <label className="field">
                <span>Natural-language trading request</span>
                <textarea value={prompt} onChange={(event) => handlePromptChange(event.target.value)} />
              </label>
            </div>
          </div>
        </section>

        <div className="nav-row">
          <nav className="tabs" aria-label="Main navigation">
            {(["overview", "evidence", "history", "audit"] as TabId[]).map((tab) => (
              <button key={tab} className={activeTab === tab ? "active" : ""} onClick={() => { void selectTab(tab); }}>
                {tab === "overview" && <ClipboardCheck size={18} />}
                {tab === "evidence" && <Database size={18} />}
                {tab === "history" && <History size={18} />}
                {tab === "audit" && <ListChecks size={18} />}
                {tab[0].toUpperCase() + tab.slice(1)}
              </button>
            ))}
          </nav>
        </div>

        {isRestoring && !assessment && (
          <section className="empty-state">
            <Bot size={34} />
            <h2>Restoring latest pre-flight check...</h2>
            <p>Loading the persisted assessment, proof status, history, and decision audit from the backend.</p>
          </section>
        )}

        {!isRestoring && !assessment && (
          <section className="empty-state">
            <Bot size={34} />
            <h2>No pre-flight check yet.</h2>
            <p>Run the guard check to generate a fresh assessment for the selected mode and trading request.</p>
          </section>
        )}

        {assessment && activeTab === "overview" && (
          <Overview
            assessment={assessment}
            simulationVisible={simulationVisible}
            onShowSimulation={() => setSimulationVisible(true)}
            onShowEvidence={() => setActiveTab("evidence")}
            onRecordProof={recordProof}
            onVerifyProof={verifyProof}
            isProofBusy={isProofBusy}
          />
        )}

        {assessment && activeTab === "evidence" && <Evidence assessment={assessment} />}
        {assessment && activeTab === "history" && <HistoryView records={historyRecords} />}
        {assessment && activeTab === "audit" && <Audit assessment={assessment} audit={audit} />}
      </main>
    </div>
  );
}

function Overview({
  assessment,
  simulationVisible,
  onShowSimulation,
  onShowEvidence,
  onRecordProof,
  onVerifyProof,
  isProofBusy
}: {
  assessment: PreflightAssessment;
  simulationVisible: boolean;
  onShowSimulation: () => void;
  onShowEvidence: () => void;
  onRecordProof: () => void;
  onVerifyProof: () => void;
  isProofBusy: boolean;
}) {
  const canRecord = ["ready_to_record", "not_recorded"].includes(assessment.proof.status);
  const canVerify = Boolean(assessment.proof.txHash) && !isProofVerified(assessment.proof);
  const proofRecorded = isProofRecorded(assessment.proof);
  const proofVerified = isProofVerified(assessment.proof);
  return (
    <div className="content-stack">
      <ResultSummaryStrip assessment={assessment} />

      <section className={`hero-card ${severityClass(assessment.decision)}`}>
        <div>
          <p className="eyebrow">{assessment.network}</p>
          <h2>{decisionTitle(assessment)}</h2>
          <p>{assessment.reason}</p>
        </div>
        <div className="score-card">
          <span>Risk score</span>
          <strong>{assessment.riskScore} / 100</strong>
          <em>{assessment.riskLevel}</em>
        </div>
      </section>

      <section className="panel">
        <PanelHeader title="Injective evidence context" description="Read-only account, subaccount, market, and source evidence used by the guard." />
        <div className="summary-grid">
          <Metric label="Network" value="Injective testnet" tone="success" />
          <Metric label="Data mode" value={dataModeLabel(assessment)} tone={sourceStatusTone(assessment)} />
          <Metric label="Account" value={shortValue(assessment.injectiveContext.account)} />
          <Metric label="Subaccount" value={subaccountLabel(assessment)} tone={assessment.injectiveContext.subaccountKind === "simulation_placeholder" ? "warning" : "neutral"} />
          <Metric label="Market" value={marketLabel(assessment)} />
          <Metric label="Mark / oracle" value={formatPricePair(assessment.injectiveContext.markPrice, assessment.injectiveContext.oraclePrice)} />
          <Metric label="Funding" value={formatPercent(assessment.injectiveContext.fundingRatePct)} />
          <Metric label="Source status" value={sourceStatusLabel(assessment)} tone={sourceStatusTone(assessment)} />
        </div>
        {isLivePartialFallback(assessment) && (
          <div className="source-warning">
            <AlertTriangle size={17} />
            <span>Live source partial; using disclosed simulated fallback. Missing live data is treated as unknown, not safe.</span>
          </div>
        )}
      </section>

      <SaferAlternativeCard simulation={assessment.simulation} />

      <section className="panel">
        <PanelHeader title="Core pre-trade signals" description="Evidence-bound signals checked before any agent execution path." />
        <div className="risk-grid">
          {assessment.topRisks.map((risk) => (
            <article className={`risk-card ${severityClass(risk.severity)}`} key={risk.id}>
              <div>
                <h3>{risk.title}</h3>
                <span className={`badge ${severityClass(risk.severity)}`}>{risk.severity}</span>
              </div>
              <p>{risk.claim}</p>
              <small>Confidence {Math.round(risk.confidence * 100)}% · Evidence: {evidenceRefsForRisk(risk)}</small>
            </article>
          ))}
        </div>
      </section>

      <section className="workflow-card">
        <div className="workflow-copy">
          <p className="eyebrow">Review workflow</p>
          <h2>Inspect evidence, simulate safer trade, then record and verify the assessment proof.</h2>
          <p>Use these steps to move from guard result to auditable proof without placing an order.</p>
        </div>
        <div className="workflow-stepper" aria-label="Review workflow steps">
          <button className="workflow-step completed" onClick={onShowEvidence}>
            <Eye size={17} /> Inspect evidence
          </button>
          <button className={simulationVisible ? "workflow-step completed" : "workflow-step"} onClick={onShowSimulation}>
            <Zap size={17} /> Simulate safer trade
          </button>
          <button
            className={proofRecorded ? "workflow-step completed" : "workflow-step"}
            onClick={proofRecorded ? undefined : onRecordProof}
            disabled={!proofRecorded && (!canRecord || isProofBusy)}
            aria-disabled={proofRecorded}
          >
            {proofRecorded ? <CheckCircle2 size={17} /> : <ShieldCheck size={17} />}
            {proofRecorded ? "Proof recorded" : isProofBusy && canRecord ? "Recording..." : "Record proof"}
          </button>
          <button
            className={proofVerified ? "workflow-step completed" : "workflow-step"}
            onClick={proofVerified ? undefined : onVerifyProof}
            disabled={!proofVerified && (!canVerify || isProofBusy)}
            aria-disabled={proofVerified}
          >
            <CheckCircle2 size={17} /> {proofVerified ? "Proof verified" : isProofBusy && canVerify ? "Verifying..." : "Verify proof"}
          </button>
          {assessment.proof.txHash && assessment.proof.explorerUrl && (
            <a className="workflow-step proof-link" href={assessment.proof.explorerUrl} target="_blank" rel="noreferrer">
              <ExternalLink size={17} /> View Injective proof
            </a>
          )}
        </div>
      </section>

      <section className="panel proof-panel">
        <PanelHeader title="Assessment proof" description="Assessment hash, proof transaction, and recorded hash state." />
        <p className="proof-scope-headline">{PROOF_SCOPE_HEADLINE}</p>
        <p className="proof-scope-note">
          {PROOF_SCOPE_NOTE}
        </p>
        <div className="summary-grid">
          <Metric label="Proof status" value={proofLabel(assessment.proof)} tone={proofTone(assessment.proof)} />
          <Metric label="Tx hash" value={assessment.proof.txHash ? shortValue(assessment.proof.txHash) : "Not recorded"} />
          <Metric label="Assessment hash" value={shortValue(assessment.assessmentHash)} />
          <Metric label="Recorded hash" value={assessment.proof.onchainAssessmentHash ? shortValue(assessment.proof.onchainAssessmentHash) : "Awaiting proof recording"} />
        </div>
      </section>

      {simulationVisible && <SimulationPanel simulation={assessment.simulation} />}
    </div>
  );
}

function ResultSummaryStrip({ assessment }: { assessment: PreflightAssessment }) {
  const evidenceCount = buildEvidenceSlots(assessment).length;
  return (
    <section className="result-summary-strip" aria-label="Assessment summary">
      <Metric label="Decision" value={decisionLabel(assessment.decision)} tone={assessment.decision === "block" ? "danger" : assessment.decision === "warn" ? "warning" : "success"} />
      <Metric label="Risk" value={`${assessment.riskScore} / 100`} tone={assessment.decision === "block" ? "danger" : assessment.decision === "warn" ? "warning" : "success"} />
      <Metric label="Network" value="Injective testnet" tone="success" />
      <Metric label="Data mode" value={dataModeLabel(assessment)} tone={sourceStatusTone(assessment)} />
      <Metric label="Evidence" value={`${evidenceCount} bound`} />
      <Metric label="Assessment hash" value={shortValue(assessment.assessmentHash)} />
      <Metric label="Proof status" value={proofLabel(assessment.proof)} tone={proofTone(assessment.proof)} />
    </section>
  );
}

function SaferAlternativeCard({ simulation }: { simulation: Simulation }) {
  return (
    <section className="panel safer-card">
      <PanelHeader
        title="Safer alternative simulated"
        description="The guard blocks risky execution and proposes a lower-risk action for human review."
      />
      <div className="summary-grid">
        <Metric label="Alternative" value={formatIntent(simulation.after)} tone="success" />
        <Metric label="Risk after" value={`${simulation.riskAfter} / 100`} />
        <Metric label="Risk delta" value={`${simulation.riskDelta}`} tone="success" />
        <Metric label="Execution" value="Human confirmation required" tone="warning" />
      </div>
      <p className="simulation-note">{simulation.explanation}</p>
    </section>
  );
}

function Evidence({ assessment }: { assessment: PreflightAssessment }) {
  const evidenceSlots = buildEvidenceSlots(assessment);
  return (
    <div className="content-stack">
      <section className="panel">
        <PanelHeader
          title="Evidence bundle"
          description={`${evidenceSlots.length} evidence items supporting ${assessment.topRisks.length} risk signals.`}
        />
        <div className="summary-grid">
          <Metric label="Data mode" value={dataModeLabel(assessment)} tone={sourceStatusTone(assessment)} />
          <Metric label="Source status" value={sourceStatusLabel(assessment)} tone={sourceStatusTone(assessment)} />
          <Metric label="Coverage mode" value={dataModeLabel(assessment)} tone={sourceStatusTone(assessment)} />
          <Metric label="Proof status" value={proofLabel(assessment.proof)} tone={proofTone(assessment.proof)} />
          <Metric label="Hash" value={assessment.assessmentHash.slice(0, 18) + "..."} />
        </div>
        <p className="coverage-note">{assessment.sourceCoverage.summary}</p>
      </section>

      <section className="panel">
        <PanelHeader title="Risk evidence" description="Human-readable claims first; technical details stay compact." />
        <div className="evidence-list">
          {assessment.topRisks.map((risk) => (
            <article className="evidence-group" key={risk.id}>
              <div className="evidence-group-title">
                <h3>{risk.title}</h3>
                <span className={`badge ${severityClass(risk.severity)}`}>{risk.severity}</span>
              </div>
              <p>
                <strong>Claim:</strong> {risk.claim}
              </p>
              <small>Evidence: {evidenceRefsForRisk(risk)}</small>
            </article>
          ))}
        </div>
      </section>

      <section className="panel">
        <PanelHeader title="Supporting records" description="Six named evidence items used by the guard and proof flow." />
        <div className="evidence-list">
          {evidenceSlots.map((item) => (
            <article className="record-row" key={item.id}>
              <div>
                <h3>{item.id} {item.title}</h3>
                <small>{item.source}</small>
                <p>{item.claim}</p>
                <small>Verification: {item.verification}</small>
                <small>Mode: {item.mode.replaceAll("_", " ")}</small>
                <small>Quality: {item.dataQuality} · Timestamp: {item.timestamp}</small>
              </div>
              <span className="badge neutral">{item.id}</span>
            </article>
          ))}
        </div>
      </section>
    </div>
  );
}

function HistoryView({ records }: { records: HistoryRecord[] }) {
  if (!records.length) {
    return (
      <section className="empty-state">
        <History size={34} />
        <h2>No assessment history yet.</h2>
        <p>Run a pre-flight check to load backend assessment history.</p>
      </section>
    );
  }

  return (
    <div className="content-stack">
      <section className="panel">
        <PanelHeader title="Assessment history & risk trend" description="Recent pre-flight checks with independent proof status." />
        <div className="history-summary">
          <Metric label="Latest score" value={`${records[0].score} / 100`} tone={decisionTone(records[0].decision)} />
          <Metric label="Latest decision" value={decisionLabel(records[0].decision)} tone={decisionTone(records[0].decision)} />
          <Metric label="Data mode" value={historyDataModeLabel(records[0])} tone={records[0].dataMode === "live_read_only" ? "warning" : "neutral"} />
          <Metric label="Proof" value={records[0].proofStatus} tone={records[0].proofVerified || records[0].proofRecorded ? "success" : "neutral"} />
          <Metric label="Open review items" value={String(records[0].risks.length)} />
        </div>
      </section>
      <section className="panel">
        <PanelHeader title="Recent assessments" description="Latest, previous, and changed pre-flight records." />
        <div className="history-list">
          {records.map((record, index) => (
            <article className="history-record" key={record.id}>
              <div>
                <small>{index === 0 ? "Latest assessment" : record.createdAt}</small>
                <h3>{record.score} / 100 · {decisionLabel(record.decision)}</h3>
                <p>Mode: {historyDataModeLabel(record)} · Market source: {record.simulatedMarket ? "Simulated market fixture" : record.marketSource || "Recorded source"}</p>
                <p>Top risks: {record.risks.join(" · ")}</p>
                <p>Proof: {record.proofStatus}</p>
              </div>
              {record.txHash ? (
                <div className="history-proof">
                  <span className="badge success">on-chain</span>
                  <a href={`https://testnet.explorer.injective.network/transaction/${record.txHash}`} target="_blank" rel="noreferrer">
                    View on-chain proof
                  </a>
                </div>
              ) : (
                <span className="badge neutral">not recorded</span>
              )}
            </article>
          ))}
        </div>
      </section>
    </div>
  );
}

function Audit({ assessment, audit }: { assessment: PreflightAssessment; audit: AgentAuditState | null }) {
  const backendAudit = audit?.assessmentId === assessment.assessmentId ? audit : null;
  const hasBackendAudit = Boolean(backendAudit);
  const allowedActions = backendAudit?.allowedActions || assessment.allowedActions;
  const blockedActions = backendAudit?.blockedActions || assessment.blockedActions;
  const toolTrace = backendAudit?.toolTrace || [];
  const llmBoundary =
    backendAudit?.llmBoundary ||
    "The model explains; deterministic policy blocks unsafe execution paths before signing or order placement.";
  const auditPhases = auditPhaseSummaries(assessment);
  const lastChecked = new Date(assessment.createdAt).toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit"
  });
  const agentIdentity = backendAudit?.agentIdentity || {
    agentName: "InjectiveLens Agent Guard",
    agentCardUrl: "/.well-known/agent-card.json",
    registryUrl: "/agent-registration.json",
    mcpUrl: "/mcp"
  };

  return (
    <div className="content-stack">
      <section className="panel">
        <PanelHeader
          title="Decision Audit"
          description={auditIntro(assessment)}
        />
        <div className="audit-grid">
          <Metric label="Decision" value={decisionLabel(assessment.decision)} tone={decisionTone(assessment.decision)} />
          <Metric label="Risk score" value={`${assessment.riskScore} / 100`} tone={decisionTone(assessment.decision)} />
          <Metric label="Simulation" value="Available" tone="success" />
          <Metric label="Proof status" value={proofLabel(assessment.proof)} tone={proofTone(assessment.proof)} />
        </div>
        <p className="audit-reason">{assessment.reason}</p>
        <div className="audit-phase-grid" aria-label="Audit phases">
          {auditPhases.map((phase) => (
            <article className={`audit-phase-card ${phase.tone}`} key={phase.title}>
              <div>
                <h3>{phase.title}</h3>
                <span className={`badge ${phase.tone}`}>{phase.status}</span>
              </div>
              <p>{phase.body}</p>
            </article>
          ))}
        </div>
      </section>

      <section className="panel">
        <PanelHeader
          title="Execution Boundary"
          description="Allowed review/proof actions are separated from blocked execution actions before any signing path."
        />
        <div className="boundary-grid">
          <div className="boundary-list allowed">
            <h3>Allowed after this decision</h3>
            <ul>
              {allowedActions.map((action) => (
                <li key={action}>{boundaryActionLabel(action)}</li>
              ))}
            </ul>
          </div>
          <div className="boundary-list blocked">
            <h3>Blocked by policy</h3>
            <ul>
              {blockedActions.map((action) => (
                <li key={action}>{action}</li>
              ))}
            </ul>
          </div>
        </div>
      </section>

      <section className="panel">
        <PanelHeader
          title="Read-only agent integration surface"
          description="MCP-style read-only agent interface metadata for external agent review; it does not execute trades."
        />
        <div className="summary-grid">
          <Metric label="Agent" value={agentIdentity.agentName} />
          <Metric label="Registry" value="Available" tone="success" />
          <Metric label="Agent card" value="Available" tone="success" />
          <Metric label="MCP tools" value="Read-only" tone="success" />
          <Metric label="Last checked" value={lastChecked} />
        </div>
        <div className="workflow-actions compact-actions">
          <a href={agentIdentity.registryUrl} target="_blank" rel="noreferrer">
            <ExternalLink size={17} /> Agent registry
          </a>
          <a href={agentIdentity.agentCardUrl} target="_blank" rel="noreferrer">
            <ExternalLink size={17} /> Agent card
          </a>
          <a href="/mcp/tools" target="_blank" rel="noreferrer">
            <ExternalLink size={17} /> MCP tools
          </a>
        </div>
      </section>

      <section className="panel">
        <PanelHeader title="Technical agent trace" description="Full tool trace for reviewers who want to inspect the backend decision path." />
        {hasBackendAudit ? (
          <details className="trace-accordion">
            <summary>
              <ListChecks size={18} />
              View technical trace ({toolTrace.length} steps)
            </summary>
            <div className="trace-list">
              {toolTrace.map((event) => (
                <article className={`trace-row ${traceEmphasisClass(event)}`} key={`${event.step}-${event.tool}`}>
                  <span>{event.step}</span>
                  <div>
                    <h3>{event.tool}</h3>
                    <p>{event.summary}</p>
                    {event.evidenceIds && event.evidenceIds.length > 0 && (
                      <small>Evidence refs: {event.evidenceIds.join(", ")}</small>
                    )}
                    {event.actionType && <small>Action boundary: {event.actionType}</small>}
                  </div>
                  <span className={`badge ${traceStatusClass(event.status)}`}>{event.status}</span>
                </article>
              ))}
            </div>
          </details>
        ) : (
          <p className="coverage-note">Loading backend decision audit trace. The summary above stays visible while the audit endpoint responds.</p>
        )}
      </section>

      <section className="panel">
        <PanelHeader title="LLM boundary" description="The model explains; it does not execute or override hard rules." />
        <p>
          This guard never holds private keys, seed phrases, signing rights, transfer permissions, or default
          order-placement permissions.
        </p>
        <p>
          The LLM explains the decision; deterministic policy enforces the execution boundary. {llmBoundary}
        </p>
      </section>
    </div>
  );
}

function SimulationPanel({ simulation }: { simulation: Simulation }) {
  return (
    <section className="panel simulation-panel">
      <PanelHeader title="Safer alternative details" description="No order was placed. This is simulation-only." />
      <div className="simulation-grid">
        <div>
          <small>Before: requested trade</small>
          <strong>{formatIntent(simulation.before)}</strong>
          <span>{simulation.riskBefore} / 100</span>
        </div>
        <div>
          <small>After: safer alternative</small>
          <strong>{formatIntent(simulation.after)}</strong>
          <span>{simulation.riskAfter} / 100</span>
        </div>
        <div>
          <small>Risk delta</small>
          <strong>{simulation.riskDelta}</strong>
          <span>lower score after simulation</span>
        </div>
      </div>
      <p>{simulation.explanation}</p>
    </section>
  );
}

function PanelHeader({ title, description }: { title: string; description: string }) {
  return (
    <div className="panel-header">
      <h2>{title}</h2>
      <p>{description}</p>
    </div>
  );
}

function Metric({ label, value, tone = "neutral" }: { label: string; value: string; tone?: "success" | "warning" | "danger" | "neutral" }) {
  return (
    <div className={`metric-card ${tone}`}>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}
