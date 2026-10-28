from collections import deque
from collections.abc import Sequence
from decimal import Decimal
import json

from app.llm.base import LLMProvider, LLMRequest, LLMResponse
from app.domain.enums import ScoreCriterion


MockResult = str | LLMResponse | Exception


class MockLLMProvider(LLMProvider):
    def __init__(
        self,
        responses: Sequence[MockResult] | None = None,
        *,
        model_name: str = "mock-llm-v1",
    ) -> None:
        self._responses = deque(responses or [])
        self._model_name = model_name
        self.calls: list[LLMRequest] = []

    @property
    def provider_name(self) -> str:
        return self._bound_provider_name or "mock"

    @property
    def model_name(self) -> str:
        return self._model_name

    async def generate(self, request: LLMRequest) -> LLMResponse:
        self.calls.append(request)
        if self._responses:
            configured = self._responses.popleft()
            if isinstance(configured, Exception):
                raise configured
            if isinstance(configured, LLMResponse):
                return configured
            content = configured
        else:
            content = json.dumps(self._default_output(request), ensure_ascii=False)

        return LLMResponse(
            content=content,
            model=self.model_name,
            input_tokens=max(1, len(request.prompt) // 4),
            output_tokens=max(1, len(content) // 4),
            estimated_cost=Decimal("0"),
        )

    @staticmethod
    def _default_output(request: LLMRequest) -> dict[str, object]:
        if request.role == "OPPORTUNITY_SCOUT":
            return {
                "signals": [
                    {
                        "source_title": f"Market signal {index}",
                        "source_url": f"https://example.com/signal-{index}",
                        "pain_statement": f"Teams lose time on recurring workflow {index}.",
                        "audience": "Small service businesses",
                        "evidence_type": "market_observation",
                        "observed_signal": "Repeated requests for a simpler paid solution.",
                        "commercial_signal": "Buyers compare paid alternatives and mention current spend.",
                        "commercial_strength": 4,
                        "strength": 4,
                        "frequency": 4,
                        "willingness_to_pay": 3,
                    }
                    for index in range(1, 6)
                ],
                "search_summary": "Five recurring, commercially relevant pain signals.",
            }
        if request.role == "IDEA_GENERATOR":
            count = int(request.input_data["campaign"]["candidate_target"])
            signals = request.input_data["signals"]
            concepts = [
                ("Invoice Copilot", "late invoice collection"),
                ("Schedule Guard", "last-minute appointment cancellation"),
                ("Proposal Lens", "slow proposal preparation"),
                ("Compliance Inbox", "manual compliance document tracking"),
                ("Review Recovery", "unanswered customer reviews"),
                ("Margin Watch", "hidden service delivery cost"),
                ("Lead Triage", "slow inbound lead qualification"),
                ("Renewal Radar", "missed subscription renewals"),
                ("Scope Shield", "uncontrolled client scope changes"),
                ("Referral Loop", "inconsistent referral follow-up"),
            ]
            return {
                "opportunities": [
                    {
                        "title": concepts[(index - 1) % len(concepts)][0],
                        "problem": f"A measurable {concepts[(index - 1) % len(concepts)][1]} problem.",
                        "target_customer": "Owner-operated service businesses",
                        "solution": f"A narrow digital assistant for workflow {index}.",
                        "business_model": "Monthly subscription with a paid onboarding service.",
                        "acquisition_channel": "Direct outreach in one professional community.",
                        "pricing_hypothesis": "R$149 per month plus onboarding.",
                        "first_revenue_path": "Sell a manual concierge pilot before automation.",
                        "founder_fit_reason": "Matches the founder's available time and technology skills.",
                        "signal_codes": [signals[index % len(signals)]["code"]],
                        "inspired_by_candidate_ids": [],
                        "risks": ["Demand still requires paid validation"],
                        "business_case": {
                            "customer_type": request.input_data["campaign"]["hard_constraints"]["customer_type"],
                            "digital_product": True,
                            "self_service": True,
                            "automation_percent": 95,
                            "mvp_days": 21,
                            "recurring_human_service": False,
                            "regulated_advice": False,
                            "two_sided_marketplace": False,
                            "revenue_pattern": "RECURRING",
                        },
                    }
                    for index in range(1, count + 1)
                ]
            }
        if request.role == "OPPORTUNITY_RESEARCHER":
            return {
                "analyses": [
                    {
                        "candidate_id": item["id"],
                        "demand_evidence": [
                            {"claim": f"Customers pay to address this pain ({index}).", "source_url": f"https://example.com/demand-{index}", "evidence_kind": "purchase_behavior", "supports_purchase_behavior": True}
                            for index in range(1, 4)
                        ],
                        "competitor_evidence": [
                            {"claim": f"Paid competitor {index} publishes pricing.", "source_url": f"https://example.com/competitor-{index}", "evidence_kind": "paid_competitor", "supports_purchase_behavior": True}
                            for index in range(1, 3)
                        ],
                        "objections": ["Switching effort"],
                        "buyer": "The owner who controls the operating budget.",
                        "purchase_event": "A recurring workflow failure creates an urgent need.",
                        "current_spend": "R$100 to R$300 per month on broad tools or manual work.",
                        "purchase_frequency": "Monthly subscription renewal.",
                        "reachable_acquisition_channel": "A focused professional community reachable by direct content.",
                        "gross_margin_estimate": "About 80% after initial automation.",
                        "cac_ceiling": "Up to R$300 at a conservative twelve-month lifetime.",
                        "paid_competitor_count": 2,
                        "direct_purchase_evidence": True,
                        "demand_signal_score": 72,
                        "willingness_to_pay_score": 68,
                        "paid_competitor_score": 70,
                        "channel_score": 70,
                        "recurrence_score": 75,
                        "margin_score": 80,
                        "evidence_quality_score": 65,
                        "recommended_validation": "Offer five paid concierge pilots.",
                        "confidence": 0.64,
                    }
                    for item in request.input_data["candidates"]
                ]
            }
        if request.role == "PORTFOLIO_JUDGE":
            return {
                "evaluations": [
                    {
                        "candidate_id": item["id"],
                        "rationale": "Strong founder fit and a direct validation path.",
                        "pain_severity": 72,
                        "willingness_to_pay": 64,
                        "reachability": 76,
                        "founder_fit": 82,
                        "economics": 70,
                        "speed_to_revenue": 80,
                        "differentiation": 55,
                        "feasibility": 84,
                        "regulatory_safety": 90,
                        "confidence": 0.64,
                        "matched_rejection_tags": [],
                        "validation_plan": ["Contact 20 prospects", "Close three paid pilots"],
                    }
                    for item in request.input_data["candidates"]
                ],
                "portfolio_summary": "Prioritize the opportunities with direct access to buyers.",
            }
        if request.role == "BUILDER":
            return MockLLMProvider._default_builder_output(request)
        if request.role == "CRITIC":
            return MockLLMProvider._default_critic_output()
        if request.role == "RESEARCHER":
            return MockLLMProvider._default_researcher_output(request)
        if request.role == "JUDGE":
            return MockLLMProvider._default_judge_output()
        if request.role == "IMPROVER":
            return MockLLMProvider._default_improver_output(request)
        if request.role == "PRODUCT_ARCHITECT":
            return MockLLMProvider._default_product_architect_output()
        if request.role == "SOLUTION_ARCHITECT":
            return MockLLMProvider._default_solution_architect_output(request)
        if request.role == "TECHNICAL_CRITIC":
            return MockLLMProvider._default_technical_critic_output(request)
        if request.role == "ROADMAP_PLANNER":
            return MockLLMProvider._default_roadmap_output(request)

        raw_idea = str(request.input_data["raw_idea"])
        project_name = str(request.input_data["project_name"])
        return {
            "title": project_name,
            "raw_idea": raw_idea,
            "problem": raw_idea,
            "solution": "The proposed solution requires structuring by a real LLM provider.",
            "target_users": ["To be identified"],
            "value_proposition": "To be validated",
            "possible_use_cases": ["Initial discovery"],
            "business_models": ["Unknown"],
            "technical_assumptions": ["Technical feasibility is unvalidated"],
            "business_assumptions": ["Demand and willingness to pay are unvalidated"],
            "unknowns": ["Problem intensity", "Target segment", "Distribution"],
            "risks": ["Mock output is not evidence"],
            "initial_mvp": "Run a manual problem-validation interview process.",
        }

    @staticmethod
    def _default_builder_output(request: LLMRequest) -> dict[str, object]:
        current_concept = {
            key: value
            for key, value in request.input_data["current_concept"].items()
            if key != "raw_idea"
        }
        return {
            "improvements": [],
            "problems_solved": [],
            "unresolved_problems": ["A real provider has not evaluated the concept"],
            "new_hypotheses": [],
            "proposed_changes": [],
            "new_concept": current_concept,
        }

    @staticmethod
    def _default_critic_output() -> dict[str, object]:
        return {
            "criticisms": [
                {
                    "title": "Concept has not been independently validated",
                    "severity": "MEDIUM",
                    "claim": "The current concept may rely on unsupported assumptions.",
                    "reason": "The deterministic mock provider does not gather evidence.",
                    "affected_hypotheses": [],
                    "evidence_needed": "Independent user and market evidence.",
                    "condition_that_refutes_criticism": (
                        "Relevant evidence validates the concept's core assumptions."
                    ),
                }
            ]
        }

    @staticmethod
    def _default_researcher_output(request: LLMRequest) -> dict[str, object]:
        hypotheses = request.input_data.get("hypotheses", [])
        question = "What evidence is needed to evaluate the current idea?"
        if hypotheses:
            question = f"How can {hypotheses[0]['id']} be tested?"
        return {
            "question": question,
            "finding": "No external evidence was collected by the offline mock.",
            "evidence": [],
            "confidence": 0.0,
            "contradictory_evidence": [],
            "impact_on_project": "The highest-priority assumptions remain open.",
            "recommended_action": (
                "Run a targeted interview, dataset, or document review and add "
                "the resulting source to the evidence ledger."
            ),
        }

    @staticmethod
    def _default_judge_output() -> dict[str, object]:
        criteria = [
            {
                "criterion": criterion.value,
                "rating": 3,
                "rationale": "The mock provider has no evidence for a stronger rating.",
                "evidence_ids": [],
            }
            for criterion in ScoreCriterion
        ]
        return {
            "decision": "RESEARCH",
            "criteria": criteria,
            "confidence": 0.2,
            "reasoning_summary": "The concept is plausible but lacks evidence.",
            "critical_blockers": [],
            "most_important_unknowns": ["Market demand", "Willingness to pay"],
            "next_actions": ["Gather independent evidence"],
        }

    @staticmethod
    def _default_improver_output(request: LLMRequest) -> dict[str, object]:
        breakdown = request.input_data["latest_score"]["breakdown"]
        weakest = min(breakdown, key=lambda item: int(item["rating"]))
        criterion = str(weakest["criterion"])
        rating = int(weakest["rating"])
        return {
            "summary": "The weakest criterion needs a targeted, evidence-backed change.",
            "weaknesses": [
                {
                    "criterion": criterion,
                    "current_rating": rating,
                    "cause_type": "EVIDENCE_GAP",
                    "diagnosis": "The available record does not support a stronger assessment.",
                    "consequence": "The idea cannot progress confidently on this criterion.",
                    "confidence_limit": "Independent evidence is still missing.",
                    "evidence_ids": [],
                }
            ],
            "proposals": [
                {
                    "title": "Validate the weakest criterion",
                    "description": "Collect focused evidence and use it to refine the concept.",
                    "target_criteria": [criterion],
                    "rationale": "Targeted validation is more useful than another textual pass.",
                    "feasibility": 4,
                    "expected_impact": 3,
                    "effort": "LOW",
                    "risks": ["A small sample may remain inconclusive."],
                    "required_evidence": ["Independent observations from the target context."],
                    "validation_step": "Define a measurable threshold and collect representative observations.",
                }
            ],
            "recommended_strategy": "Validate the weakest criterion before broadening the concept.",
            "builder_instructions": ["Change only claims supported by the new evidence."],
            "research_questions": ["What independent evidence resolves the weakest criterion?"],
            "next_steps": ["Collect evidence, then run the Builder and Judge again."],
            "stop_conditions": ["Stop repeating refinement if no new evidence is available."],
        }

    @staticmethod
    def _default_product_architect_output() -> dict[str, object]:
        return {
            "executive_summary": "A development-ready definition generated offline.",
            "goals": ["Deliver the smallest useful product increment"],
            "non_goals": ["Premature scale optimization"],
            "target_users": ["Primary user from the evaluated concept"],
            "core_use_cases": ["Complete the main end-to-end workflow"],
            "functional_requirements": [
                {
                    "id": "FR-001",
                    "description": "Support the primary user workflow.",
                    "priority": "MUST",
                    "acceptance_criteria": ["The workflow completes without manual database changes."],
                }
            ],
            "non_functional_requirements": [
                {
                    "id": "NFR-001",
                    "category": "Reliability",
                    "requirement": "Failures must be visible and recoverable.",
                    "measurable_target": "Every failed request returns a traceable error identifier.",
                }
            ],
            "constraints": ["This mock output is not external evidence."],
            "open_questions": ["Confirm production scale and compliance needs."],
            "evidence_ids": [],
        }

    @staticmethod
    def _default_solution_architect_output(request: LLMRequest) -> dict[str, object]:
        number = int(request.input_data.get("option_number", 1))
        return {
            "option_name": f"Modular baseline {number}",
            "summary": "A modular service with explicit boundaries and incremental delivery.",
            "system_style": "Modular monolith with asynchronous jobs where needed",
            "technology_stack": [
                {
                    "layer": "Application",
                    "technology": "Typed web service",
                    "rationale": "Keeps boundaries explicit without early distributed complexity.",
                }
            ],
            "components": [
                {
                    "name": "Core application",
                    "responsibility": "Own the primary workflow and business rules.",
                    "interfaces": ["HTTP API"],
                    "data_owned": ["Application records"],
                }
            ],
            "data_flows": ["Client request → application validation → persistence → response"],
            "api_contracts": ["Versioned JSON API for the primary workflow"],
            "data_model": ["Primary record with immutable audit metadata"],
            "security_controls": ["Authentication, authorization, validation, and audit logging"],
            "infrastructure": ["Application runtime and managed relational database"],
            "observability": ["Structured logs, request metrics, and error tracing"],
            "deployment_strategy": "Automated staged deployment with rollback.",
            "tradeoffs": ["Lower operational complexity at the cost of shared deployment."],
            "risks": ["Scale and compliance requirements remain unconfirmed."],
            "evidence_ids": [],
        }

    @staticmethod
    def _default_technical_critic_output(request: LLMRequest) -> dict[str, object]:
        options = request.input_data["architecture_options"]
        name = str(options[0]["option_name"])
        return {
            "recommended_option": name,
            "recommendation_reason": "It minimizes irreversible complexity for the current evidence level.",
            "option_assessments": [
                {
                    "option_name": str(option["option_name"]),
                    "strengths": ["Incremental delivery"],
                    "weaknesses": ["Production constraints still need confirmation"],
                    "delivery_risk": 4,
                    "suitability": 7,
                }
                for option in options
            ],
            "findings": [
                {
                    "severity": "MEDIUM",
                    "category": "Requirements",
                    "issue": "Expected production load is unknown.",
                    "impact": "Capacity choices may be premature.",
                    "mitigation": "Measure load and define scaling thresholds before production.",
                }
            ],
            "required_changes": ["Add explicit capacity and rollback thresholds."],
            "unresolved_risks": ["Compliance and production load are unconfirmed."],
        }

    @staticmethod
    def _default_roadmap_output(request: LLMRequest) -> dict[str, object]:
        name = str(request.input_data["architecture_options"][0]["option_name"])
        return {
            "selected_option": name,
            "decision_rationale": "The option supports staged delivery with limited initial complexity.",
            "architecture_adjustments": ["Add explicit rollback and audit controls."],
            "phases": [
                {
                    "number": 1,
                    "name": "Foundation",
                    "objective": "Establish the deployable product skeleton and primary workflow.",
                    "deliverables": ["Versioned API", "Persistence", "Deployment pipeline"],
                    "dependencies": [],
                    "acceptance_criteria": ["The primary workflow passes automated tests."],
                }
            ],
            "initial_backlog": [
                {
                    "id": "BL-001",
                    "title": "Implement the primary workflow",
                    "description": "Deliver FR-001 through the selected architecture.",
                    "phase": 1,
                    "priority": "MUST",
                    "acceptance_criteria": ["FR-001 acceptance criteria pass."],
                }
            ],
            "testing_strategy": ["Unit, integration, contract, and end-to-end tests in CI"],
            "security_plan": ["Threat model, least privilege, secret isolation, and dependency scanning"],
            "deployment_plan": ["Staged deployment with health checks and rollback"],
            "observability_plan": ["Structured logs, metrics, traces, and actionable alerts"],
            "operational_plan": ["Runbook, backup restore test, and incident ownership"],
            "traceability": [
                {"requirement_id": "FR-001", "evidence_ids": [], "delivered_in_phase": 1},
                {"requirement_id": "NFR-001", "evidence_ids": [], "delivered_in_phase": 1},
            ],
            "risks": ["Unconfirmed scale and compliance requirements"],
            "unresolved_questions": ["What load and regulatory constraints apply?"],
        }
