import type {
  Criticism,
  Decision,
  Experiment,
  Evidence,
  AgentProfile,
  AgentProfilePayload,
  AgentExecutionPlan,
  AgentPrompt,
  AgentPromptVersion,
  HumanReviewAction,
  Hypothesis,
  IdeaVersion,
  OrchestratorResult,
  Project,
  ProjectScore,
  ProjectMetrics,
  ProjectEfficiency,
  Round,
  SystemConfig,
  TimelineItem,
  WorkflowProgress,
  FinanceOverview,
  BillingSync,
  ManualCostPayload,
  ProviderCostEntry,
  DevelopmentBlueprint,
  DevelopmentBlueprintPayload,
  ImprovementPlan,
  JudgeChatTurn,
  JudgeVoiceSession,
  FounderProfile,
  FounderProfilePayload,
  DiscoveryCampaign,
  OpportunitySignal,
  OpportunityCandidate,
  DiscoveryAgentRun,
  DiscoveryHardConstraints,
  CommercialValidationPayload,
  PromptAgent,
} from "@/lib/types";

export const API_URL = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").replace(
  /\/$/,
  "",
);

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, {
    ...init,
    cache: "no-store",
    headers: {
      "Content-Type": "application/json",
      ...init?.headers,
    },
  });
  if (!response.ok) {
    let message = `A API respondeu com status ${response.status}.`;
    try {
      const body = (await response.json()) as { detail?: unknown };
      message = formatApiErrorDetail(body.detail, message);
    } catch {
      // Keep the HTTP fallback when an upstream proxy returns a non-JSON body.
    }
    throw new ApiError(message, response.status);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

const fieldLabels: Record<string, string> = {
  agent_profile_id: "Perfil dos agentes",
  max_ai_budget: "Orçamento máximo",
  name: "Nome do projeto",
  raw_idea: "Descrição da ideia",
};

function formatApiErrorDetail(detail: unknown, fallback: string): string {
  if (typeof detail === "string" && detail.trim()) return detail;
  if (Array.isArray(detail)) {
    const messages = detail.flatMap((item) => {
      if (!item || typeof item !== "object") return [];
      const record = item as { loc?: unknown; msg?: unknown };
      const message = typeof record.msg === "string" ? record.msg : "Valor inválido";
      const location = Array.isArray(record.loc)
        ? record.loc.filter((part): part is string => typeof part === "string" && part !== "body")
        : [];
      const field = location.at(-1);
      return [field ? `${fieldLabels[field] ?? field}: ${message}` : message];
    });
    if (messages.length) return messages.join(" ");
  }
  if (detail && typeof detail === "object") {
    const record = detail as { message?: unknown; msg?: unknown };
    const message = record.message ?? record.msg;
    if (typeof message === "string" && message.trim()) return message;
  }
  return fallback;
}

export const api = {
  listFounderProfiles: () => request<FounderProfile[]>("/founder-profiles"),
  createFounderProfile: (payload: FounderProfilePayload) =>
    request<FounderProfile>("/founder-profiles", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  updateFounderProfile: (id: string, payload: FounderProfilePayload) =>
    request<FounderProfile>(`/founder-profiles/${id}`, {
      method: "PUT",
      body: JSON.stringify(payload),
    }),
  listDiscoveryCampaigns: () => request<DiscoveryCampaign[]>("/discovery-campaigns"),
  getDiscoveryCampaign: (id: string) =>
    request<DiscoveryCampaign>(`/discovery-campaigns/${id}`),
  createDiscoveryCampaign: (payload: {
    founder_profile_id: string;
    agent_profile_id: string | null;
    name: string;
    brief: string;
    geography: string;
    language: string;
    memory_mode: "NEW_ONLY" | "BALANCED" | "IMPROVE_APPROVED";
    hard_constraints: DiscoveryHardConstraints;
    max_ai_budget: string;
    candidate_target: number;
    finalist_target: number;
  }) => request<DiscoveryCampaign>("/discovery-campaigns", {
    method: "POST",
    body: JSON.stringify(payload),
  }),
  runDiscoveryCampaign: (id: string, signal?: AbortSignal) =>
    request<DiscoveryCampaign>(`/discovery-campaigns/${id}/run`, { method: "POST", signal }),
  cancelDiscoveryCampaign: (id: string) =>
    request<DiscoveryCampaign>(`/discovery-campaigns/${id}/cancel`, { method: "POST" }),
  listOpportunitySignals: (id: string) =>
    request<OpportunitySignal[]>(`/discovery-campaigns/${id}/signals`),
  listOpportunityCandidates: (id: string) =>
    request<OpportunityCandidate[]>(`/discovery-campaigns/${id}/opportunities`),
  listDiscoveryRuns: (id: string) =>
    request<DiscoveryAgentRun[]>(`/discovery-campaigns/${id}/runs`),
  promoteOpportunity: (id: string, maxAiBudget: string | null) =>
    request<Project>(`/opportunities/${id}/promote`, {
      method: "POST",
      body: JSON.stringify({ max_ai_budget: maxAiBudget }),
    }),
  updateOpportunityFeedback: (
    id: string,
    payload: { user_feedback: "PENDING" | "APPROVED" | "REJECTED"; feedback_tags: string[]; feedback_note: string | null },
  ) => request<OpportunityCandidate>(`/opportunities/${id}/feedback`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  }),
  updateCommercialValidation: (id: string, payload: CommercialValidationPayload) =>
    request<OpportunityCandidate>(`/opportunities/${id}/commercial-validation`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),
  listProjects: () => request<Project[]>("/projects"),
  getProject: (id: string) => request<Project>(`/projects/${id}`),
  createProject: (payload: {
    name: string;
    raw_idea: string;
    max_ai_budget: string | null;
    agent_profile_id?: string | null;
    agent_plan?: AgentExecutionPlan;
  }) => request<Project>("/projects", { method: "POST", body: JSON.stringify(payload) }),
  updateBudget: (id: string, max_ai_budget: string | null) =>
    request<Project>(`/projects/${id}/budget`, {
      method: "PATCH",
      body: JSON.stringify({ max_ai_budget }),
    }),
  updateProjectProfile: (id: string, agentProfileId: string | null) =>
    request<Project>(`/projects/${id}/agent-profile`, {
      method: "PATCH",
      body: JSON.stringify({ agent_profile_id: agentProfileId }),
    }),
  updateAgentPlan: (id: string, agentPlan: AgentExecutionPlan) =>
    request<Project>(`/projects/${id}/agent-plan`, {
      method: "PATCH",
      body: JSON.stringify({ agent_plan: agentPlan }),
    }),
  updateNextRoundContext: (id: string, nextRoundContext: string | null) =>
    request<Project>(`/projects/${id}/next-round-context`, {
      method: "PATCH",
      body: JSON.stringify({ next_round_context: nextRoundContext }),
    }),
  runProject: (id: string, maxRounds = 3, signal?: AbortSignal) =>
    request<OrchestratorResult>(`/projects/${id}/run`, {
      method: "POST",
      body: JSON.stringify({ max_rounds: maxRounds }),
      signal,
    }),
  getRunStatus: (id: string) =>
    request<WorkflowProgress>(`/projects/${id}/run-status`),
  cancelRun: (id: string) =>
    request<WorkflowProgress>(`/projects/${id}/run-cancel`, { method: "POST" }),
  listVersions: (id: string) => request<IdeaVersion[]>(`/projects/${id}/versions`),
  listScores: (id: string) => request<ProjectScore[]>(`/projects/${id}/scores`),
  listRounds: (id: string) => request<Round[]>(`/projects/${id}/rounds`),
  listHypotheses: (id: string) =>
    request<Hypothesis[]>(`/projects/${id}/hypotheses`),
  listEvidence: (id: string) => request<Evidence[]>(`/projects/${id}/evidence`),
  listCriticisms: (id: string) =>
    request<Criticism[]>(`/projects/${id}/criticisms`),
  listDecisions: (id: string) => request<Decision[]>(`/projects/${id}/decisions`),
  listImprovementPlans: (id: string) =>
    request<ImprovementPlan[]>(`/projects/${id}/improvement-plans`),
  listJudgeChatTurns: (id: string) =>
    request<JudgeChatTurn[]>(`/projects/${id}/judge-chat`),
  runJudgeChatTurn: (id: string, message: string, inputMode: "TEXT" | "VOICE", signal?: AbortSignal) =>
    request<JudgeChatTurn>(`/projects/${id}/judge-chat`, {
      method: "POST",
      body: JSON.stringify({ message, input_mode: inputMode }),
      signal,
    }),
  createJudgeVoiceSession: (id: string) =>
    request<JudgeVoiceSession>(`/projects/${id}/judge-voice/session`, {
      method: "POST",
    }),
  runImprover: (id: string) =>
    request<ImprovementPlan>(`/projects/${id}/improver`, { method: "POST" }),
  listTimeline: (id: string) => request<TimelineItem[]>(`/projects/${id}/timeline`),
  getEfficiency: (id: string) =>
    request<ProjectEfficiency>(`/projects/${id}/efficiency`),
  listExperiments: (id: string) =>
    request<Experiment[]>(`/projects/${id}/experiments`),
  listDevelopmentBlueprints: (id: string) =>
    request<DevelopmentBlueprint[]>(`/projects/${id}/development-blueprints`),
  generateDevelopmentBlueprint: (id: string, payload: DevelopmentBlueprintPayload) =>
    request<DevelopmentBlueprint>(`/projects/${id}/development-blueprints`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  updateExperiment: (
    projectId: string,
    experimentId: string,
    payload: Partial<Pick<Experiment, "experiment_type" | "description" | "success_metric" | "success_threshold" | "estimated_cost" | "actual_cost" | "status" | "outcome" | "result_summary" | "observed_value" | "sample_size" | "methodology" | "limitations">>,
  ) => request<Experiment>(`/projects/${projectId}/experiments/${experimentId}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  }),
  reassessExperiment: (projectId: string, experimentId: string) =>
    request<Experiment>(`/projects/${projectId}/experiments/${experimentId}/reassess`, {
      method: "POST",
    }),
  reviewDecision: (
    projectId: string,
    decisionId: string,
    action: HumanReviewAction,
    note: string | null,
  ) => request<Project>(`/projects/${projectId}/decisions/${decisionId}/review`, {
    method: "POST",
    body: JSON.stringify({ action, note }),
  }),
  listProfiles: () => request<AgentProfile[]>("/agent-profiles"),
  createProfile: (payload: AgentProfilePayload) =>
    request<AgentProfile>("/agent-profiles", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  updateProfile: (id: string, payload: AgentProfilePayload) =>
    request<AgentProfile>(`/agent-profiles/${id}`, {
      method: "PUT",
      body: JSON.stringify(payload),
    }),
  deleteProfile: (id: string) =>
    request<void>(`/agent-profiles/${id}`, { method: "DELETE" }),
  getSystemConfig: () => request<SystemConfig>("/system/config"),
  listPrompts: () => request<AgentPrompt[]>("/agent-prompts"),
  listDiscoveryPrompts: () => request<AgentPrompt[]>("/discovery-prompts"),
  updatePrompt: (agent: AgentPrompt["agent"], content: string) =>
    request<AgentPrompt>(`/agent-prompts/${agent}`, {
      method: "PUT",
      body: JSON.stringify({ content }),
    }),
  resetPrompt: (agent: AgentPrompt["agent"]) =>
    request<AgentPrompt>(`/agent-prompts/${agent}`, { method: "DELETE" }),
  listPromptVersions: (agent: AgentPrompt["agent"]) =>
    request<AgentPromptVersion[]>(`/agent-prompts/${agent}/versions`),
  updateDiscoveryPrompt: (agent: PromptAgent, content: string) =>
    request<AgentPrompt>(`/discovery-prompts/${agent}`, {
      method: "PUT",
      body: JSON.stringify({ content }),
    }),
  resetDiscoveryPrompt: (agent: PromptAgent) =>
    request<AgentPrompt>(`/discovery-prompts/${agent}`, { method: "DELETE" }),
  listDiscoveryPromptVersions: (agent: PromptAgent) =>
    request<AgentPromptVersion[]>(`/discovery-prompts/${agent}/versions`),
  getMetrics: (id: string) => request<ProjectMetrics>(`/projects/${id}/metrics`),
  reportMarkdownUrl: (id: string) => `${API_URL}/projects/${id}/report.md`,
  backupUrl: (id: string) => `${API_URL}/projects/${id}/backup`,
  restoreBackup: (payload: unknown) => request<Project>("/projects/import", {
    method: "POST",
    body: JSON.stringify(payload),
  }),
  getFinanceOverview: (days = 30) =>
    request<FinanceOverview>(`/finance/overview?days=${days}`),
  syncFinanceProvider: (provider: string, days = 30) =>
    request<BillingSync>(`/finance/sync/${encodeURIComponent(provider)}`, {
      method: "POST",
      body: JSON.stringify({ days }),
    }),
  addManualCost: (payload: ManualCostPayload) =>
    request<ProviderCostEntry>("/finance/costs/manual", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
};

export function formatCost(value: string | null): string {
  if (value === null) return "Sem limite";
  return `$${Number(value).toFixed(4)}`;
}

export function formatConfidence(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return `${Math.round(value * 100)}%`;
}
