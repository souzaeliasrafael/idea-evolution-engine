"use client";

import Link from "next/link";
import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";

import { StatusBadge } from "@/components/dashboard";
import { JudgeChat } from "@/components/judge-chat";
import { api, formatConfidence, formatCost } from "@/lib/api";
import type {
  AgentExecutionPlan,
  AgentProfile,
  Criticism,
  Decision,
  DevelopmentBlueprint,
  Evidence,
  Experiment,
  HumanReviewAction,
  Hypothesis,
  IdeaConcept,
  IdeaVersion,
  ImprovementPlan,
  JudgeChatTurn,
  Project,
  ProjectScore,
  ProjectEfficiency,
  ProjectMetrics,
  Round,
  ScoreCriterion,
  TimelineItem,
  WorkflowProgress,
} from "@/lib/types";

const agentDepthOptions = [
  { value: 0, label: "0 · Desativado" },
  { value: 1, label: "1 · Padrão" },
  { value: 2, label: "2 · Aprofundado" },
  { value: 3, label: "3 · Intensivo" },
];

const scoreCriterionLabels: Record<ScoreCriterion, string> = {
  REAL_PROBLEM: "Problema real",
  PROBLEM_INTENSITY: "Intensidade do problema",
  IDENTIFIABLE_USERS: "Usuários identificáveis",
  MARKET: "Mercado",
  DIFFERENTIATION: "Diferenciação",
  TECHNICAL_FEASIBILITY: "Viabilidade técnica",
  ECONOMIC_FEASIBILITY: "Viabilidade econômica",
  DISTRIBUTION: "Distribuição",
  DEFENSIBILITY: "Defensibilidade",
  LEGAL_REGULATORY_RISK: "Risco regulatório",
  TESTABLE_MVP: "MVP testável",
  SCALABILITY: "Escalabilidade",
};

function isAbortError(value: unknown): boolean {
  return value instanceof DOMException && value.name === "AbortError";
}

interface Snapshot {
  project: Project;
  versions: IdeaVersion[];
  scores: ProjectScore[];
  rounds: Round[];
  hypotheses: Hypothesis[];
  evidence: Evidence[];
  criticisms: Criticism[];
  decisions: Decision[];
  improvements: ImprovementPlan[];
  timeline: TimelineItem[];
  experiments: Experiment[];
  blueprints: DevelopmentBlueprint[];
  metrics: ProjectMetrics;
  efficiency: ProjectEfficiency;
  profiles: AgentProfile[];
  judgeChatTurns: JudgeChatTurn[];
}

