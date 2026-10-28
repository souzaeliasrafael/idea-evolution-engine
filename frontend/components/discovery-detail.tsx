"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";

import { api, formatConfidence, formatCost } from "@/lib/api";
import type { CommercialValidationPayload, DiscoveryAgentRun, DiscoveryCampaign, OpportunityCandidate, OpportunityFeedbackStatus, OpportunitySignal } from "@/lib/types";

const stageLabels: Record<string, string> = {
  PESQUISANDO_SINAIS: "Scout pesquisando sinais atuais na web",
  REUTILIZANDO_SINAIS: "Retomando os sinais já pesquisados, sem novo custo",
  GERANDO_OPORTUNIDADES: "Generator convertendo dores em negócios",
  RECUPERANDO_GERACAO: "Recuperando ideias válidas de uma tentativa já paga",
  REUTILIZANDO_OPORTUNIDADES: "Retomando as oportunidades já geradas",
  VALIDANDO_MERCADO: "Researcher verificando demanda e concorrentes",
  REUTILIZANDO_PESQUISA: "Retomando a pesquisa de mercado já concluída",
  COMPARANDO_PORTFOLIO: "Portfolio Judge comparando as finalistas",
  SEM_FINALISTAS_COMPROVADAS: "Nenhuma oportunidade passou pelo filtro de mercado",
  CANCELAMENTO_SOLICITADO: "Cancelamento solicitado",
  CONCLUIDA: "Análise concluída",
  CANCELADA: "Análise cancelada",
  ORCAMENTO_ENCERRADO: "Orçamento encerrado",
  FALHA: "A execução falhou",
};

const scoreLabels: Record<string, string> = {
  pain_severity: "Dor",
  willingness_to_pay: "Disposição a pagar",
  reachability: "Acesso ao público",
  founder_fit: "Aderência a você",
  economics: "Economia",
  speed_to_revenue: "Velocidade",
  differentiation: "Diferenciação",
  feasibility: "Viabilidade",
  regulatory_safety: "Segurança regulatória",
};

const marketScoreLabels: Array<[keyof OpportunityCandidate["research"], string]> = [
  ["demand_signal_score", "Demanda"],
  ["willingness_to_pay_score", "Pagamento"],
  ["paid_competitor_score", "Concorrentes pagos"],
  ["channel_score", "Aquisição"],
  ["recurrence_score", "Recorrência"],
  ["margin_score", "Margem"],
  ["evidence_quality_score", "Qualidade das fontes"],
];

const suggestedFeedbackTags = [
  "B2B",
  "Não combina comigo",
  "Mercado saturado",
  "Venda difícil",
  "Custo alto",
  "Complexa demais",
  "Pouco diferencial",
  "Operação manual",
  "Risco regulatório",
  "Baixa recorrência",
  "Sem disposição a pagar",
  "CAC provavelmente alto",
  "Sem canal de aquisição",
  "Fácil de copiar",
  "Não tenho interesse",
];

