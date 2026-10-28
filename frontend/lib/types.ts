export type ProjectStatus =
  | "DRAFT"
  | "STRUCTURING"
  | "RESEARCHING"
  | "DEBATING"
  | "VALIDATING"
  | "PIVOTING"
  | "AWAITING_CONFIRMATION"
  | "APPROVED"
  | "DISCARDED"
  | "BUILDING";

export type DecisionType =
  | "REFINE"
  | "RESEARCH"
  | "TEST"
  | "PIVOT"
  | "APPROVE"
  | "DISCARD";

export interface AgentExecutionPlan {
  builder: number;
  researcher: number;
  critic: number;
}

export interface Project {
  id: string;
  name: string;
  raw_idea: string;
  agent_profile_id: string | null;
  agent_plan: AgentExecutionPlan;
  status: ProjectStatus;
  total_cost: string;
  max_ai_budget: string | null;
  next_round_context: string | null;
  remaining_ai_budget: string | null;
  budget_exhausted: boolean;
  stagnation_detected: boolean;
  created_at: string;
  updated_at: string;
}

export interface IdeaConcept {
  title: string;
  raw_idea: string;
  problem: string;
  solution: string;
  target_users: string[];
  value_proposition: string;
  possible_use_cases: string[];
  business_models: string[];
  technical_assumptions: string[];
  business_assumptions: string[];
  unknowns: string[];
  risks: string[];
  initial_mvp: string;
}

export interface IdeaVersion {
  id: string;
  project_id: string;
  version: number;
  parent_version_id: string | null;
  reason_for_change: string;
  created_by: string;
  changes: string[];
  concept: IdeaConcept;
  created_at: string;
}

export interface ProjectScore {
  id: string;
  total_score: number;
  confidence: number;
  breakdown: Array<{
    criterion: ScoreCriterion;
    rating: number;
    weight: number;
    weighted_score: number;
    rationale: string;
    evidence_ids: string[];
  }>;
  created_at: string;
}

export interface ImprovementPlan {
  id: string;
  project_id: string;
  round_id: string | null;
  idea_version_id: string;
  score_id: string;
  decision_id: string;
  agent_run_id: string;
  version: number;
  source_score: number;
  source_confidence: number;
  plan: {
    summary: string;
    weaknesses: Array<{
      criterion: ScoreCriterion;
      current_rating: number;
      cause_type: "CONCEPT_WEAKNESS" | "EVIDENCE_GAP" | "FEASIBILITY_RISK" | "MARKET_RISK" | "EXECUTION_RISK" | "REGULATORY_RISK";
      diagnosis: string;
      consequence: string;
      confidence_limit: string;
      evidence_ids: string[];
    }>;
    proposals: Array<{
      title: string;
      description: string;
      target_criteria: ScoreCriterion[];
      rationale: string;
      feasibility: number;
      expected_impact: number;
      effort: "LOW" | "MEDIUM" | "HIGH";
      risks: string[];
      required_evidence: string[];
      validation_step: string;
    }>;
    recommended_strategy: string;
    builder_instructions: string[];
    research_questions: string[];
    next_steps: string[];
    stop_conditions: string[];
  };
  created_at: string;
}

export interface Round {
  id: string;
  round_number: number;
  status: "RUNNING" | "COMPLETED" | "FAILED" | "CANCELLED";
  decision: DecisionType | null;
  score: number | null;
  confidence: number | null;
  budget_limit_reached: boolean;
  stagnation_detected: boolean;
  error: string | null;
  human_context: string | null;
  started_at: string;
  completed_at: string | null;
}

export interface Hypothesis {
  id: string;
  statement: string;
  category: string;
  impact: number;
  confidence: number;
  priority: number;
  status: "OPEN" | "PARTIAL" | "VALIDATED" | "REJECTED";
  epistemic_classification: string;
  origin: string;
}

export interface Evidence {
  id: string;
  source: string;
  source_type: string;
  claim: string;
  hypothesis_id: string;
  direction: "SUPPORT" | "CONTRADICT" | "NEUTRAL";
  strength: number;
  epistemic_classification: string;
  url: string;
  date: string | null;
  origin: "USER" | "RESEARCHER" | "EXPERIMENT";
  created_at: string;
}