export function ProjectDetail({ projectId }: { projectId: string }) {
  const [data, setData] = useState<Snapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [budgetBusy, setBudgetBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [budget, setBudget] = useState("");
  const [profileId, setProfileId] = useState("");
  const [agentPlan, setAgentPlan] = useState<AgentExecutionPlan>({
    builder: 1,
    researcher: 1,
    critic: 1,
  });
  const [reviewNote, setReviewNote] = useState("");
  const [nextRoundContext, setNextRoundContext] = useState("");
  const [executionProgress, setExecutionProgress] = useState<WorkflowProgress | null>(null);
  const [stopping, setStopping] = useState(false);
  const [blueprintBusy, setBlueprintBusy] = useState(false);
  const [blueprintAlternatives, setBlueprintAlternatives] = useState(2);
  const [blueprintContext, setBlueprintContext] = useState("");
  const [blueprintBudget, setBlueprintBudget] = useState("");
  const [experimentBusyId, setExperimentBusyId] = useState<string | null>(null);
  const activeRunController = useRef<AbortController | null>(null);

  const load = useCallback(async () => {
    const [project, versions, scores, rounds, hypotheses, evidence, criticisms, decisions, improvements, timeline, experiments, blueprints, metrics, efficiency, profiles, judgeChatTurns, runStatus] =
      await Promise.all([
        api.getProject(projectId),
        api.listVersions(projectId),
        api.listScores(projectId),
        api.listRounds(projectId),
        api.listHypotheses(projectId),
        api.listEvidence(projectId),
        api.listCriticisms(projectId),
        api.listDecisions(projectId),
        api.listImprovementPlans(projectId),
        api.listTimeline(projectId),
        api.listExperiments(projectId),
        api.listDevelopmentBlueprints(projectId),
        api.getMetrics(projectId),
        api.getEfficiency(projectId),
        api.listProfiles(),
        api.listJudgeChatTurns(projectId),
        api.getRunStatus(projectId),
      ]);
    setData({ project, versions, scores, rounds, hypotheses, evidence, criticisms, decisions, improvements, timeline, experiments, blueprints, metrics, efficiency, profiles, judgeChatTurns });
    setBudget(project.max_ai_budget ?? "");
    setProfileId(project.agent_profile_id ?? "");
    setAgentPlan(project.agent_plan);
    setNextRoundContext(project.next_round_context ?? "");
    setExecutionProgress(runStatus);
    if (runStatus.status !== "IDLE") setBusy(true);
  }, [projectId]);

  useEffect(() => {
    let active = true;
    setLoading(true);
    load()
      .catch((caught) => {
        if (active) setError(caught instanceof Error ? caught.message : "Falha ao carregar o projeto.");
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [load]);

  useEffect(() => {
    if (!executionProgress || executionProgress.status === "IDLE") return;
    let active = true;
    let timer: ReturnType<typeof setTimeout> | undefined;

    async function poll() {
      try {
        const next = await api.getRunStatus(projectId);
        if (!active) return;
        setExecutionProgress(next);
        if (next.status === "IDLE") {
          setBusy(false);
          await load();
          return;
        }
      } catch {
        // A transient polling failure must not interrupt the workflow request.
      }
      if (active) timer = setTimeout(() => void poll(), 1000);
    }

    timer = setTimeout(() => void poll(), 700);
    return () => {
      active = false;
      if (timer) clearTimeout(timer);
    };
  }, [executionProgress?.status, load, projectId]);

  const latestVersion = data?.versions.at(-1) ?? null;
  const latestScore = data?.scores.at(-1) ?? null;
  const latestRound = data?.rounds.at(-1) ?? null;
  const latestDecision = data?.decisions.at(-1) ?? null;
  const latestBlueprint = data?.blueprints.at(0) ?? null;
  const sortedHypotheses = useMemo(
    () => [...(data?.hypotheses ?? [])].sort((a, b) => b.priority - a.priority),
    [data?.hypotheses],
  );

  async function runWorkflow() {
    setBusy(true);
    setError(null);
    setNotice(null);
    const startedAt = new Date().toISOString();
    setExecutionProgress({
      project_id: projectId,
      status: "RUNNING",
      current_agent: null,
      workflow_stage: null,
      current_round: null,
      round_position: null,
      requested_rounds: 3,
      agent_iteration: null,
      agent_iterations: null,
      started_at: startedAt,
      updated_at: startedAt,
    });
    const controller = new AbortController();
    activeRunController.current = controller;
    try {
      const result = await api.runProject(projectId, 3, controller.signal);
      setNotice(result.stop_reason === "USER_CANCELLED"
        ? "Execução interrompida com segurança. Nenhum novo agente será iniciado."
        : `Execução encerrada: ${result.stop_reason.replaceAll("_", " ")}.`);
      await load();
    } catch (caught) {
      if (!isAbortError(caught)) {
        setError(caught instanceof Error ? caught.message : "A execução não pôde ser concluída.");
      }
      await load().catch(() => undefined);
    } finally {
      if (activeRunController.current === controller) activeRunController.current = null;
      setBusy(false);
      setExecutionProgress(null);
    }
  }

  async function stopWorkflow() {
    setStopping(true);
    setError(null);
    try {
      const progress = await api.cancelRun(projectId);
      activeRunController.current?.abort();
      setExecutionProgress(progress);
      setNotice("Execução interrompida: a tarefa e a conexão HTTP ativa foram canceladas.");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Não foi possível solicitar a parada.");
    } finally {
      setStopping(false);
    }
  }

  async function runJudgeChat(message: string, inputMode: "TEXT" | "VOICE"): Promise<JudgeChatTurn> {
    setBusy(true);
    setError(null);
    setNotice(null);
    const startedAt = new Date().toISOString();
    setExecutionProgress({
      project_id: projectId,
      status: "RUNNING",
      current_agent: null,
      workflow_stage: null,
      current_round: null,
      round_position: null,
      requested_rounds: 1,
      agent_iteration: null,
      agent_iterations: null,
      started_at: startedAt,
      updated_at: startedAt,
    });
    const controller = new AbortController();
    activeRunController.current = controller;
    try {
      const turn = await api.runJudgeChatTurn(projectId, message, inputMode, controller.signal);
      setNotice(turn.status === "COMPLETED"
        ? "O Judge respondeu depois de executar o ciclo completo."
        : turn.judge_response ?? "A conversa foi registrada.");
      await load();
      return turn;
    } catch (caught) {
      if (!isAbortError(caught)) {
        setError(caught instanceof Error ? caught.message : "O Judge não conseguiu concluir a conversa.");
      }
      await load().catch(() => undefined);
      throw caught;
    } finally {
      if (activeRunController.current === controller) activeRunController.current = null;
      setBusy(false);
      setExecutionProgress(null);
    }
  }

  async function updateBudget(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBudgetBusy(true);
    setError(null);
    setNotice(null);
    try {
      const updated = await api.updateBudget(projectId, budget.trim() ? budget : null);
      setData((current) => current ? { ...current, project: updated } : current);
      setBudget(updated.max_ai_budget ?? "");
      setNotice(
        executionProgress !== null && executionProgress.status !== "IDLE"
          ? "Orçamento atualizado. O novo teto será aplicado antes do próximo agente."
          : "Orçamento atualizado.",
      );
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Não foi possível atualizar o orçamento.");
    } finally {
      setBudgetBusy(false);
    }
  }

  async function updateProfile(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await api.updateProjectProfile(projectId, profileId || null);
      setNotice(profileId ? "Perfil do projeto atualizado." : "Projeto restaurado para a configuração padrão.");
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Não foi possível trocar o perfil.");
    } finally {
      setBusy(false);
    }
  }

  async function updateAgentPlan(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (agentPlan.builder + agentPlan.researcher + agentPlan.critic === 0) {
      setError("Mantenha ao menos Builder, Researcher ou Critic ativo.");
      return;
    }
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await api.updateAgentPlan(projectId, agentPlan);
      setNotice("Foco dos agentes atualizado para as próximas rodadas.");
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Não foi possível atualizar o foco dos agentes.");
    } finally {
      setBusy(false);
    }
  }

  async function saveNextRoundContext(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const value = nextRoundContext.trim();
    if (!value) {
      setError("Digite as informações para a próxima rodada ou use Limpar.");
      return;
    }
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await api.updateNextRoundContext(projectId, value);
      setNotice("Informações salvas para a próxima rodada.");
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Não foi possível salvar as informações.");
    } finally {
      setBusy(false);
    }
  }

  async function clearNextRoundContext() {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await api.updateNextRoundContext(projectId, null);
      setNextRoundContext("");
      setNotice("Informações da próxima rodada removidas.");
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Não foi possível limpar as informações.");
    } finally {
      setBusy(false);
    }
  }

  async function reviewDecision(action: HumanReviewAction) {
    if (!latestDecision) return;
    if (action === "MANUAL_PIVOT" && !reviewNote.trim()) {
      setError("Descreva as instruções do pivô manual.");
      return;
    }
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await api.reviewDecision(projectId, latestDecision.id, action, reviewNote.trim() || null);
      setReviewNote("");
      setNotice("Decisão humana registrada.");
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Não foi possível registrar a decisão.");
    } finally {
      setBusy(false);
    }
  }

  async function saveExperiment(experimentId: string, payload: Parameters<typeof api.updateExperiment>[2]) {
    setExperimentBusyId(experimentId);
    setError(null);
    setNotice(null);
    try {
      if (payload.status === "COMPLETED") {
        setNotice("Salvando o experimento e registrando a evidência…");
      }
      const updated = await api.updateExperiment(projectId, experimentId, payload);
      setNotice(experimentNotice(updated));
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Não foi possível atualizar o experimento.");
    } finally {
      setExperimentBusyId(null);
    }
  }

  async function reassessExperiment(experimentId: string) {
    if (executionProgress !== null && executionProgress.status !== "IDLE") {
      setError("Aguarde a execução atual terminar ou use “Parar execução” antes de chamar o Judge novamente.");
      return;
    }
    setExperimentBusyId(experimentId);
    setError(null);
    setNotice("Preparando a evidência e reavaliando o projeto com o Judge…");
    try {
      const updated = await api.reassessExperiment(projectId, experimentId);
      setNotice(experimentNotice(updated));
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Não foi possível reavaliar o experimento.");
    } finally {
      setExperimentBusyId(null);
    }
  }

  async function runImprover() {
    setBusy(true);
    setError(null);
    setNotice("Improver analisando os critérios fracos e as alternativas viáveis…");
    try {
      const plan = await api.runImprover(projectId);
      setNotice(`Plano de melhoria V${plan.version} criado a partir do score ${plan.source_score}.`);
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Não foi possível gerar o plano de melhoria.");
    } finally {
      setBusy(false);
    }
  }

  async function generateBlueprint(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBlueprintBusy(true);
    setError(null);
    setNotice(null);
    try {
      const generated = await api.generateDevelopmentBlueprint(projectId, {
        architecture_alternatives: blueprintAlternatives,
        user_context: blueprintContext.trim() || null,
        max_ai_budget: blueprintBudget.trim() || null,
      });
      setNotice(`Blueprint de desenvolvimento V${generated.version} concluído.`);
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Não foi possível gerar o blueprint de desenvolvimento.");
      await load().catch(() => undefined);
    } finally {
      setBlueprintBusy(false);
    }
  }

  if (loading) {
    return <div className="page-shell"><div className="state-card">Carregando avaliação…</div></div>;
  }
  if (!data) {
    return (
      <div className="page-shell">
        <div className="alert alert-error">{error ?? "Projeto não encontrado."}</div>
        <Link className="back-link" href="/">← Voltar aos projetos</Link>
      </div>
    );
  }

  const terminal = ["APPROVED", "DISCARDED"].includes(data.project.status);
  const pendingReview = latestDecision?.human_review_status === "PENDING";
  const hasOpenExperiment = data.experiments.some((item) => ["PLANNED", "RUNNING"].includes(item.status));
  const budgetPercent = data.project.max_ai_budget
    ? Math.min(100, (Number(data.project.total_cost) / Math.max(Number(data.project.max_ai_budget), 0.000001)) * 100)
    : null;
  const workflowIsActive = executionProgress !== null && executionProgress.status !== "IDLE";
  const runBlockReason = terminal
    ? "Este projeto já recebeu uma decisão final."
    : pendingReview
      ? "Registre a confirmação humana antes de iniciar outra rodada."
      : hasOpenExperiment
        ? "O Judge solicitou um teste. Conclua ou cancele o experimento aberto para liberar a próxima rodada."
        : data.project.budget_exhausted
          ? "O orçamento foi atingido. Aumente ou remova o teto para continuar."
          : null;

  return (
    <div className="page-shell project-page">
      <Link className="back-link" href="/">← Voltar aos projetos</Link>
      <section className="project-header">
        <div className="project-title-block">
          <div className="title-line">
            <p className="eyebrow">Projeto {data.project.id.slice(0, 8)}</p>
            <StatusBadge status={data.project.status} />
          </div>
          <h1>{data.project.name}</h1>
          <p>{data.project.raw_idea}</p>
        </div>
        <div className="header-metrics">
          <HeaderStat label="Score" value={latestScore ? `${latestScore.total_score}` : "—"} />
          <HeaderStat label="Confiança" value={formatConfidence(latestScore?.confidence)} />
          <HeaderStat label="Rodada" value={latestRound ? `${latestRound.round_number}` : "0"} />
          <HeaderStat label="Custo estimado" value={formatCost(data.project.total_cost)} />
        </div>
        <div className="header-actions">
          <button
            className="button"
            disabled={busy || terminal || pendingReview || hasOpenExperiment || data.project.budget_exhausted}
            onClick={() => void runWorkflow()}
            title={runBlockReason ?? undefined}
            type="button"
          >
            {workflowIsActive ? "Execução em andamento…" : "Executar até 3 rodadas"}
          </button>
          <form className="budget-form" onSubmit={updateBudget}>
            <label htmlFor="budget">Teto de IA</label>
            <div>
              <input
                id="budget"
                min="0"
                step="0.000001"
                inputMode="decimal"
                placeholder="Sem limite"
                value={budget}
                onChange={(event) => setBudget(event.target.value)}
              />
              <button className="button button-secondary" disabled={budgetBusy} type="submit">{budgetBusy ? "Salvando…" : "Salvar"}</button>
            </div>
            <small>Durante uma execução, o novo teto vale a partir do próximo agente; a chamada atual não é alterada.</small>
          </form>
        </div>
        {budgetPercent !== null && (
          <div className="budget-summary">
            <div>
              <span>{formatCost(data.project.total_cost)} usados</span>
              <span>{formatCost(data.project.remaining_ai_budget)} restantes</span>
            </div>
            <div className="budget-track large" role="progressbar" aria-valuenow={budgetPercent} aria-valuemin={0} aria-valuemax={100}>
              <span style={{ width: `${budgetPercent}%` }} />
            </div>
          </div>
        )}
      </section>

      {error && <div className="alert alert-error">{error}</div>}
      {notice && <div className="alert alert-success">{notice}</div>}
      {workflowIsActive && (
        <WorkflowProgressCard
          progress={executionProgress}
          plan={data.project.agent_plan}
          stopping={stopping}
          onStop={() => void stopWorkflow()}
        />
      )}
      {data.project.budget_exhausted && (
        <div className="alert alert-warning">O orçamento foi atingido. Aumente ou remova o teto para iniciar novas chamadas.</div>
      )}
      {hasOpenExperiment && (
        <div className="alert alert-warning">
          <strong>Próxima rodada bloqueada por um experimento planejado.</strong>
          O Judge escolheu TEST. Na seção Experimentos, preencha o resultado e marque como Concluído; ou marque como Cancelado para seguir sem esse resultado.
        </div>
      )}
      {data.project.stagnation_detected && (
        <div className="alert alert-warning">Estagnação detectada: três melhorias consecutivas ficaram abaixo de 3 pontos. O Judge deixa de aceitar refinamentos textuais repetidos.</div>
      )}
      {latestRound?.error && latestRound.status === "COMPLETED" && (
        <div className="alert alert-warning">
          <strong>A rodada foi concluída com recuperação automática.</strong> {latestRound.error}
        </div>
      )}
      {blueprintBusy && (
        <div className="workflow-progress" role="status" aria-live="polite">
          <span className="progress-spinner" aria-hidden="true" />
          <div className="workflow-progress-copy">
            <span>Blueprint em elaboração</span>
            <strong>Arquitetos e crítico técnico estão processando o histórico do projeto</strong>
            <small>O fluxo grava cada etapa e o custo separadamente. Esta operação não cria experimentos nem código executável.</small>
          </div>
        </div>
      )}
      {pendingReview && latestDecision && (
        <section className="review-box">
          <div>
            <p className="eyebrow">Confirmação humana necessária</p>
            <h2>O Judge recomenda {latestDecision.decision}</h2>
            <p>{latestDecision.reason}</p>
          </div>
          <textarea
            maxLength={5000}
            placeholder="Observação opcional; obrigatória para pivô manual"
            rows={3}
            value={reviewNote}
            onChange={(event) => setReviewNote(event.target.value)}
          />
          <div className="review-actions">
            <button className="button" disabled={busy} onClick={() => void reviewDecision("ACCEPT_RECOMMENDATION")} type="button">Aceitar recomendação</button>
            <button className="button button-secondary" disabled={busy} onClick={() => void reviewDecision("CONTINUE_ANYWAY")} type="button">Continuar mesmo assim</button>
            <button className="button button-secondary" disabled={busy} onClick={() => void reviewDecision("MANUAL_PIVOT")} type="button">Pivotar manualmente</button>
          </div>
        </section>
      )}

      <JudgeChat
        blockReason={runBlockReason}
        disabled={busy || workflowIsActive || Boolean(runBlockReason)}
        onSend={runJudgeChat}
        projectId={projectId}
        turns={data.judgeChatTurns}
      />

      <form className="next-round-context" onSubmit={saveNextRoundContext}>
        <div>
          <p className="eyebrow">Orientação humana</p>
          <h2>Informações para a próxima rodada</h2>
          <p>
            O histórico estruturado das rodadas anteriores continua incluído automaticamente. Este texto será enviado ao Builder, Researcher, Critic e Judge na primeira rodada da próxima execução e removido depois que ela for concluída.
          </p>
        </div>
        <textarea
          disabled={workflowIsActive || terminal}
          maxLength={20000}
          placeholder="Ex.: Considere que o cliente-alvo são pequenas operadoras rurais; priorize custo baixo e funcionamento offline."
          rows={4}
          value={nextRoundContext}
          onChange={(event) => setNextRoundContext(event.target.value)}
        />
        <div className="next-round-context-actions">
          <small>{nextRoundContext.length.toLocaleString("pt-BR")} / 20.000 caracteres</small>
          {data.project.next_round_context && (
            <button className="button button-secondary" disabled={busy || workflowIsActive || terminal} onClick={() => void clearNextRoundContext()} type="button">
              Limpar
            </button>
          )}
          <button
            className="button"
            disabled={busy || workflowIsActive || terminal || !nextRoundContext.trim() || nextRoundContext.trim() === (data.project.next_round_context ?? "")}
            type="submit"
          >
            Salvar para a próxima rodada
          </button>
        </div>
      </form>

      <section className="content-grid">
        <div className="content-main">
          <ScoreEvolution scores={data.scores} decisions={data.decisions} experiments={data.experiments} />

          <EfficiencyPanel efficiency={data.efficiency} />

          <ImprovementPlanPanel
            disabled={busy || workflowIsActive || data.project.budget_exhausted || !latestDecision || terminal}
            latest={data.improvements[0] ?? null}
            onRun={() => void runImprover()}
            total={data.improvements.length}
          />

          <Panel title="Conceito atual" meta={latestVersion ? `V${latestVersion.version} · ${latestVersion.created_by}` : "Ainda não estruturado"}>
            {latestVersion ? <ConceptView concept={latestVersion.concept} /> : <p className="muted">Execute o fluxo para criar a versão inicial.</p>}
          </Panel>

          <Panel
            title="Desenvolvimento"
            meta={latestBlueprint ? `Blueprint V${latestBlueprint.version} · ${latestBlueprint.status}` : "Opcional"}
          >
            <form className="blueprint-form" onSubmit={generateBlueprint}>
              <div>
                <h3>Transformar a pesquisa em um plano de construção</h3>
                <p>
                  Usa conceito, Researcher, críticas, evidências e decisões para gerar requisitos, alternativas de arquitetura, revisão técnica, fases e backlog. Não cria experimento nem executável.
                </p>
              </div>
              <div className="blueprint-fields">
                <label>
                  Alternativas de arquitetura
                  <select value={blueprintAlternatives} onChange={(event) => setBlueprintAlternatives(Number(event.target.value))}>
                    <option value={1}>1 · Direta</option>
                    <option value={2}>2 · Comparar abordagens</option>
                    <option value={3}>3 · Exploração ampla</option>
                  </select>
                </label>
                <label>
                  Teto desta geração (USD, opcional)
                  <input min="0.000001" placeholder="Usa o teto geral" step="0.000001" type="number" value={blueprintBudget} onChange={(event) => setBlueprintBudget(event.target.value)} />
                </label>
              </div>
              <label>
                Orientações para o desenvolvimento (opcional)
                <textarea
                  maxLength={20000}
                  placeholder="Ex.: priorize implantação local, baixo custo operacional e uma primeira fase para dois desenvolvedores."
                  rows={4}
                  value={blueprintContext}
                  onChange={(event) => setBlueprintContext(event.target.value)}
                />
              </label>
              <div className="blueprint-actions">
                <small>{blueprintAlternatives + 3} chamadas de agentes previstas, além de possíveis tentativas de correção.</small>
                <button
                  className="button"
                  disabled={blueprintBusy || busy || workflowIsActive || data.project.budget_exhausted || !latestVersion}
                  type="submit"
                >
                  {blueprintBusy ? "Gerando blueprint…" : latestBlueprint ? "Gerar nova versão" : "Gerar blueprint"}
                </button>
              </div>
            </form>
            {latestBlueprint && <DevelopmentBlueprintView blueprint={latestBlueprint} />}
          </Panel>

          <Panel title="Experimentos" meta={`${data.experiments.length} registrados`}>
            {data.experiments.length === 0 ? (
              <p className="muted">Decisões TEST criam automaticamente um experimento planejado.</p>
            ) : (
              <div className="experiment-list">
                {data.experiments.map((item) => (
                  <ExperimentEditor
                    busy={experimentBusyId === item.id || (busy && !workflowIsActive)}
                    item={item}
                    key={item.id}
                    onReassess={reassessExperiment}
                    onSave={saveExperiment}
                    workflowActive={workflowIsActive}
                  />
                ))}
              </div>
            )}
          </Panel>
        </div>

        <aside className="content-side">
          <Panel title="Decisão atual" meta={latestDecision ? `Rodada ${latestDecision.round_number ?? "manual"}` : undefined}>
            {latestDecision ? (
              <div className="decision-card">
                <span className={`decision decision-${latestDecision.decision.toLowerCase()}`}>{latestDecision.decision}</span>
                <div className="decision-score"><strong>{latestDecision.score}</strong><span>{formatConfidence(latestDecision.confidence)} confiança</span></div>
                <p>{latestDecision.reason}</p>
                {latestDecision.next_actions.length > 0 && <TextList title="Próximas ações" items={latestDecision.next_actions} />}
              </div>
            ) : <p className="muted">Ainda não há decisão do Judge.</p>}
          </Panel>

          <Panel title="Timeline" meta={`${data.timeline.length} execuções`}>
            {data.timeline.length === 0 ? <p className="muted">Nenhum agente executado.</p> : (
              <ol className="timeline">
                {data.timeline.map((item) => (
                  <li className={item.succeeded ? "" : "timeline-failed"} key={item.id}>
                    <span className="timeline-dot" />
                    <div><strong>{item.agent}</strong><span>{item.round_number ? `Rodada ${item.round_number}` : "Estruturação"} · {item.provider} / {item.model}</span><small>{formatCost(item.estimated_cost)} · {item.input_tokens + item.output_tokens} tokens{item.web_search_calls > 0 ? ` · ${item.web_search_calls} busca(s) web (${formatCost(item.tool_cost)})` : ""}</small>{item.error && <em>{item.error}</em>}</div>
                  </li>
                ))}
              </ol>
            )}
          </Panel>

          <Panel title="Histórico" meta={`${data.decisions.length} decisões`}>
            {data.decisions.length === 0 ? <p className="muted">Sem histórico ainda.</p> : (
              <div className="history-list">
                {[...data.decisions].reverse().map((item) => (
                  <div key={item.id}><span className={`decision mini decision-${item.decision.toLowerCase()}`}>{item.decision}</span><strong>{item.score} pontos</strong><small>{new Date(item.created_at).toLocaleString("pt-BR")}</small></div>
                ))}
              </div>
            )}
          </Panel>

          <Panel title="Operação" meta={`${data.metrics.total_runs} execuções`}>
            <form className="project-profile-form" onSubmit={updateProfile}>
              <label htmlFor="project-profile">Perfil dos agentes</label>
              <div>
                <select id="project-profile" value={profileId} onChange={(event) => setProfileId(event.target.value)}>
                  <option value="">Configuração padrão do servidor</option>
                  {data.profiles.map((profile) => <option key={profile.id} value={profile.id}>{profile.name}</option>)}
                </select>
                <button className="button button-secondary" disabled={busy || profileId === (data.project.agent_profile_id ?? "")} type="submit">Aplicar</button>
              </div>
              <small>A troca afeta somente as próximas chamadas. <Link href="/profiles">Gerenciar perfis</Link></small>
            </form>
            <form className="agent-plan-form" onSubmit={updateAgentPlan}>
              <div>
                <strong>Profundidade máxima por rodada</strong>
                <small>A primeira passagem usa um agente por etapa; chamadas extras só são liberadas quando score ou confiança indicam necessidade.</small>
              </div>
              <div className="agent-plan-grid compact">
                {(["builder", "researcher", "critic"] as const).map((agent) => (
                  <label key={agent}>
                    {agent === "builder" ? "Builder · 2 etapas" : agent === "researcher" ? "Researcher · 2 etapas" : "Critic"}
                    <select
                      value={agentPlan[agent]}
                      onChange={(event) => setAgentPlan((current) => ({
                        ...current,
                        [agent]: Number(event.target.value),
                      }))}
                    >
                      {agentDepthOptions.map((option) => (
                        <option key={option.value} value={option.value}>{option.label}</option>
                      ))}
                    </select>
                  </label>
                ))}
              </div>
              <small>
                Builder e Researcher aparecem em duas etapas. Structurer, Judge e Improver permanecem automáticos; tudo respeita o teto de IA.
              </small>
              <button
                className="button button-secondary"
                disabled={busy || JSON.stringify(agentPlan) === JSON.stringify(data.project.agent_plan)}
                type="submit"
              >
                Salvar foco
              </button>
            </form>
            <div className="operation-links">
              <a className="button button-secondary" href={api.reportMarkdownUrl(projectId)}>Baixar relatório</a>
              <a className="button button-secondary" href={api.backupUrl(projectId)}>Exportar backup</a>
            </div>
            <div className="agent-metrics">
              {data.metrics.by_agent.map((item) => (
                <div key={`${item.agent}-${item.provider}-${item.model}`}><strong>{item.agent}</strong><span>{item.provider} / {item.model}</span><small>{item.runs} chamadas · {item.input_tokens + item.output_tokens} tokens · {formatCost(item.estimated_cost)}</small></div>
              ))}
            </div>
          </Panel>
        </aside>
      </section>

      <Panel title="Problemas críticos" meta={`${data.criticisms.length} registros`}>
        {data.criticisms.length === 0 ? (
          <p className="muted">Nenhuma crítica registrada ainda.</p>
        ) : (
          <div className="criticism-list">
            {data.criticisms.map((item) => <CriticismCard item={item} key={item.id} />)}
          </div>
        )}
      </Panel>

      <Panel title="Hipóteses" meta={`${sortedHypotheses.length} registradas`}>
        {sortedHypotheses.length === 0 ? (
          <p className="muted">As hipóteses aparecerão depois da estruturação.</p>
        ) : (
          <div className="table-wrap">
            <table>
              <thead><tr><th>Hipótese</th><th>Impacto</th><th>Confiança</th><th>Prioridade</th><th>Status</th></tr></thead>
              <tbody>
                {sortedHypotheses.map((item) => (
                  <tr key={item.id}>
                    <td><span className="mono-id">{item.id}</span><strong>{item.statement}</strong><small>{item.category} · {item.epistemic_classification}</small></td>
                    <td>{item.impact}/10</td>
                    <td>{formatConfidence(item.confidence)}</td>
                    <td><strong>{item.priority.toFixed(2)}</strong></td>
                    <td><span className="table-status">{item.status}</span></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>

      <Panel title="Evidências" meta={`${data.evidence.length} fontes registradas`}>
        {data.evidence.length === 0 ? (
          <p className="muted">As fontes usadas pelo Researcher aparecerão aqui depois da próxima pesquisa.</p>
        ) : (
          <div className="evidence-list">
            {[...data.evidence].reverse().map((item) => (
              <article key={item.id}>
                <div>
                  <span className="mono-id">{item.id}</span>
                  <strong>{item.source}</strong>
                  <small>{item.source_type} · {item.hypothesis_id} · {item.direction} · força {item.strength}/5</small>
                </div>
                <p>{item.claim}</p>
                {item.url && <a href={item.url} target="_blank" rel="noreferrer">Abrir fonte original ↗</a>}
              </article>
            ))}
          </div>
        )}
      </Panel>
    </div>
  );
}

function HeaderStat({ label, value }: { label: string; value: string }) {
  return <div><span>{label}</span><strong>{value}</strong></div>;
}

const workflowAgentLabels: Record<TimelineItem["agent"], string> = {
  STRUCTURER: "Structurer",
  BUILDER: "Builder",
  RESEARCHER: "Researcher",
  CRITIC: "Critic",
  JUDGE: "Judge",
  IMPROVER: "Improver",
  PRODUCT_ARCHITECT: "Product Architect",
  SOLUTION_ARCHITECT: "Solution Architect",
  TECHNICAL_CRITIC: "Technical Critic",
  ROADMAP_PLANNER: "Roadmap Planner",
};

function WorkflowProgressCard({
  progress,
  plan,
  stopping,
  onStop,
}: {
  progress: WorkflowProgress;
  plan: AgentExecutionPlan;
  stopping: boolean;
  onStop: () => void;
}) {
  const stages: Array<{ agent: TimelineItem["agent"]; label: string; count: number }> = [
    { agent: "STRUCTURER", label: "Estruturação inicial", count: 1 },
    { agent: "RESEARCHER", label: "Pesquisa inicial", count: plan.researcher },
    { agent: "BUILDER", label: "Enriquecimento após pesquisa", count: plan.builder },
    { agent: "CRITIC", label: "Crítica do conteúdo acumulado", count: plan.critic },
    { agent: "RESEARCHER", label: "Verificação das críticas", count: plan.researcher },
    { agent: "BUILDER", label: "Enriquecimento final", count: plan.builder },
    { agent: "JUDGE", label: "Julgamento final", count: 1 },
    { agent: "IMPROVER", label: "Plano de melhoria", count: 1 },
  ];
  const agentLabel = progress.current_agent ? workflowAgentLabels[progress.current_agent] : "agente atual";
  const cancelling = progress.status === "CANCELLING";
  const iterationLabel = progress.agent_iterations && progress.agent_iterations > 1
    ? ` ${progress.agent_iteration ?? "…"}/${progress.agent_iterations}`
    : "";
  const headline = cancelling
    ? `Interrompendo ${agentLabel} e fechando a conexão ativa`
    : progress.current_agent === "STRUCTURER"
      ? "Structurer preparando a versão inicial"
      : progress.current_agent
        ? `Rodada ${progress.round_position ?? "…"} de até ${progress.requested_rounds ?? "…"} — ${progress.workflow_stage ?? agentLabel}${iterationLabel}`
        : "Preparando a execução dos agentes";

  return (
    <section className="workflow-progress" role="status" aria-live="polite" aria-atomic="true">
      <span className="progress-spinner" aria-hidden="true" />
      <div className="workflow-progress-copy">
        <span>{cancelling ? "Encerrando execução" : "Execução em andamento"}</span>
        <strong>{headline}</strong>
        <small>{cancelling
          ? "A chamada HTTP foi cancelada; o backend está apenas registrando a rodada como interrompida."
          : "A tela consulta o backend automaticamente a cada segundo. Você não precisa clicar novamente."}</small>
        <div className="workflow-stage-list" aria-label="Etapas da execução">
          {stages.map((stage) => {
            const className = progress.workflow_stage === stage.label
              ? "workflow-stage active"
              : stage.count === 0
                ? "workflow-stage disabled"
                : "workflow-stage";
            return (
              <span className={className} key={stage.label}>
                {stage.label}{stage.count > 1 ? ` · até ×${stage.count}` : stage.count === 0 ? " · off" : ""}
              </span>
            );
          })}
        </div>
        <div className="workflow-progress-actions">
          <button className="button button-danger button-small" disabled={cancelling || stopping} onClick={onStop} type="button">
            {cancelling || stopping ? "Parada solicitada…" : "Parar execução"}
          </button>
        </div>
      </div>
    </section>
  );
}

function Panel({ title, meta, children }: { title: string; meta?: string; children: React.ReactNode }) {
  return <section className="panel"><header><h2>{title}</h2>{meta && <span>{meta}</span>}</header><div className="panel-body">{children}</div></section>;
}

function ImprovementPlanPanel({
  disabled,
  latest,
  onRun,
  total,
}: {
  disabled: boolean;
  latest: ImprovementPlan | null;
  onRun: () => void;
  total: number;
}) {
  return (
    <Panel title="Plano de melhoria" meta={latest ? `V${latest.version} · ${total} planos` : "Improver"}>
      <div className="improvement-plan">
        <div className="improvement-intro">
          <div>
            <p className="eyebrow">Pós-Judge</p>
            <h3>{latest ? `Como superar o score ${latest.source_score}` : "Transforme a avaliação em ações concretas"}</h3>
            <p>{latest?.plan.summary ?? "O Improver diagnostica critérios fracos, propõe soluções viáveis e prepara instruções para Builder e Researcher. Ele não altera o score diretamente."}</p>
          </div>
          <button className="button button-secondary" disabled={disabled} onClick={onRun} type="button">
            {latest ? "Gerar nova análise" : "Analisar melhorias"}
          </button>
        </div>

        {latest && (
          <>
            <section className="improvement-strategy">
              <span>Estratégia recomendada</span>
              <strong>{latest.plan.recommended_strategy}</strong>
              <small>Origem: score {latest.source_score} · confiança {formatConfidence(latest.source_confidence)}</small>
            </section>

            <div className="improvement-weaknesses">
              {latest.plan.weaknesses.map((item) => (
                <article key={item.criterion}>
                  <div><span>{scoreCriterionLabels[item.criterion]}</span><strong>{item.current_rating}/5</strong></div>
                  <small>{improvementCauseLabel(item.cause_type)}</small>
                  <p>{item.diagnosis}</p>
                  <em>Limite de confiança: {item.confidence_limit}</em>
                </article>
              ))}
            </div>

            <div className="improvement-proposals">
              {latest.plan.proposals.map((proposal) => (
                <article key={proposal.title}>
                  <div>
                    <h4>{proposal.title}</h4>
                    <span>{improvementEffortLabel(proposal.effort)} · viabilidade {proposal.feasibility}/5 · impacto potencial {proposal.expected_impact}/5</span>
                  </div>
                  <p>{proposal.description}</p>
                  <div className="criterion-tags">{proposal.target_criteria.map((criterion) => <span key={criterion}>{scoreCriterionLabels[criterion]}</span>)}</div>
                  <small><strong>Como validar:</strong> {proposal.validation_step}</small>
                </article>
              ))}
            </div>

            <div className="improvement-actions-grid">
              <TextList title="Para o Builder" items={latest.plan.builder_instructions} />
              <TextList title="Para o Researcher" items={latest.plan.research_questions} />
              <TextList title="Próximos passos" items={latest.plan.next_steps} />
              <TextList title="Condições de parada" items={latest.plan.stop_conditions} />
            </div>
          </>
        )}
      </div>
    </Panel>
  );
}

function improvementCauseLabel(value: ImprovementPlan["plan"]["weaknesses"][number]["cause_type"]): string {
  const labels: Record<typeof value, string> = {
    CONCEPT_WEAKNESS: "Fraqueza do conceito",
    EVIDENCE_GAP: "Falta de evidência",
    FEASIBILITY_RISK: "Risco de viabilidade",
    MARKET_RISK: "Risco de mercado",
    EXECUTION_RISK: "Risco de execução",
    REGULATORY_RISK: "Risco regulatório",
  };
  return labels[value];
}

function improvementEffortLabel(value: ImprovementPlan["plan"]["proposals"][number]["effort"]): string {
  return { LOW: "Esforço baixo", MEDIUM: "Esforço médio", HIGH: "Esforço alto" }[value];
}

type TrendTone = "base" | "improving" | "worsening" | "stable" | "mixed";

function EfficiencyPanel({ efficiency }: { efficiency: ProjectEfficiency }) {
  const stop = ["PARAR_E_DECIDIR", "ADICIONAR_EVIDENCIA_ANTES", "CORRIGIR_EXECUCAO"].includes(efficiency.recommendation);
  return (
    <Panel title="Eficiência por rodada" meta={`${formatCost(efficiency.total_round_cost)} nas rodadas`}>
      <div className={`score-recommendation recommendation-${stop ? "stop" : "go"}`}>
        <strong>{efficiency.recommendation.replaceAll("_", " ")}</strong>
        <span>{efficiency.recommendation_reason}</span>
      </div>
      {efficiency.rounds.length === 0 ? (
        <p className="muted">A primeira rodada criará a referência de custo, tokens, score e confiança.</p>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr><th>Rodada</th><th>Chamadas</th><th>Contexto</th><th>Tokens</th><th>Custo</th><th>Resultado</th><th>Valor</th></tr>
            </thead>
            <tbody>
              {efficiency.rounds.map((item) => (
                <tr key={item.round_number}>
                  <td><strong>#{item.round_number}</strong><small>{item.status}{item.failed_calls ? ` · ${item.failed_calls} falha(s)` : ""}</small></td>
                  <td>{item.calls}</td>
                  <td><strong>{(item.largest_input_payload_characters / 1000).toFixed(1)}k</strong><small>maior entrada · {(item.input_payload_characters / 1000).toFixed(1)}k total</small></td>
                  <td><strong>{(item.input_tokens + item.output_tokens).toLocaleString("pt-BR")}</strong><small>{item.cached_input_tokens.toLocaleString("pt-BR")} em cache</small></td>
                  <td>{formatCost(item.estimated_cost)}</td>
                  <td><strong>{item.score ?? "—"}/100</strong><small>{item.confidence === null ? "—" : formatConfidence(item.confidence)} confiança</small></td>
                  <td>
                    <strong className={deltaClass(item.score_delta ?? 0)}>{item.score_delta === null ? "referência" : `${formatScoreDelta(item.score_delta)} score`}</strong>
                    <small>{item.cost_per_score_point ? `${formatCost(item.cost_per_score_point)} / ponto` : "sem ganho de score mensurável"}</small>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className="score-trend-note">Contexto mostra caracteres do JSON realmente enviado; tokens e custo vêm do provedor. “Valor” é custo por ponto ganho, não uma estimativa de valor comercial.</p>
    </Panel>
  );
}

function ScoreEvolution({
  scores,
  decisions,
  experiments,
}: {
  scores: ProjectScore[];
  decisions: Decision[];
  experiments: Experiment[];
}) {
  const orderedScores = [...scores].sort((left, right) => left.created_at.localeCompare(right.created_at));
  const orderedDecisions = [...decisions].sort((left, right) => left.created_at.localeCompare(right.created_at));

  if (orderedScores.length === 0) {
    return (
      <Panel title="Evolução do score e da confiança" meta="Sem avaliações">
        <p className="muted">O comparativo aparecerá depois da primeira avaliação do Judge.</p>
      </Panel>
    );
  }

  const first = orderedScores[0];
  const latest = orderedScores[orderedScores.length - 1];
  const previous = orderedScores.at(-2);
  const cumulativeScoreDelta = latest.total_score - first.total_score;
  const cumulativeConfidenceDelta = latest.confidence - first.confidence;
  const latestScoreDelta = previous ? latest.total_score - previous.total_score : 0;
  const latestConfidenceDelta = previous ? latest.confidence - previous.confidence : 0;
  const recommendation = scoreRecommendation(orderedScores, experiments);

  return (
    <Panel title="Evolução do score e da confiança" meta={`${orderedScores.length} avaliações`}>
      <div className="score-evolution">
        <div className="score-trend-summary">
          <div>
            <span>Score atual</span>
            <strong>{latest.total_score}/100</strong>
            <small className={deltaClass(cumulativeScoreDelta)}>Δ {formatScoreDelta(cumulativeScoreDelta)} desde a primeira</small>
          </div>
          <div>
            <span>Confiança atual</span>
            <strong>{formatConfidence(latest.confidence)}</strong>
            <small className={deltaClass(cumulativeConfidenceDelta)}>Δ {formatConfidenceDelta(cumulativeConfidenceDelta)} desde a primeira</small>
          </div>
          <div>
            <span>Última mudança</span>
            <strong className={deltaClass(latestScoreDelta)}>{formatScoreDelta(latestScoreDelta)} score</strong>
            <small className={deltaClass(latestConfidenceDelta)}>{formatConfidenceDelta(latestConfidenceDelta)} de confiança</small>
          </div>
        </div>

        <div className={`score-recommendation recommendation-${recommendation.tone}`}>
          <span>Vale rodar novamente?</span>
          <strong>{recommendation.title}</strong>
          <p>{recommendation.message}</p>
        </div>

        <div className="table-wrap score-history-table">
          <table>
            <thead>
              <tr><th>Avaliação</th><th>Decisão</th><th>Score</th><th>Δ score</th><th>Confiança</th><th>Δ confiança</th><th>Leitura</th></tr>
            </thead>
            <tbody>
              {orderedScores.map((score, index) => {
                const prior = orderedScores[index - 1];
                const decision = orderedDecisions[index];
                const scoreDelta = prior ? score.total_score - prior.total_score : 0;
                const confidenceDelta = prior ? score.confidence - prior.confidence : 0;
                const reading = classifyScoreChange(scoreDelta, confidenceDelta, index === 0);
                const label = decision?.round_number === null
                  ? "Reavaliação"
                  : decision?.round_number
                    ? `Rodada ${decision.round_number}`
                    : `Avaliação ${index + 1}`;

                return (
                  <tr key={score.id}>
                    <td><strong>{label}</strong><small>{new Date(score.created_at).toLocaleString("pt-BR")}</small></td>
                    <td>{decision ? <span className={`decision mini decision-${decision.decision.toLowerCase()}`}>{decision.decision}</span> : "—"}</td>
                    <td><strong>{score.total_score}</strong></td>
                    <td className={index === 0 ? "delta-neutral" : deltaClass(scoreDelta)}>{index === 0 ? "—" : formatScoreDelta(scoreDelta)}</td>
                    <td><strong>{formatConfidence(score.confidence)}</strong></td>
                    <td className={index === 0 ? "delta-neutral" : deltaClass(confidenceDelta)}>{index === 0 ? "—" : formatConfidenceDelta(confidenceDelta)}</td>
                    <td><span className={`trend-reading trend-${reading.tone}`}>{reading.label}</span></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <p className="score-trend-note">Score mede a avaliação atual da ideia; confiança mede o quanto essa avaliação está apoiada por evidências. Uma nova rodada só tende a ajudar quando recebe informação nova.</p>
      </div>
    </Panel>
  );
}

function classifyScoreChange(scoreDelta: number, confidenceDelta: number, isFirst: boolean): { label: string; tone: TrendTone } {
  if (isFirst) return { label: "Base", tone: "base" };
  const scoreImproved = scoreDelta >= 2;
  const scoreWorsened = scoreDelta <= -2;
  const confidenceImproved = confidenceDelta >= 0.05;
  const confidenceWorsened = confidenceDelta <= -0.05;

  if ((scoreImproved || confidenceImproved) && (scoreWorsened || confidenceWorsened)) return { label: "Sinais mistos", tone: "mixed" };
  if (scoreImproved || confidenceImproved) return { label: "Melhora", tone: "improving" };
  if (scoreWorsened || confidenceWorsened) return { label: "Piora", tone: "worsening" };
  if (scoreDelta === 0 && confidenceDelta > 0.01) return { label: "Mais confiança", tone: "improving" };
  if (scoreDelta === 0 && confidenceDelta < -0.01) return { label: "Menos confiança", tone: "worsening" };
  if (scoreDelta > 0 || confidenceDelta > 0.01) return { label: "Leve melhora", tone: "improving" };
  if (scoreDelta < 0 || confidenceDelta < -0.01) return { label: "Leve piora", tone: "worsening" };
  return { label: "Estável", tone: "stable" };
}

function scoreRecommendation(scores: ProjectScore[], experiments: Experiment[]): { tone: "stop" | "caution" | "go"; title: string; message: string } {
  const reassessmentPending = experiments.some((item) =>
    item.status === "COMPLETED" && ["NOT_REQUESTED", "PENDING", "FAILED", "SKIPPED_BUDGET"].includes(item.reassessment_status),
  );
  if (reassessmentPending) {
    return {
      tone: "go",
      title: "Reavalie a evidência já coletada",
      message: "Existe um experimento concluído que ainda não atualizou o score. Reavalie-o antes de pagar por outra rodada completa.",
    };
  }

  if (scores.length < 2) {
    return {
      tone: "caution",
      title: "Ainda não há histórico suficiente",
      message: "Uma segunda avaliação só será comparável se você adicionar evidência, resultado de experimento ou orientação nova.",
    };
  }

  const latest = scores.at(-1)!;
  const previous = scores.at(-2)!;
  const recent = scores.slice(-3);
  const recentScoreRange = Math.max(...recent.map((item) => item.total_score)) - Math.min(...recent.map((item) => item.total_score));
  const recentConfidenceRange = Math.max(...recent.map((item) => item.confidence)) - Math.min(...recent.map((item) => item.confidence));
  const scoreDelta = latest.total_score - previous.total_score;
  const confidenceDelta = latest.confidence - previous.confidence;

  if (recent.length === 3 && recentScoreRange <= 1 && recentConfidenceRange <= 0.05) {
    return {
      tone: "stop",
      title: "Não rode outra rodada igual",
      message: "As três últimas avaliações estão estagnadas. Primeiro conclua um experimento ou acrescente evidência nova que possa mudar alguma hipótese.",
    };
  }
  if (latest.total_score >= 80 && latest.confidence >= 0.7) {
    return {
      tone: "stop",
      title: "Não rode apenas por inércia",
      message: "Score e confiança já estão altos. Revise a decisão e avance para validação ou desenvolvimento, salvo se houver uma dúvida específica.",
    };
  }
  if (scoreDelta <= -2 || confidenceDelta <= -0.05) {
    return {
      tone: "stop",
      title: "Investigue a piora antes de repetir",
      message: "A última avaliação piorou de forma relevante. Leia os bloqueadores e busque evidência para confirmar, corrigir ou pivotar a hipótese afetada.",
    };
  }
  if (scoreDelta >= 2 || confidenceDelta >= 0.05) {
    return {
      tone: "go",
      title: "Há melhora, mas exija informação nova",
      message: "Outra rodada pode valer a pena se houver nova evidência ou uma orientação materialmente diferente. Repetir o mesmo contexto não garante progresso.",
    };
  }
  return {
    tone: "caution",
    title: "Só rode com nova evidência",
    message: "A mudança foi pequena. Adicione um resultado mensurável, uma fonte nova ou uma orientação específica antes da próxima execução.",
  };
}

function deltaClass(value: number): string {
  if (value > 0.0001) return "delta-positive";
  if (value < -0.0001) return "delta-negative";
  return "delta-neutral";
}

function formatScoreDelta(value: number): string {
  return `${value > 0 ? "+" : ""}${value}`;
}

function formatConfidenceDelta(value: number): string {
  const percentagePoints = Math.round(value * 100);
  return `${percentagePoints > 0 ? "+" : ""}${percentagePoints} p.p.`;
}

function ConceptView({ concept }: { concept: IdeaConcept }) {
  return (
    <div className="concept-view">
      <ConceptSection title="Problema" text={concept.problem} />
      <ConceptSection title="Solução" text={concept.solution} />
      <ConceptSection title="Proposta de valor" text={concept.value_proposition} />
      <ConceptSection title="MVP inicial" text={concept.initial_mvp} />
      <div className="concept-columns">
        <TextList title="Usuários-alvo" items={concept.target_users} />
        <TextList title="Casos de uso" items={concept.possible_use_cases} />
        <TextList title="Incertezas" items={concept.unknowns} />
        <TextList title="Riscos" items={concept.risks} />
      </div>
    </div>
  );
}

function ConceptSection({ title, text }: { title: string; text: string }) {
  return <div className="concept-section"><h3>{title}</h3><p>{text}</p></div>;
}

function TextList({ title, items }: { title: string; items: string[] }) {
  return <div className="text-list"><h3>{title}</h3><ul>{items.map((item, index) => <li key={`${index}-${item}`}>{item}</li>)}</ul></div>;
}

function DevelopmentBlueprintView({ blueprint }: { blueprint: DevelopmentBlueprint }) {
  const product = blueprint.product_definition;
  const review = blueprint.technical_review;
  const plan = blueprint.final_blueprint;
  return (
    <div className="blueprint-result">
      <div className="blueprint-result-heading">
        <div>
          <span className={`table-status blueprint-status-${blueprint.status.toLowerCase()}`}>{blueprint.status}</span>
          <strong>Versão {blueprint.version}</strong>
        </div>
        <small>{blueprint.agent_run_ids.length} chamadas · {formatCost(blueprint.estimated_cost)}</small>
      </div>
      {blueprint.error && <div className="alert alert-error">{blueprint.error}</div>}
      {product && (
        <section>
          <h3>Definição do produto</h3>
          <p>{product.executive_summary}</p>
          <div className="blueprint-columns">
            <TextList title="Objetivos" items={product.goals} />
            <TextList title="Questões abertas" items={product.open_questions} />
          </div>
          <details>
            <summary>{product.functional_requirements.length} requisitos funcionais e {product.non_functional_requirements.length} não funcionais</summary>
            <div className="blueprint-requirements">
              {product.functional_requirements.map((item) => (
                <article key={item.id}><span className="mono-id">{item.id}</span><strong>{item.priority}</strong><p>{item.description}</p></article>
              ))}
              {product.non_functional_requirements.map((item) => (
                <article key={item.id}><span className="mono-id">{item.id}</span><strong>{item.category}</strong><p>{item.requirement} — {item.measurable_target}</p></article>
              ))}
            </div>
          </details>
        </section>
      )}
      {blueprint.architecture_options.length > 0 && (
        <section>
          <h3>Alternativas de arquitetura</h3>
          <div className="architecture-options">
            {blueprint.architecture_options.map((option) => (
              <details key={option.option_name}>
                <summary>{option.option_name} · {option.system_style}</summary>
                <p>{option.summary}</p>
                <TextList title="Componentes" items={option.components.map((item) => `${item.name}: ${item.responsibility}`)} />
                <TextList title="Trade-offs" items={option.tradeoffs} />
                <TextList title="Riscos" items={option.risks} />
              </details>
            ))}
          </div>
        </section>
      )}
      {review && (
        <section className="technical-review">
          <h3>Revisão técnica</h3>
          <strong>Recomendação: {review.recommended_option}</strong>
          <p>{review.recommendation_reason}</p>
          {review.required_changes.length > 0 && <TextList title="Mudanças obrigatórias" items={review.required_changes} />}
        </section>
      )}
      {plan && (
        <section>
          <h3>Plano de desenvolvimento</h3>
          <p><strong>{plan.selected_option}:</strong> {plan.decision_rationale}</p>
          <div className="delivery-phases">
            {plan.phases.map((phase) => (
              <article key={phase.number}>
                <span>Fase {phase.number}</span>
                <h4>{phase.name}</h4>
                <p>{phase.objective}</p>
                <TextList title="Entregáveis" items={phase.deliverables} />
                <TextList title="Aceite" items={phase.acceptance_criteria} />
              </article>
            ))}
          </div>
          <details>
            <summary>Backlog inicial · {plan.initial_backlog.length} itens</summary>
            <div className="blueprint-backlog">
              {plan.initial_backlog.map((item) => (
                <article key={item.id}><span className="mono-id">{item.id}</span><strong>{item.priority} · Fase {item.phase}</strong><h4>{item.title}</h4><p>{item.description}</p></article>
              ))}
            </div>
          </details>
        </section>
      )}
    </div>
  );
}

function ExperimentEditor({
  busy,
  item,
  onReassess,
  onSave,
  workflowActive,
}: {
  busy: boolean;
  item: Experiment;
  onReassess: (id: string) => Promise<void>;
  onSave: (id: string, payload: Parameters<typeof api.updateExperiment>[2]) => Promise<void>;
  workflowActive: boolean;
}) {
  const [metric, setMetric] = useState(item.success_metric ?? "");
  const [threshold, setThreshold] = useState(item.success_threshold ?? "");
  const [result, setResult] = useState(item.result_summary ?? "");
  const [observedValue, setObservedValue] = useState(item.observed_value ?? "");
  const [sampleSize, setSampleSize] = useState(item.sample_size?.toString() ?? "");
  const [methodology, setMethodology] = useState(item.methodology ?? "");
  const [limitations, setLimitations] = useState(item.limitations ?? "");
  const [actualCost, setActualCost] = useState(item.actual_cost);
  const [status, setStatus] = useState(item.status);
  const [outcome, setOutcome] = useState<NonNullable<Experiment["outcome"]> | "">(item.outcome ?? "");
  const [formError, setFormError] = useState<string | null>(null);
  const closed = ["COMPLETED", "CANCELLED"].includes(item.status);
  const canReassess = item.status === "COMPLETED" && ["NOT_REQUESTED", "PENDING", "FAILED", "SKIPPED_BUDGET"].includes(item.reassessment_status);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setFormError(null);
    if (status === "COMPLETED") {
      const missing = [
        !metric.trim() ? "métrica" : null,
        !threshold.trim() ? "limite de sucesso" : null,
        !result.trim() ? "resultado" : null,
        !outcome ? "classificação do resultado" : null,
      ].filter(Boolean);
      if (missing.length > 0) {
        setFormError(`Para concluir, preencha: ${missing.join(", ")}.`);
        return;
      }
      if (workflowActive) {
        setFormError("A execução anterior ainda está finalizando. Aguarde ou use “Parar execução” antes de concluir o experimento.");
        return;
      }
    }
    await onSave(item.id, {
      success_metric: metric.trim() || undefined,
      success_threshold: threshold.trim() || undefined,
      result_summary: result.trim() || undefined,
      observed_value: observedValue.trim() || undefined,
      sample_size: sampleSize ? Number(sampleSize) : undefined,
      methodology: methodology.trim() || undefined,
      limitations: limitations.trim() || undefined,
      actual_cost: actualCost || "0",
      status,
      outcome: outcome || undefined,
    });
  }

  return (
    <form className="experiment-card" onSubmit={submit}>
      <div className="experiment-heading"><span className="table-status">{item.status}</span><strong>{item.experiment_type}</strong></div>
      <p>{item.description}</p>
      <label>Métrica<input disabled={closed} required={status === "COMPLETED"} value={metric} onChange={(event) => setMetric(event.target.value)} /></label>
      <label>Limite de sucesso<input disabled={closed} required={status === "COMPLETED"} value={threshold} onChange={(event) => setThreshold(event.target.value)} /></label>
      <label>Resultado<textarea disabled={closed} required={status === "COMPLETED"} rows={3} value={result} onChange={(event) => setResult(event.target.value)} /></label>
      <div className="experiment-fields">
        <label>Valor observado<input disabled={closed} placeholder="Ex.: Sharpe 1,12; p95 280 ms" value={observedValue} onChange={(event) => setObservedValue(event.target.value)} /></label>
        <label>Tamanho da amostra<input disabled={closed} min="1" step="1" type="number" value={sampleSize} onChange={(event) => setSampleSize(event.target.value)} /></label>
        <label>Custo real<input disabled={closed} min="0" step="0.000001" type="number" value={actualCost} onChange={(event) => setActualCost(event.target.value)} /></label>
      </div>
      <label>Metodologia<textarea disabled={closed} placeholder="Como o teste foi executado, período, controles e fonte dos dados" rows={3} value={methodology} onChange={(event) => setMethodology(event.target.value)} /></label>
      <label>Limitações<textarea disabled={closed} placeholder="Viés, duração, amostra ou condições que limitam a conclusão" rows={2} value={limitations} onChange={(event) => setLimitations(event.target.value)} /></label>
      <div className="experiment-fields">
        <label>Status<select disabled={closed} value={status} onChange={(event) => setStatus(event.target.value as Experiment["status"])}><option value="PLANNED">Planejado</option><option value="RUNNING">Em execução</option><option value="COMPLETED">Concluído</option><option value="CANCELLED">Cancelado</option></select></label>
        <label>Resultado<select disabled={closed} required={status === "COMPLETED"} value={outcome} onChange={(event) => setOutcome(event.target.value as NonNullable<Experiment["outcome"]> | "")}><option value="">Selecione</option><option value="SUCCESS">Sucesso</option><option value="FAILURE">Falha</option><option value="INCONCLUSIVE">Inconclusivo</option></select></label>
      </div>
      {!closed && <p className="experiment-help">Ao marcar como concluído, o resultado será convertido em evidência. Depois você decide quando chamar o Judge para uma reavaliação focada. Valor observado, amostra e metodologia aumentam a qualidade da evidência.</p>}
      {workflowActive && !closed && <p className="experiment-help">A execução anterior ainda está ativa. Você pode salvar o preenchimento, mas deve aguardar ou pará-la antes de concluir e reavaliar.</p>}
      {formError && <p className="field-error" role="alert">{formError}</p>}
      {!closed && <button className="button button-secondary" disabled={busy} type="submit">{busy ? "Salvando…" : "Salvar experimento"}</button>}
      {item.status === "COMPLETED" && (
        <div className="experiment-trace">
          <div className="experiment-trace-heading">
            <strong>Evidência {item.evidence_id ? `registrada · qualidade ${item.evidence_quality ?? 0}/5` : "ainda não registrada"}</strong>
            <span className={`table-status reassessment-${item.reassessment_status.toLowerCase()}`}>{reassessmentLabel(item.reassessment_status)}</span>
          </div>
          {item.affected_criteria.length > 0 && <div className="criterion-tags">{item.affected_criteria.map((criterion) => <span key={criterion}>{scoreCriterionLabels[criterion]}</span>)}</div>}
          {item.previous_score !== null && item.reassessed_score !== null && (
            <div className="score-comparison">
              <span>Score <strong>{item.previous_score} → {item.reassessed_score}</strong></span>
              <span>Confiança <strong>{formatConfidence(item.previous_confidence)} → {formatConfidence(item.reassessed_confidence)}</strong></span>
            </div>
          )}
          {item.reassessment_error && <p className="field-error">{item.reassessment_error}</p>}
          {canReassess && <button className="button button-secondary" disabled={busy || workflowActive} onClick={() => onReassess(item.id)} type="button">{busy ? "Reavaliando…" : "Reavaliar com esta evidência"}</button>}
        </div>
      )}
    </form>
  );
}

function reassessmentLabel(status: Experiment["reassessment_status"]): string {
  const labels: Record<Experiment["reassessment_status"], string> = {
    NOT_REQUESTED: "Não reavaliado",
    PENDING: "Aguardando reavaliação",
    COMPLETED: "Reavaliado",
    FAILED: "Falhou",
    SKIPPED_BUDGET: "Sem orçamento",
  };
  return labels[status];
}

function experimentNotice(item: Experiment): string {
  if (item.status !== "COMPLETED") return "Experimento atualizado.";
  if (item.reassessment_status === "PENDING") {
    return "Experimento e evidência salvos. Use “Reavaliar com esta evidência” quando quiser chamar o Judge.";
  }
  if (item.reassessment_status === "COMPLETED") {
    return `Evidência registrada e projeto reavaliado: score ${item.previous_score ?? "—"} → ${item.reassessed_score ?? "—"}.`;
  }
  if (item.reassessment_status === "SKIPPED_BUDGET") {
    return "Evidência registrada. A reavaliação não foi executada porque o orçamento de IA terminou.";
  }
  if (item.reassessment_status === "FAILED") {
    return "Evidência registrada, mas a reavaliação falhou. Você pode tentar novamente.";
  }
  return "Experimento concluído e evidência registrada.";
}

function CriticismCard({ item }: { item: Criticism }) {
  return (
    <article className="criticism-card">
      <div><span className={`severity severity-${item.severity.toLowerCase()}`}>{item.severity}</span><h3>{item.title}</h3></div>
      <p>{item.claim}</p>
      <details><summary>Ver fundamento e condição de refutação</summary><p><strong>Motivo:</strong> {item.reason}</p><p><strong>Evidência necessária:</strong> {item.evidence_needed}</p><p><strong>Refutada se:</strong> {item.condition_that_refutes_criticism}</p></details>
    </article>
  );
}
