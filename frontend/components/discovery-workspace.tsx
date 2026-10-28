"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useEffect, useState } from "react";

import { api } from "@/lib/api";
import type { AgentProfile, DiscoveryCampaign, DiscoveryHardConstraints, FounderProfile, FounderProfilePayload } from "@/lib/types";

const defaultHardConstraints: DiscoveryHardConstraints = {
  customer_type: "B2C",
  digital_only: true,
  self_service_only: true,
  min_automation_percent: 90,
  max_mvp_days: 30,
  exclude_recurring_human_service: true,
  exclude_regulated_advice: true,
  exclude_two_sided_marketplaces: true,
  require_recurring_or_repeat_revenue: true,
  require_reachable_channel: true,
  min_demand_sources: 3,
  min_paid_competitors: 2,
  min_market_reality_score: 55,
};

const emptyFounder: FounderProfilePayload = {
  name: "",
  skills: [],
  industries: [],
  available_capital: "5000",
  currency: "BRL",
  hours_per_week: 20,
  target_monthly_revenue: "15000",
  revenue_horizon_days: 90,
  preferred_business_models: ["SaaS", "serviço produtizado"],
  preferred_markets: ["PMEs brasileiras"],
  distribution_assets: [],
  technologies: [],
  exclusions: [],
  risk_tolerance: "MEDIUM",
};

function lines(value: string): string[] {
  return value.split(/[,\n]/).map((item) => item.trim()).filter(Boolean);
}

function founderPayload(profile: FounderProfile): FounderProfilePayload {
  return {
    name: profile.name,
    skills: profile.skills,
    industries: profile.industries,
    available_capital: profile.available_capital,
    currency: profile.currency,
    hours_per_week: profile.hours_per_week,
    target_monthly_revenue: profile.target_monthly_revenue,
    revenue_horizon_days: profile.revenue_horizon_days,
    preferred_business_models: profile.preferred_business_models,
    preferred_markets: profile.preferred_markets,
    distribution_assets: profile.distribution_assets,
    technologies: profile.technologies,
    exclusions: profile.exclusions,
    risk_tolerance: profile.risk_tolerance,
  };
}

function ListField({ label, value, onChange, hint }: { label: string; value: string[]; onChange: (value: string[]) => void; hint?: string }) {
  const [draft, setDraft] = useState(value.join(", "));

  useEffect(() => {
    setDraft(value.join(", "));
  }, [value]);

  return (
    <label>
      {label}
      <textarea
        value={draft}
        onBlur={() => onChange(lines(draft))}
        onChange={(event) => setDraft(event.target.value)}
        rows={2}
      />
      {hint && <small>{hint}</small>}
    </label>
  );
}