export interface Criticism {
  id: string;
  title: string;
  severity: "CRITICAL" | "HIGH" | "MEDIUM" | "LOW";
  claim: string;
  reason: string;
  evidence_needed: string;
  condition_that_refutes_criticism: string;
  created_at: string;
}

export interface Decision {
  id: string;
  round_number: number | null;
  decision: DecisionType;
  reason: string;
  score: number;
  confidence: number;
  critical_blockers: string[];
  most_important_unknowns: string[];
  next_actions: string[];
  human_review_status: "NOT_REQUIRED" | "PENDING" | "ACCEPTED" | "OVERRIDDEN";
  human_action: HumanReviewAction | null;
  human_note: string | null;
  reviewed_at: string | null;
  created_at: string;
}

export interface JudgeChatTurn {
  id: string;
  project_id: string;
  decision_id: string | null;
  user_message: string;
  input_mode: "TEXT" | "VOICE";
  status: "RUNNING" | "COMPLETED" | "NO_DECISION" | "CANCELLED" | "BUDGET_STOPPED" | "FAILED";
  requested_rounds: number;
  judge_response: string | null;
  stop_reason: OrchestratorResult["stop_reason"] | null;
  error: string | null;
  decision: DecisionType | null;
  score: number | null;
  confidence: number | null;
  cost_before: string;
  cost_after: string;
  created_at: string;
  completed_at: string | null;
}

export interface JudgeVoiceSession {
  client_secret: string;
  expires_at: number | null;
  model: string;
  voice: string;
  max_duration_seconds: number;
}

export type HumanReviewAction =
  | "ACCEPT_RECOMMENDATION"
  | "CONTINUE_ANYWAY"
  | "MANUAL_PIVOT";

export type ScoreCriterion =
  | "REAL_PROBLEM"
  | "PROBLEM_INTENSITY"
  | "IDENTIFIABLE_USERS"
  | "MARKET"
  | "DIFFERENTIATION"
  | "TECHNICAL_FEASIBILITY"
  | "ECONOMIC_FEASIBILITY"
  | "DISTRIBUTION"
  | "DEFENSIBILITY"
  | "LEGAL_REGULATORY_RISK"
  | "TESTABLE_MVP"
  | "SCALABILITY";

export interface Experiment {
  id: string;
  project_id: string;
  decision_id: string | null;
  hypothesis_id: string | null;
  experiment_type: string;
  description: string;
  success_metric: string | null;
  success_threshold: string | null;
  estimated_cost: string;
  actual_cost: string;
  status: "PLANNED" | "RUNNING" | "COMPLETED" | "CANCELLED";
  outcome: "SUCCESS" | "FAILURE" | "INCONCLUSIVE" | null;
  result_summary: string | null;
  observed_value: string | null;
  sample_size: number | null;
  methodology: string | null;
  limitations: string | null;
  evidence_id: string | null;
  evidence_quality: number | null;
  affected_criteria: ScoreCriterion[];
  reassessment_status: "NOT_REQUESTED" | "PENDING" | "COMPLETED" | "FAILED" | "SKIPPED_BUDGET";
  previous_score: number | null;
  previous_confidence: number | null;
  reassessed_score: number | null;
  reassessed_confidence: number | null;
  reassessment_score_id: string | null;
  reassessment_decision_id: string | null;
  reassessment_error: string | null;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
}

export interface AgentProfileModel {
  provider: string;
  model: string;
  input_cost_per_million: string;
  cached_input_cost_per_million: string | null;
  output_cost_per_million: string;
}

export interface AgentProfile {
  id: string;
  name: string;
  description: string;
  agents: Record<TimelineItem["agent"], AgentProfileModel>;
  created_at: string;
  updated_at: string;
}

export interface AgentProfilePayload {
  name: string;
  description: string;
  agents: AgentProfile["agents"];
}

export interface ProviderDiagnostic extends AgentProfileModel {
  agent: TimelineItem["agent"];
  credential_configured: boolean;
  pricing_configured: boolean;
}