function CandidateFeedback({ candidate, onSaved }: { candidate: OpportunityCandidate; onSaved: (candidate: OpportunityCandidate) => void }) {
  const [verdict, setVerdict] = useState<OpportunityFeedbackStatus>(candidate.user_feedback);
  const [tags, setTags] = useState<string[]>(candidate.feedback_tags);
  const [note, setNote] = useState(candidate.feedback_note ?? "");
  const [customTag, setCustomTag] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setVerdict(candidate.user_feedback);
    setTags(candidate.feedback_tags);
    setNote(candidate.feedback_note ?? "");
  }, [candidate]);

  function toggleTag(tag: string) {
    setTags((current) => current.includes(tag) ? current.filter((item) => item !== tag) : [...current, tag].slice(0, 10));
  }

  function addCustomTag() {
    const normalized = customTag.trim();
    if (normalized && !tags.includes(normalized)) setTags((current) => [...current, normalized].slice(0, 10));
    setCustomTag("");
  }

  async function save(nextVerdict: OpportunityFeedbackStatus, nextTags = tags, nextNote = note) {
    setBusy(true); setError(null);
    try {
      const updated = await api.updateOpportunityFeedback(candidate.id, {
        user_feedback: nextVerdict,
        feedback_tags: nextTags,
        feedback_note: nextNote.trim() || null,
      });
      setVerdict(updated.user_feedback);
      onSaved(updated);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Não foi possível salvar sua avaliação.");
    } finally { setBusy(false); }
  }

  const showRejection = verdict === "REJECTED";
  return (
    <div className={`candidate-feedback feedback-${verdict.toLowerCase()}`}>
      <div className="candidate-feedback-heading">
        <div><strong>Sua avaliação</strong><small>Será usada nas próximas campanhas deste perfil.</small></div>
        <div className="candidate-feedback-actions">
          <button className={verdict === "APPROVED" ? "feedback-button approved" : "feedback-button"} disabled={busy} onClick={() => void save("APPROVED", [], "")} type="button">✓ Aprovar</button>
          <button className={verdict === "REJECTED" ? "feedback-button rejected" : "feedback-button"} disabled={busy} onClick={() => setVerdict("REJECTED")} type="button">× Não gostei</button>
        </div>
      </div>
      {showRejection && <div className="feedback-editor">
        <span>Por que não gostou?</span>
        <div className="feedback-tags">{suggestedFeedbackTags.map((tag) => <button className={tags.includes(tag) ? "active" : ""} key={tag} onClick={() => toggleTag(tag)} type="button">{tag}</button>)}</div>
        <div className="feedback-custom-tag"><input maxLength={300} placeholder="Outra tag" value={customTag} onChange={(event) => setCustomTag(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter") { event.preventDefault(); addCustomTag(); } }} /><button className="button button-secondary button-small" onClick={addCustomTag} type="button">Adicionar</button></div>
        {tags.filter((tag) => !suggestedFeedbackTags.includes(tag)).length > 0 && <div className="feedback-tags custom">{tags.filter((tag) => !suggestedFeedbackTags.includes(tag)).map((tag) => <button className="active" key={tag} onClick={() => toggleTag(tag)} type="button">{tag} ×</button>)}</div>}
        <textarea maxLength={2000} placeholder="Observação opcional para orientar os agentes" rows={2} value={note} onChange={(event) => setNote(event.target.value)} />
        <div className="feedback-save-row"><button className="button button-small" disabled={busy} onClick={() => void save("REJECTED")} type="button">Salvar rejeição</button>{candidate.user_feedback !== "PENDING" && <button className="button button-secondary button-small" disabled={busy} onClick={() => void save("PENDING", [], "")} type="button">Limpar avaliação</button>}</div>
      </div>}
      {verdict === "APPROVED" && <p className="feedback-confirmation">Aprovada. O Generator poderá criar variações melhores quando você selecionar esse modo.</p>}
      {error && <p className="field-error">{error}</p>}
    </div>
  );
}

function CommercialValidation({ candidate, onSaved }: { candidate: OpportunityCandidate; onSaved: (candidate: OpportunityCandidate) => void }) {
  const saved = candidate.validation_result;
  const [payload, setPayload] = useState<CommercialValidationPayload>({
    status: candidate.validation_status === "UNTESTED" ? "PLANNED" : candidate.validation_status,
    channel: saved.channel ?? "Landing page com tráfego segmentado",
    hypothesis: saved.hypothesis ?? "A oferta conseguirá pelo menos uma pré-venda ou cliente pagante.",
    visits: saved.visits ?? 0,
    leads: saved.leads ?? 0,
    preorders: saved.preorders ?? 0,
    paying_customers: saved.paying_customers ?? 0,
    revenue: saved.revenue ?? "0",
    spend: saved.spend ?? "0",
    currency: saved.currency ?? "BRL",
    notes: saved.notes ?? "",
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function save() {
    setBusy(true); setError(null);
    try {
      onSaved(await api.updateCommercialValidation(candidate.id, payload));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Não foi possível registrar o experimento.");
    } finally { setBusy(false); }
  }

  const metric = (key: "visits" | "leads" | "preorders" | "paying_customers", value: string) => {
    setPayload((current) => ({ ...current, [key]: Math.max(0, Number(value) || 0) }));
  };

  return (
    <details className="commercial-validation" open={candidate.validation_status !== "UNTESTED"}>
      <summary>Validação comercial <span className={`validation-status validation-${candidate.validation_status.toLowerCase()}`}>{candidate.validation_status}</span></summary>
      <div className="validation-body">
        <p>Registre uma oferta real. A nota só melhora com pré-venda ou cliente pagante; leads isolados continuam como evidência intermediária.</p>
        <div className="validation-grid">
          <label>Status<select value={payload.status} onChange={(e) => setPayload({ ...payload, status: e.target.value as CommercialValidationPayload["status"] })}><option value="PLANNED">Planejado</option><option value="RUNNING">Em execução</option><option value="VALIDATED">Compra validada</option><option value="INVALIDATED">Hipótese invalidada</option><option value="INCONCLUSIVE">Inconclusivo</option></select></label>
          <label>Canal<input value={payload.channel} onChange={(e) => setPayload({ ...payload, channel: e.target.value })} /></label>
        </div>
        <label>Hipótese da oferta<textarea rows={2} value={payload.hypothesis} onChange={(e) => setPayload({ ...payload, hypothesis: e.target.value })} /></label>
        <div className="validation-metrics">
          <label>Visitas<input type="number" min="0" value={payload.visits} onChange={(e) => metric("visits", e.target.value)} /></label>
          <label>Leads<input type="number" min="0" value={payload.leads} onChange={(e) => metric("leads", e.target.value)} /></label>
          <label>Pré-vendas<input type="number" min="0" value={payload.preorders} onChange={(e) => metric("preorders", e.target.value)} /></label>
          <label>Pagantes<input type="number" min="0" value={payload.paying_customers} onChange={(e) => metric("paying_customers", e.target.value)} /></label>
          <label>Receita ({payload.currency})<input type="number" min="0" step="0.01" value={payload.revenue} onChange={(e) => setPayload({ ...payload, revenue: e.target.value })} /></label>
          <label>Investimento ({payload.currency})<input type="number" min="0" step="0.01" value={payload.spend} onChange={(e) => setPayload({ ...payload, spend: e.target.value })} /></label>
        </div>
        <label>Observações<textarea rows={2} value={payload.notes} onChange={(e) => setPayload({ ...payload, notes: e.target.value })} /></label>
        {candidate.validation_status !== "UNTESTED" && <div className="validation-comparison"><span>Δ score <strong>{(saved.score_delta ?? 0) >= 0 ? "+" : ""}{(saved.score_delta ?? 0).toFixed(1)}</strong></span><span>Δ confiança <strong>{(saved.confidence_delta ?? 0) >= 0 ? "+" : ""}{Math.round((saved.confidence_delta ?? 0) * 100)} p.p.</strong></span><span>Δ mercado <strong>{(saved.market_reality_delta ?? 0) >= 0 ? "+" : ""}{(saved.market_reality_delta ?? 0).toFixed(1)}</strong></span></div>}
        {error && <p className="field-error">{error}</p>}
        <button className="button button-small" disabled={busy} onClick={() => void save()} type="button">{busy ? "Salvando…" : "Registrar resultado"}</button>
      </div>
    </details>
  );
}

export function DiscoveryDetail({ campaignId }: { campaignId: string }) {
  const router = useRouter();
  const controller = useRef<AbortController | null>(null);
  const [campaign, setCampaign] = useState<DiscoveryCampaign | null>(null);
  const [signals, setSignals] = useState<OpportunitySignal[]>([]);
  const [candidates, setCandidates] = useState<OpportunityCandidate[]>([]);
  const [runs, setRuns] = useState<DiscoveryAgentRun[]>([]);
  const [projectBudget, setProjectBudget] = useState("2.00");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    const [campaignData, signalData, candidateData, runData] = await Promise.all([
      api.getDiscoveryCampaign(campaignId),
      api.listOpportunitySignals(campaignId),
      api.listOpportunityCandidates(campaignId),
      api.listDiscoveryRuns(campaignId),
    ]);
    setCampaign(campaignData); setSignals(signalData); setCandidates(candidateData); setRuns(runData);
    return campaignData;
  }, [campaignId]);

  useEffect(() => {
    refresh().catch((cause) => setError(cause instanceof Error ? cause.message : "Não foi possível carregar a campanha."));
  }, [refresh]);

  useEffect(() => {
    if (campaign?.status !== "RUNNING") return;
    const timer = window.setInterval(() => {
      refresh().catch(() => undefined);
    }, 1200);
    return () => window.clearInterval(timer);
  }, [campaign?.status, refresh]);

  async function runCampaign() {
    setBusy(true); setError(null);
    controller.current = new AbortController();
    setCampaign((current) => current ? { ...current, status: "RUNNING", current_stage: "PESQUISANDO_SINAIS" } : current);
    try {
      await api.runDiscoveryCampaign(campaignId, controller.current.signal);
      await refresh();
    } catch (cause) {
      if (!(cause instanceof DOMException && cause.name === "AbortError")) {
        setError(cause instanceof Error ? cause.message : "A descoberta não pôde ser executada.");
      }
      await refresh().catch(() => undefined);
    } finally { controller.current = null; setBusy(false); }
  }

  async function cancelCampaign() {
    setError(null);
    try {
      const updated = await api.cancelDiscoveryCampaign(campaignId);
      setCampaign(updated);
      controller.current?.abort();
      window.setTimeout(() => { refresh().catch(() => undefined); }, 500);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Não foi possível cancelar.");
    }
  }

  async function promote(candidate: OpportunityCandidate) {
    setBusy(true); setError(null);
    try {
      const project = await api.promoteOpportunity(candidate.id, projectBudget.trim() || null);
      router.push(`/projects/${project.id}`);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Não foi possível promover a oportunidade.");
      setBusy(false);
    }
  }

  if (!campaign) return <div className="page-shell"><div className="state-card">Carregando campanha…</div></div>;
  const running = campaign.status === "RUNNING";
  const progress = Math.min(100, (Number(campaign.total_cost) / Number(campaign.max_ai_budget)) * 100);

  return (
    <div className="page-shell discovery-detail-page">
      <Link className="back-link" href="/discover">← Voltar para descoberta</Link>
      <section className="project-header discovery-header">
        <div className="project-title-block"><p className="eyebrow">Campanha de oportunidades</p><div className="title-line"><h1>{campaign.name}</h1><span className={`status status-${campaign.status.toLowerCase()}`}>{campaign.status}</span></div><p>{campaign.brief || "Busca ampla, orientada pelo perfil do fundador."}</p></div>
        <div className="header-metrics"><div><span>Candidatas</span><strong>{campaign.candidate_target}</strong></div><div><span>Finalistas</span><strong>{campaign.finalist_target}</strong></div><div><span>Custo</span><strong>{formatCost(campaign.total_cost)}</strong></div><div><span>Limite</span><strong>{formatCost(campaign.max_ai_budget)}</strong></div></div>
        <div className="budget-summary"><div><span>Uso do orçamento da campanha</span><span>{Math.round(progress)}%</span></div><div className="budget-track large"><span style={{ width: `${progress}%` }} /></div></div>
        <div className="header-actions">
          <div className="discovery-run-copy"><strong>{campaign.current_stage ? stageLabels[campaign.current_stage] ?? campaign.current_stage : "Pronta para iniciar"}</strong><small>{running ? "A tela é atualizada automaticamente após cada agente." : "A validação completa do projeto só começa após você escolher uma oportunidade."}</small></div>
          {running ? <button className="button button-danger" onClick={cancelCampaign}>Parar descoberta</button> : <button className="button" disabled={busy || campaign.status === "COMPLETED"} onClick={runCampaign}>{campaign.status === "COMPLETED" ? "Descoberta concluída" : "Executar descoberta"}</button>}
        </div>
      </section>
      {running && <div className="workflow-progress"><span className="progress-spinner" /><div className="workflow-progress-copy"><span>Execução em andamento</span><strong>{campaign.current_stage ? stageLabels[campaign.current_stage] : "Preparando…"}</strong><small>{runs.length} de 4 etapas registradas · você pode sair desta página e voltar depois.</small></div></div>}
      {error && <div className="alert alert-error">{error}</div>}
      {campaign.error && <div className="alert alert-warning"><strong>A campanha não concluiu.</strong>{campaign.error}</div>}

      <section className="discovery-ranking">
        <header className="section-heading"><div><p className="eyebrow">Ranking comparável</p><h2>Oportunidades encontradas</h2></div>{candidates.some((item) => item.rank) && <label className="project-budget-inline">Orçamento do projeto promovido (USD)<input type="number" min="0" step="0.01" value={projectBudget} onChange={(e) => setProjectBudget(e.target.value)} /></label>}</header>
        {candidates.length === 0 ? <div className="empty-state"><span className="empty-glyph">◇</span><h2>Ainda sem oportunidades</h2><p>Execute a campanha para pesquisar o mercado e gerar o ranking.</p></div> : (
          <div className="opportunity-list">
            {candidates.map((item) => (
              <article className={`opportunity-card ${item.status === "FINALIST" || item.status === "SELECTED" ? "finalist" : ""} ${!item.hard_constraint_passed || (item.market_reality_score !== null && !item.market_gate_passed) ? "gate-rejected" : ""}`} key={item.id}>
                <header><div className="opportunity-rank">{item.rank ? `#${item.rank}` : "—"}</div><div><div className="opportunity-title-row"><h3>{item.title}</h3><span className={`status status-${item.status.toLowerCase()}`}>{item.status}</span></div><p>{item.problem}</p><div className="gate-badges"><span className={item.business_case.customer_type === undefined ? "gate-neutral" : item.hard_constraint_passed ? "gate-pass" : "gate-fail"}>{item.business_case.customer_type === undefined ? "Legado: regras não medidas" : item.hard_constraint_passed ? "✓ Regras" : "× Regras"}</span><span className={item.market_reality_score === null ? "gate-neutral" : item.market_gate_passed ? "gate-pass" : "gate-fail"}>{item.market_reality_score === null ? "Legado: mercado não medido" : item.market_gate_passed ? "✓ Mercado" : "× Mercado"}</span></div></div><div className="opportunity-score"><strong>{item.overall_score?.toFixed(1) ?? item.preliminary_score.toFixed(1)}</strong><span>{item.overall_score === null ? "pré-score" : "score"}</span><small>{formatConfidence(item.confidence)}</small>{item.market_reality_score !== null && <em>Mercado {item.market_reality_score.toFixed(1)}</em>}</div></header>
                {item.disqualification_reasons.length > 0 && <div className="gate-reasons"><strong>Por que não passou</strong>{item.disqualification_reasons.map((reason) => <p key={reason}>{reason}</p>)}</div>}
                <div className="opportunity-core"><div><span>Cliente</span><p>{item.target_customer}</p></div><div><span>Solução</span><p>{item.solution}</p></div><div><span>Receita</span><p>{item.business_model} {item.pricing_hypothesis}</p></div><div><span>Primeira venda</span><p>{item.first_revenue_path}</p></div></div>
                <div className="business-case-strip"><span>{item.business_case.customer_type ?? "—"}</span><span>{item.business_case.automation_percent ?? 0}% automatizado</span><span>MVP em {item.business_case.mvp_days ?? "—"} dias</span><span>{item.business_case.revenue_pattern ?? "receita não classificada"}</span></div>
                {Object.keys(item.scores).length > 0 && <div className="opportunity-score-grid">{Object.entries(item.scores).map(([key, value]) => <div key={key}><span>{scoreLabels[key] ?? key}</span><strong>{value}</strong><div><i style={{ width: `${value}%` }} /></div></div>)}</div>}
                {item.market_reality_score !== null && <div className="market-score-panel"><div><strong>Market Reality Score</strong><span>{item.market_reality_score.toFixed(1)}/100 · {item.research.direct_purchase_evidence ? "há evidência direta de compra" : "sem evidência direta de compra"}</span></div><div className="market-score-grid">{marketScoreLabels.map(([key, label]) => { const value = item.research[key]; return typeof value === "number" ? <div key={key}><span>{label}</span><strong>{value}</strong></div> : null; })}</div></div>}
                {item.research.judge_rationale && <p className="judge-rationale"><strong>Leitura do Judge:</strong> {item.research.judge_rationale}</p>}
                {item.inspired_by_candidate_ids.length > 0 && <p className="memory-line">Evolução de {item.inspired_by_candidate_ids.length} oportunidade(s) anterior(es).</p>}
                <details className="opportunity-evidence"><summary>Pesquisa, riscos e próximo teste</summary><div>
                  {item.research.demand_evidence?.map((evidence, index) => <p key={`d-${index}`}><strong>Demanda:</strong> {evidence.claim} <a href={evidence.source_url} target="_blank" rel="noreferrer">Abrir fonte ↗</a></p>)}
                  {item.research.competitor_evidence?.map((evidence, index) => <p key={`c-${index}`}><strong>Concorrência:</strong> {evidence.claim} <a href={evidence.source_url} target="_blank" rel="noreferrer">Abrir fonte ↗</a></p>)}
                  {item.research.buyer && <p><strong>Comprador:</strong> {item.research.buyer}</p>}
                  {item.research.purchase_event && <p><strong>Evento de compra:</strong> {item.research.purchase_event}</p>}
                  {item.research.current_spend && <p><strong>Gasto atual:</strong> {item.research.current_spend}</p>}
                  {item.research.reachable_acquisition_channel && <p><strong>Canal acessível:</strong> {item.research.reachable_acquisition_channel}</p>}
                  {item.research.gross_margin_estimate && <p><strong>Margem:</strong> {item.research.gross_margin_estimate} · <strong>CAC máximo:</strong> {item.research.cac_ceiling}</p>}
                  {item.risks.length > 0 && <p><strong>Riscos:</strong> {item.risks.join(" · ")}</p>}
                  {item.research.validation_plan && <p><strong>Validação:</strong> {item.research.validation_plan.join(" → ")}</p>}
                </div></details>
                <CommercialValidation candidate={item} onSaved={(updated) => setCandidates((current) => current.map((candidate) => candidate.id === updated.id ? updated : candidate))} />
                <CandidateFeedback candidate={item} onSaved={(updated) => setCandidates((current) => current.map((candidate) => candidate.id === updated.id ? updated : candidate))} />
                <footer><span>Sinais: {item.signal_codes.join(", ")}</span>{item.project_id ? <Link className="button button-secondary" href={`/projects/${item.project_id}`}>Abrir projeto</Link> : (item.rank || item.validation_status === "VALIDATED") && item.hard_constraint_passed && item.market_gate_passed && <button className="button" disabled={busy} onClick={() => promote(item)}>Transformar em projeto</button>}</footer>
              </article>
            ))}
          </div>
        )}
      </section>

      {signals.length > 0 && <section className="panel discovery-signals"><header><h2>Sinais de mercado</h2><span>{signals.length} fontes</span></header><div className="signal-grid">{signals.map((item) => <article key={item.id}><div><span>{item.code}</span><small>{item.evidence_type}</small></div><h3>{item.pain_statement}</h3><p>{item.observed_signal}</p><p><strong>Sinal comercial:</strong> {item.commercial_signal}</p><footer><span>Força {item.strength}/5 · frequência {item.frequency}/5 · compra {item.willingness_to_pay}/5 · comercial {item.commercial_strength}/5</span><a href={item.source_url} target="_blank" rel="noreferrer">{item.source_title} ↗</a></footer></article>)}</div></section>}

      {runs.length > 0 && <section className="panel discovery-runs"><header><h2>Rastreabilidade e custo</h2><span>{runs.length} chamadas</span></header><div className="panel-body"><table><thead><tr><th>Agente</th><th>Modelo</th><th>Tokens</th><th>Web</th><th>Custo</th><th>Tempo</th></tr></thead><tbody>{runs.map((item) => <tr key={item.id}><td>{item.agent}</td><td>{item.provider} · {item.model}</td><td>{item.input_tokens + item.output_tokens}</td><td>{item.web_search_calls}</td><td>{formatCost(item.estimated_cost)}</td><td>{item.execution_time.toFixed(1)}s</td></tr>)}</tbody></table></div></section>}
    </div>
  );
}