export function DiscoveryWorkspace() {
  const router = useRouter();
  const [founders, setFounders] = useState<FounderProfile[]>([]);
  const [campaigns, setCampaigns] = useState<DiscoveryCampaign[]>([]);
  const [agentProfiles, setAgentProfiles] = useState<AgentProfile[]>([]);
  const [founder, setFounder] = useState<FounderProfilePayload>(emptyFounder);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [campaign, setCampaign] = useState({
    name: "Busca de oportunidades digitais",
    brief: "Encontre produtos digitais B2C com comprador específico, evento claro de compra e mercado já demonstrado por comportamento de pagamento.",
    geography: "Brasil",
    max_ai_budget: "0.30",
    candidate_target: 5,
    finalist_target: 2,
    agent_profile_id: "",
    memory_mode: "BALANCED" as "NEW_ONLY" | "BALANCED" | "IMPROVE_APPROVED",
    hard_constraints: defaultHardConstraints,
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    try {
      const [founderData, campaignData, profileData] = await Promise.all([
        api.listFounderProfiles(), api.listDiscoveryCampaigns(), api.listProfiles(),
      ]);
      setFounders(founderData);
      setCampaigns(campaignData);
      setAgentProfiles(profileData);
      if (!editingId && founderData[0]) {
        setEditingId(founderData[0].id);
        setFounder(founderPayload(founderData[0]));
      }
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Não foi possível carregar a descoberta.");
    }
  }

  useEffect(() => { void load(); }, []);

  async function saveFounder(event: FormEvent) {
    event.preventDefault();
    setBusy(true); setError(null);
    try {
      const saved = editingId
        ? await api.updateFounderProfile(editingId, founder)
        : await api.createFounderProfile(founder);
      setEditingId(saved.id);
      setFounder(founderPayload(saved));
      await load();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Não foi possível salvar o perfil.");
    } finally { setBusy(false); }
  }

  async function createCampaign(event: FormEvent) {
    event.preventDefault();
    if (!editingId) { setError("Salve primeiro o seu perfil de fundador."); return; }
    setBusy(true); setError(null);
    try {
      const created = await api.createDiscoveryCampaign({
        founder_profile_id: editingId,
        agent_profile_id: campaign.agent_profile_id || null,
        name: campaign.name,
        brief: campaign.brief,
        geography: campaign.geography,
        language: "pt-BR",
        memory_mode: campaign.memory_mode,
        hard_constraints: campaign.hard_constraints,
        max_ai_budget: campaign.max_ai_budget,
        candidate_target: campaign.candidate_target,
        finalist_target: campaign.finalist_target,
      });
      router.push(`/discover/${created.id}`);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Não foi possível criar a campanha.");
      setBusy(false);
    }
  }

  return (
    <div className="page-shell discovery-page">
      <section className="hero compact-hero discovery-hero">
        <div>
          <p className="eyebrow">Opportunity Discovery</p>
          <h1>Encontre a dor antes de escolher a ideia.</h1>
          <p className="lede">O sistema pesquisa sinais reais, gera negócios compatíveis com você, aprofunda somente os melhores e entrega um ranking auditável.</p>
        </div>
      </section>
      {error && <div className="alert alert-error">{error}</div>}

      <div className="discovery-setup-grid">
        <form className="profile-editor discovery-form" onSubmit={saveFounder}>
          <header>
            <div><p className="eyebrow">1. Seu contexto</p><h2>Perfil do fundador</h2></div>
            {founders.length > 0 && (
              <select value={editingId ?? ""} onChange={(event) => {
                const selected = founders.find((item) => item.id === event.target.value);
                if (selected) { setEditingId(selected.id); setFounder(founderPayload(selected)); }
              }}>
                {founders.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
              </select>
            )}
          </header>
          <div className="profile-main-fields">
            <label>Nome<input required value={founder.name} onChange={(e) => setFounder({ ...founder, name: e.target.value })} /></label>
            <ListField label="Habilidades" value={founder.skills} onChange={(value) => setFounder({ ...founder, skills: value })} />
          </div>
          <div className="discovery-numeric-grid">
            <label>Capital disponível (BRL)<input type="number" min="0" value={founder.available_capital} onChange={(e) => setFounder({ ...founder, available_capital: e.target.value })} /></label>
            <label>Horas por semana<input type="number" min="1" max="168" value={founder.hours_per_week} onChange={(e) => setFounder({ ...founder, hours_per_week: Number(e.target.value) })} /></label>
            <label>Meta mensal (BRL)<input type="number" min="0" value={founder.target_monthly_revenue} onChange={(e) => setFounder({ ...founder, target_monthly_revenue: e.target.value })} /></label>
            <label>Prazo para receita (dias)<input type="number" min="7" value={founder.revenue_horizon_days} onChange={(e) => setFounder({ ...founder, revenue_horizon_days: Number(e.target.value) })} /></label>
          </div>
          <div className="discovery-list-grid">
            <ListField label="Experiência em setores" value={founder.industries} onChange={(value) => setFounder({ ...founder, industries: value })} />
            <ListField label="Modelos preferidos" value={founder.preferred_business_models} onChange={(value) => setFounder({ ...founder, preferred_business_models: value })} />
            <ListField label="Mercados preferidos" value={founder.preferred_markets} onChange={(value) => setFounder({ ...founder, preferred_markets: value })} />
            <ListField label="Canais e audiência que já possui" value={founder.distribution_assets} onChange={(value) => setFounder({ ...founder, distribution_assets: value })} />
            <ListField label="Tecnologias" value={founder.technologies} onChange={(value) => setFounder({ ...founder, technologies: value })} />
            <ListField label="O que não quer fazer" value={founder.exclusions} onChange={(value) => setFounder({ ...founder, exclusions: value })} />
          </div>
          <label>Tolerância a risco<select value={founder.risk_tolerance} onChange={(e) => setFounder({ ...founder, risk_tolerance: e.target.value as FounderProfilePayload["risk_tolerance"] })}><option value="LOW">Baixa</option><option value="MEDIUM">Média</option><option value="HIGH">Alta</option></select></label>
          <button className="button" disabled={busy}>{editingId ? "Atualizar perfil" : "Salvar perfil"}</button>
        </form>

        <form className="profile-editor discovery-form campaign-form" onSubmit={createCampaign}>
          <header><div><p className="eyebrow">2. A busca</p><h2>Nova campanha</h2></div></header>
          <label>Nome<input required value={campaign.name} onChange={(e) => setCampaign({ ...campaign, name: e.target.value })} /></label>
          <label>Foco ou restrições adicionais<textarea rows={4} value={campaign.brief} onChange={(e) => setCampaign({ ...campaign, brief: e.target.value })} /></label>
          <label>Geografia<input required value={campaign.geography} onChange={(e) => setCampaign({ ...campaign, geography: e.target.value })} /></label>
          <label>Perfil dos agentes<select value={campaign.agent_profile_id} onChange={(e) => setCampaign({ ...campaign, agent_profile_id: e.target.value })}><option value="">Configuração padrão do servidor</option>{agentProfiles.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select><small>Scout/Researcher usam o modelo do Researcher; Generator usa Structurer; ranking usa Judge.</small></label>
          <label>Como usar ideias anteriores<select value={campaign.memory_mode} onChange={(e) => setCampaign({ ...campaign, memory_mode: e.target.value as typeof campaign.memory_mode })}><option value="NEW_ONLY">Somente ideias novas</option><option value="BALANCED">Equilibrado: evitar rejeitadas e duplicatas</option><option value="IMPROVE_APPROVED">Aprofundar ideias que aprovei</option></select><small>A memória usa apenas campanhas vinculadas ao mesmo perfil de fundador.</small></label>
          <fieldset className="constraint-editor">
            <legend>Regras eliminatórias</legend>
            <p>Uma ideia que viole estas condições é descartada antes da pesquisa aprofundada.</p>
            <div className="discovery-numeric-grid">
              <label>Público obrigatório<select value={campaign.hard_constraints.customer_type} onChange={(e) => setCampaign({ ...campaign, hard_constraints: { ...campaign.hard_constraints, customer_type: e.target.value as DiscoveryHardConstraints["customer_type"] } })}><option value="B2C">B2C — consumidor</option><option value="B2B">B2B — empresas</option><option value="ANY">Qualquer público</option></select></label>
              <label>Automação mínima (%)<input type="number" min="0" max="100" value={campaign.hard_constraints.min_automation_percent} onChange={(e) => setCampaign({ ...campaign, hard_constraints: { ...campaign.hard_constraints, min_automation_percent: Number(e.target.value) } })} /></label>
              <label>Prazo máximo do MVP (dias)<input type="number" min="1" max="365" value={campaign.hard_constraints.max_mvp_days} onChange={(e) => setCampaign({ ...campaign, hard_constraints: { ...campaign.hard_constraints, max_mvp_days: Number(e.target.value) } })} /></label>
            </div>
            <div className="constraint-checks">
              {([
                ["digital_only", "Somente produto digital"],
                ["self_service_only", "Somente self-service"],
                ["exclude_recurring_human_service", "Excluir operação humana recorrente"],
                ["exclude_regulated_advice", "Excluir aconselhamento regulado"],
                ["exclude_two_sided_marketplaces", "Excluir marketplace de dois lados"],
                ["require_recurring_or_repeat_revenue", "Exigir recorrência ou recompra"],
                ["require_reachable_channel", "Exigir canal de aquisição acessível"],
              ] as const).map(([key, label]) => <label key={key}><input type="checkbox" checked={campaign.hard_constraints[key]} onChange={(e) => setCampaign({ ...campaign, hard_constraints: { ...campaign.hard_constraints, [key]: e.target.checked } })} />{label}</label>)}
            </div>
            <div className="discovery-numeric-grid">
              <label>Fontes de demanda mínimas<input type="number" min="1" max="10" value={campaign.hard_constraints.min_demand_sources} onChange={(e) => setCampaign({ ...campaign, hard_constraints: { ...campaign.hard_constraints, min_demand_sources: Number(e.target.value) } })} /></label>
              <label>Concorrentes pagos mínimos<input type="number" min="0" max="10" value={campaign.hard_constraints.min_paid_competitors} onChange={(e) => setCampaign({ ...campaign, hard_constraints: { ...campaign.hard_constraints, min_paid_competitors: Number(e.target.value) } })} /></label>
              <label>Market Reality mínimo<input type="number" min="0" max="100" value={campaign.hard_constraints.min_market_reality_score} onChange={(e) => setCampaign({ ...campaign, hard_constraints: { ...campaign.hard_constraints, min_market_reality_score: Number(e.target.value) } })} /></label>
            </div>
          </fieldset>
          <div className="discovery-numeric-grid">
            <label>Orçamento máximo (USD)<input type="number" min="0.01" step="0.01" required value={campaign.max_ai_budget} onChange={(e) => setCampaign({ ...campaign, max_ai_budget: e.target.value })} /></label>
            <label>Ideias geradas<input type="number" min="3" max="5" value={campaign.candidate_target} onChange={(e) => setCampaign({ ...campaign, candidate_target: Number(e.target.value) })} /></label>
            <label>Finalistas<input type="number" min="1" max="3" value={campaign.finalist_target} onChange={(e) => setCampaign({ ...campaign, finalist_target: Number(e.target.value) })} /></label>
          </div>
          <div className="discovery-cost-note"><strong>Até 4 chamadas limitadas</strong><span>Scout comercial com web → 3–5 ideias → filtros eliminatórios → pesquisa profunda somente das melhores → Market Reality Gate → Portfolio Judge.</span></div>
          <button className="button" disabled={busy || !editingId}>Criar campanha</button>
        </form>
      </div>

      <section className="campaign-history">
        <header><div><p className="eyebrow">Histórico</p><h2>Campanhas de descoberta</h2></div></header>
        {campaigns.length === 0 ? <div className="empty-state"><p>Nenhuma campanha criada.</p></div> : (
          <div className="project-grid">
            {campaigns.map((item) => (
              <Link className="project-card campaign-card" href={`/discover/${item.id}`} key={item.id}>
                <div className="card-heading"><h2>{item.name}</h2><span className={`status status-${item.status.toLowerCase()}`}>{item.status}</span></div>
                <p className="idea-preview">{item.brief || "Busca ampla de oportunidades."}</p>
                <div className="metric-row"><div className="metric"><span>Candidatas</span><strong>{item.candidate_target}</strong></div><div className="metric"><span>Finalistas</span><strong>{item.finalist_target}</strong></div><div className="metric"><span>Custo</span><strong>${Number(item.total_cost).toFixed(3)}</strong></div></div>
              </Link>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