export interface SystemConfig {
  app_name: string;
  app_env: string;
  max_rounds: number;
  max_attempts: number;
  max_output_tokens: number;
  builder_max_output_tokens: number;
  adaptive_agent_depth_enabled: boolean;
  adaptive_depth_score_threshold: number;
  adaptive_depth_confidence_threshold: number;
  research_web_enabled: boolean;
  research_web_max_calls: number;
  research_web_context_size: "low" | "medium" | "high";
  web_search_cost_per_call: string;
  providers: ProviderDiagnostic[];
}

export type PromptAgent = TimelineItem["agent"]
  | "OPPORTUNITY_SCOUT"
  | "IDEA_GENERATOR"
  | "OPPORTUNITY_RESEARCHER"
  | "PORTFOLIO_JUDGE";

export interface AgentPrompt {
  agent: PromptAgent;
  content: string;
  version: string;
  customized: boolean;
  default_content: string;
  default_version: string;
  updated_at: string | null;
}

export interface AgentPromptVersion {
  id: string;
  agent: PromptAgent;
  version: number;
  content: string;
  is_active: boolean;
  created_at: string;
}

export interface AgentMetric {
  agent: TimelineItem["agent"];
  provider: string;
  model: string;
  runs: number;
  successful_runs: number;
  failed_runs: number;
  input_tokens: number;
  output_tokens: number;
  cached_input_tokens: number;
  reasoning_tokens: number;
  estimated_cost: string;
  average_execution_time: number;
}

export interface ProjectMetrics {
  project_id: string;
  total_runs: number;
  total_input_tokens: number;
  total_output_tokens: number;
  total_estimated_cost: string;
  by_agent: AgentMetric[];
}

export interface RoundEfficiency {
  round_number: number;
  status: Round["status"];
  calls: number;
  failed_calls: number;
  input_tokens: number;
  cached_input_tokens: number;
  output_tokens: number;
  reasoning_tokens: number;
  input_payload_characters: number;
  largest_input_payload_characters: number;
  estimated_cost: string;
  score: number | null;
  confidence: number | null;
  score_delta: number | null;
  confidence_delta: number | null;
  cost_per_score_point: string | null;
}

export interface ProjectEfficiency {
  project_id: string;
  rounds: RoundEfficiency[];
  total_round_cost: string;
  recommendation: string;
  recommendation_reason: string;
}

export interface TimelineItem {
  id: string;
  round_id: string | null;
  round_number: number | null;
  agent:
    | "STRUCTURER"
    | "BUILDER"
    | "RESEARCHER"
    | "CRITIC"
    | "JUDGE"
    | "IMPROVER"
    | "PRODUCT_ARCHITECT"
    | "SOLUTION_ARCHITECT"
    | "TECHNICAL_CRITIC"
    | "ROADMAP_PLANNER";
  provider: string;
  model: string;
  prompt_version: string;
  input_tokens: number;
  output_tokens: number;
  cached_input_tokens: number;
  reasoning_tokens: number;
  web_search_calls: number;
  tool_cost: string;
  web_sources: Array<{ url: string; title: string }>;
  estimated_cost: string;
  succeeded: boolean;
  error: string | null;
  created_at: string;
}

export interface DevelopmentBlueprint {
  id: string;
  project_id: string;
  version: number;
  status: "RUNNING" | "COMPLETED" | "FAILED";
  architecture_alternatives: number;
  user_context: string | null;
  max_ai_budget: string | null;
  estimated_cost: string;
  product_definition: null | {
    executive_summary: string;
    goals: string[];
    non_goals: string[];
    target_users: string[];
    core_use_cases: string[];
    functional_requirements: Array<{
      id: string;
      description: string;
      priority: "MUST" | "SHOULD" | "COULD";
      acceptance_criteria: string[];
    }>;
    non_functional_requirements: Array<{
      id: string;
      category: string;
      requirement: string;
      measurable_target: string;
    }>;
    constraints: string[];
    open_questions: string[];
    evidence_ids: string[];
  };
  architecture_options: Array<{
    option_name: string;
    summary: string;
    system_style: string;
    technology_stack: Array<{ layer: string; technology: string; rationale: string }>;
    components: Array<{
      name: string;
      responsibility: string;
      interfaces: string[];
      data_owned: string[];
    }>;
    data_flows: string[];
    api_contracts: string[];
    data_model: string[];
    security_controls: string[];
    infrastructure: string[];
    observability: string[];
    deployment_strategy: string;
    tradeoffs: string[];
    risks: string[];
    evidence_ids: string[];
  }>;
  technical_review: null | {
    recommended_option: string;
    recommendation_reason: string;
    option_assessments: Array<{
      option_name: string;
      strengths: string[];
      weaknesses: string[];
      delivery_risk: number;
      suitability: number;
    }>;
    findings: Array<{
      severity: "CRITICAL" | "HIGH" | "MEDIUM" | "LOW";
      category: string;
      issue: string;
      impact: string;
      mitigation: string;
    }>;
    required_changes: string[];
    unresolved_risks: string[];
  };
  final_blueprint: null | {
    selected_option: string;
    decision_rationale: string;
    architecture_adjustments: string[];
    phases: Array<{
      number: number;
      name: string;
      objective: string;
      deliverables: string[];
      dependencies: string[];
      acceptance_criteria: string[];
    }>;
    initial_backlog: Array<{
      id: string;
      title: string;
      description: string;
      phase: number;
      priority: "MUST" | "SHOULD" | "COULD";
      acceptance_criteria: string[];
    }>;
    testing_strategy: string[];
    security_plan: string[];
    deployment_plan: string[];
    observability_plan: string[];
    operational_plan: string[];
    traceability: Array<{
      requirement_id: string;
      evidence_ids: string[];
      delivered_in_phase: number;
    }>;
    risks: string[];
    unresolved_questions: string[];
  };
  agent_run_ids: string[];
  error: string | null;
  created_at: string;
  completed_at: string | null;
}

export interface DevelopmentBlueprintPayload {
  architecture_alternatives: number;
  user_context: string | null;
  max_ai_budget: string | null;
}

export interface OrchestratorResult {
  project_id: string;
  project_status: ProjectStatus;
  rounds: Round[];
  final_decision: DecisionType | null;
  final_score: number | null;
  final_confidence: number | null;
  stop_reason:
    | "TERMINAL_DECISION"
    | "AWAITING_CONFIRMATION"
    | "AWAITING_TEST"
    | "BUDGET_LIMIT_REACHED"
    | "MAX_ROUNDS_REACHED"
    | "USER_CANCELLED";
}

export interface WorkflowProgress {
  project_id: string;
  status: "IDLE" | "RUNNING" | "CANCELLING";
  current_agent: TimelineItem["agent"] | null;
  workflow_stage: string | null;
  current_round: number | null;
  round_position: number | null;
  requested_rounds: number | null;
  agent_iteration: number | null;
  agent_iterations: number | null;
  started_at: string | null;
  updated_at: string | null;
}

export interface ProviderCostEntry {
  id: string;
  provider: string;
  source: "PROVIDER_API" | "MANUAL";
  period_start: string;
  period_end: string;
  amount: string;
  currency: string;
  model: string | null;
  line_item: string | null;
  external_project_id: string | null;
  external_api_key_id: string | null;
  quantity: string | null;
  quantity_unit: string | null;
  details: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface BillingSync {
  id: string;
  provider: string;
  status: "COMPLETED" | "FAILED";
  period_start: string;
  period_end: string;
  entries_seen: number;
  entries_written: number;
  error: string | null;
  started_at: string;
  completed_at: string;
}

export interface FinanceOverview {
  generated_at: string;
  period_start: string;
  period_end: string;
  currency: string;
  summary: {
    estimated_cost: string;
    reconciled_cost: string;
    variance: string;
    all_time_estimated_cost: string;
    configured_budget: string;
    total_runs: number;
    input_tokens: number;
    output_tokens: number;
    cached_input_tokens: number;
    reasoning_tokens: number;
    web_search_calls: number;
    tool_cost: string;
    projects_at_or_over_budget: number;
    unpriced_runs: number;
    unsupported_currency_entries: number;
  };
  by_provider: Array<{
    provider: string;
    estimated_cost: string;
    reconciled_cost: string;
    variance: string;
    runs: number;
    input_tokens: number;
    output_tokens: number;
    web_search_calls: number;
    tool_cost: string;
    models: string[];
    connector_configured: boolean;
    last_synced_at: string | null;
  }>;
  by_model: Array<{
    provider: string;
    model: string;
    runs: number;
    input_tokens: number;
    output_tokens: number;
    cached_input_tokens: number;
    reasoning_tokens: number;
    web_search_calls: number;
    tool_cost: string;
    estimated_cost: string;
    reconciled_cost: string | null;
  }>;
  by_agent: Array<{
    agent: TimelineItem["agent"];
    runs: number;
    input_tokens: number;
    output_tokens: number;
    web_search_calls: number;
    tool_cost: string;
    estimated_cost: string;
  }>;
  by_project: Array<{
    project_id: string;
    name: string;
    status: ProjectStatus;
    runs: number;
    period_estimated_cost: string;
    all_time_estimated_cost: string;
    max_ai_budget: string | null;
    remaining_ai_budget: string | null;
    budget_exhausted: boolean;
  }>;
  daily: Array<{
    date: string;
    estimated_cost: string;
    reconciled_cost: string;
  }>;
  connectors: Array<{
    provider: string;
    configured: boolean;
    supports_sync: boolean;
    last_sync_status: BillingSync["status"] | null;
    last_synced_at: string | null;
    guidance: string;
  }>;
  recent_cost_entries: ProviderCostEntry[];
  recent_syncs: BillingSync[];
}

export interface ManualCostPayload {
  provider: string;
  period_start: string;
  period_end: string;
  amount: string;
  currency: "USD";
  model: string | null;
  line_item: string | null;
  note: string | null;
}

export type RiskTolerance = "LOW" | "MEDIUM" | "HIGH";
export type DiscoveryCampaignStatus =
  | "DRAFT"
  | "RUNNING"
  | "COMPLETED"
  | "BUDGET_STOPPED"
  | "FAILED"
  | "CANCELLED";
export type OpportunityStatus =
  | "GENERATED"
  | "SHORTLISTED"
  | "FINALIST"
  | "REJECTED"
  | "SELECTED";
export type OpportunityFeedbackStatus = "PENDING" | "APPROVED" | "REJECTED";
export type DiscoveryMemoryMode = "NEW_ONLY" | "BALANCED" | "IMPROVE_APPROVED";
export type OpportunityCustomerType = "ANY" | "B2C" | "B2B";
export type CommercialValidationStatus =
  | "UNTESTED"
  | "PLANNED"
  | "RUNNING"
  | "VALIDATED"
  | "INVALIDATED"
  | "INCONCLUSIVE";

export interface DiscoveryHardConstraints {
  customer_type: OpportunityCustomerType;
  digital_only: boolean;
  self_service_only: boolean;
  min_automation_percent: number;
  max_mvp_days: number;
  exclude_recurring_human_service: boolean;
  exclude_regulated_advice: boolean;
  exclude_two_sided_marketplaces: boolean;
  require_recurring_or_repeat_revenue: boolean;
  require_reachable_channel: boolean;
  min_demand_sources: number;
  min_paid_competitors: number;
  min_market_reality_score: number;
}

export interface FounderProfilePayload {
  name: string;
  skills: string[];
  industries: string[];
  available_capital: string;
  currency: string;
  hours_per_week: number;
  target_monthly_revenue: string;
  revenue_horizon_days: number;
  preferred_business_models: string[];
  preferred_markets: string[];
  distribution_assets: string[];
  technologies: string[];
  exclusions: string[];
  risk_tolerance: RiskTolerance;
}

export interface FounderProfile extends FounderProfilePayload {
  id: string;
  created_at: string;
  updated_at: string;
}

export interface DiscoveryCampaign {
  id: string;
  founder_profile_id: string;
  agent_profile_id: string | null;
  name: string;
  brief: string;
  geography: string;
  language: string;
  memory_mode: DiscoveryMemoryMode;
  hard_constraints: DiscoveryHardConstraints;
  status: DiscoveryCampaignStatus;
  max_ai_budget: string;
  total_cost: string;
  candidate_target: number;
  finalist_target: number;
  cancellation_requested: boolean;
  current_stage: string | null;
  error: string | null;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface OpportunitySignal {
  id: string;
  code: string;
  sequence: number;
  source_title: string;
  source_url: string;
  pain_statement: string;
  audience: string;
  evidence_type: string;
  observed_signal: string;
  commercial_signal: string;
  commercial_strength: number;
  strength: number;
  frequency: number;
  willingness_to_pay: number;
  created_at: string;
}

export interface OpportunityCandidate {
  id: string;
  project_id: string | null;
  title: string;
  problem: string;
  target_customer: string;
  solution: string;
  business_model: string;
  acquisition_channel: string;
  pricing_hypothesis: string;
  first_revenue_path: string;
  founder_fit_reason: string;
  signal_codes: string[];
  inspired_by_candidate_ids: string[];
  risks: string[];
  business_case: {
    customer_type?: OpportunityCustomerType;
    digital_product?: boolean;
    self_service?: boolean;
    automation_percent?: number;
    mvp_days?: number;
    recurring_human_service?: boolean;
    regulated_advice?: boolean;
    two_sided_marketplace?: boolean;
    revenue_pattern?: "RECURRING" | "REPEAT" | "ONE_OFF";
  };
  hard_constraint_passed: boolean;
  disqualification_reasons: string[];
  research: {
    demand_evidence?: Array<{ claim: string; source_url: string }>;
    competitor_evidence?: Array<{ claim: string; source_url: string }>;
    objections?: string[];
    recommended_validation?: string;
    judge_rationale?: string;
    validation_plan?: string[];
    confidence?: number;
    buyer?: string;
    purchase_event?: string;
    current_spend?: string;
    purchase_frequency?: string;
    reachable_acquisition_channel?: string;
    gross_margin_estimate?: string;
    cac_ceiling?: string;
    paid_competitor_count?: number;
    direct_purchase_evidence?: boolean;
    demand_signal_score?: number;
    willingness_to_pay_score?: number;
    paid_competitor_score?: number;
    channel_score?: number;
    recurrence_score?: number;
    margin_score?: number;
    evidence_quality_score?: number;
    preference_adjustment?: number;
    matched_rejection_tags?: string[];
  };
  scores: Record<string, number>;
  preliminary_score: number;
  market_reality_score: number | null;
  market_gate_passed: boolean;
  overall_score: number | null;
  confidence: number | null;
  rank: number | null;
  status: OpportunityStatus;
  user_feedback: OpportunityFeedbackStatus;
  feedback_tags: string[];
  feedback_note: string | null;
  feedback_at: string | null;
  validation_status: CommercialValidationStatus;
  validation_result: {
    channel?: string;
    hypothesis?: string;
    visits?: number;
    leads?: number;
    preorders?: number;
    paying_customers?: number;
    revenue?: string;
    spend?: string;
    currency?: string;
    notes?: string;
    lead_rate?: number;
    purchase_rate?: number;
    revenue_multiple?: number | null;
    score_delta?: number;
    confidence_delta?: number;
    market_reality_delta?: number;
  };
  created_at: string;
}

export interface CommercialValidationPayload {
  status: CommercialValidationStatus;
  channel: string;
  hypothesis: string;
  visits: number;
  leads: number;
  preorders: number;
  paying_customers: number;
  revenue: string;
  spend: string;
  currency: string;
  notes: string;
}

export interface DiscoveryAgentRun {
  id: string;
  agent: string;
  provider: string;
  model: string;
  prompt_version: string;
  input_tokens: number;
  output_tokens: number;
  cached_input_tokens: number;
  reasoning_tokens: number;
  web_search_calls: number;
  tool_cost: string;
  web_sources: Array<{ title?: string; url?: string }>;
  estimated_cost: string;
  execution_time: number;
  error: string | null;
  created_at: string;
}
