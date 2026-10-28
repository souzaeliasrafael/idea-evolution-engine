"use client";

import Link from "next/link";
import { FormEvent, useEffect, useState } from "react";

import { api } from "@/lib/api";
import type {
  AgentProfile,
  AgentProfileModel,
  AgentProfilePayload,
  SystemConfig,
  TimelineItem,
} from "@/lib/types";

type Agent = TimelineItem["agent"];

interface ProfileDraft extends AgentProfilePayload {
  id: string | null;
}

const agents: Agent[] = [
  "STRUCTURER",
  "BUILDER",
  "RESEARCHER",
  "CRITIC",
  "JUDGE",
  "IMPROVER",
  "PRODUCT_ARCHITECT",
  "SOLUTION_ARCHITECT",
  "TECHNICAL_CRITIC",
  "ROADMAP_PLANNER",
];
const agentLabels: Record<Agent, string> = {
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

export function ProfileManager() {
  const [profiles, setProfiles] = useState<AgentProfile[]>([]);
  const [systemConfig, setSystemConfig] = useState<SystemConfig | null>(null);
  const [draft, setDraft] = useState<ProfileDraft | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    Promise.all([api.listProfiles(), api.getSystemConfig()])
      .then(([profileItems, config]) => {
        if (!active) return;
        setProfiles(profileItems);
        setSystemConfig(config);
        setDraft(newDraft(config));
      })
      .catch((caught) => {
        if (active) setError(caught instanceof Error ? caught.message : "Falha ao carregar os perfis.");
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  function selectProfile(profile: AgentProfile) {
    setDraft({
      id: profile.id,
      name: profile.name,
      description: profile.description,
      agents: cloneAgents(profile.agents),
    });
    setError(null);
    setNotice(null);
  }

  function startNew() {
    if (!systemConfig) return;
    setDraft(newDraft(systemConfig));
    setError(null);
    setNotice(null);
  }

  function copyServerDefaults() {
    if (!systemConfig || !draft) return;
    setDraft({ ...draft, agents: agentsFromSystem(systemConfig) });
    setNotice("Configuração padrão do servidor copiada para o formulário. Salve para aplicar.");
    setError(null);
  }

  function updateAgent(agent: Agent, field: keyof AgentProfileModel, value: string) {
    setDraft((current) => current ? {
      ...current,
      agents: {
        ...current.agents,
        [agent]: { ...current.agents[agent], [field]: value },
      },
    } : current);
  }

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!draft) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const payload: AgentProfilePayload = {
        name: draft.name.trim(),
        description: draft.description.trim(),
        agents: Object.fromEntries(
          agents.map((agent) => [
            agent,
            {
              ...draft.agents[agent],
              provider: draft.agents[agent].provider.trim(),
              model: draft.agents[agent].model.trim(),
              input_cost_per_million: normalizePrice(draft.agents[agent].input_cost_per_million),
              cached_input_cost_per_million: normalizeOptionalPrice(draft.agents[agent].cached_input_cost_per_million),
              output_cost_per_million: normalizePrice(draft.agents[agent].output_cost_per_million),
            },
          ]),
        ) as AgentProfile["agents"],
      };
      const saved = draft.id
        ? await api.updateProfile(draft.id, payload)
        : await api.createProfile(payload);
      setProfiles((current) => [...current.filter((item) => item.id !== saved.id), saved]
        .sort((a, b) => a.name.localeCompare(b.name, "pt-BR")));
      selectProfile(saved);
      setNotice(draft.id ? "Perfil atualizado." : "Perfil criado.");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Não foi possível salvar o perfil.");
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    if (!draft?.id) return;
    if (!window.confirm(`Excluir o perfil “${draft.name}”? Projetos vinculados voltarão à configuração padrão.`)) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await api.deleteProfile(draft.id);
      setProfiles((current) => current.filter((item) => item.id !== draft.id));
      if (systemConfig) setDraft(newDraft(systemConfig));
      setNotice("Perfil excluído. Projetos vinculados agora usam a configuração padrão.");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Não foi possível excluir o perfil.");
    } finally {
      setBusy(false);
    }
  }

  if (loading) return <div className="page-shell"><div className="state-card">Carregando perfis…</div></div>;

  return (
    <div className="page-shell profile-page">
      <Link className="back-link" href="/">← Voltar aos projetos</Link>
      <section className="hero compact-hero profile-hero">
        <div>
          <p className="eyebrow">Configuração de modelos</p>
          <h1>Escolha a IA de cada agente.</h1>
          <p className="lede">
            Perfis reúnem provedor, modelo e preço por milhão de tokens. Esses preços geram a estimativa imediata que controla o orçamento de cada ideia; a reconciliação da fatura fica no painel Financeiro. As chaves continuam exclusivamente no backend.
          </p>
        </div>
        <button className="button" onClick={startNew} type="button">Novo perfil</button>
      </section>

      {error && <div className="alert alert-error">{error}</div>}
      {notice && <div className="alert alert-success">{notice}</div>}

      <section className="profile-workspace">
        <aside className="profile-list" aria-label="Perfis cadastrados">
          <button className={!draft?.id ? "profile-list-item active" : "profile-list-item"} onClick={startNew} type="button">
            <span>＋ Novo perfil</span>
            <small>Baseado no servidor</small>
          </button>
          {profiles.map((profile) => (
            <button
              className={draft?.id === profile.id ? "profile-list-item active" : "profile-list-item"}
              key={profile.id}
              onClick={() => selectProfile(profile)}
              type="button"
            >
              <span>{profile.name}</span>
              <small>{profile.description || "Sem descrição"}</small>
            </button>
          ))}
          {profiles.length === 0 && <p className="profile-list-empty">Nenhum perfil salvo.</p>}
        </aside>

        {draft && (
          <form className="profile-editor" onSubmit={save}>
            <header>
              <div>
                <p className="eyebrow">{draft.id ? "Editar perfil" : "Novo perfil"}</p>
                <h2>{draft.id ? draft.name : "Configuração personalizada"}</h2>
              </div>
              <button className="button button-secondary" disabled={busy} onClick={copyServerDefaults} type="button">
                Copiar padrão do servidor
              </button>
            </header>

            <div className="profile-main-fields">
              <label>
                Nome do perfil
                <input maxLength={100} required value={draft.name} onChange={(event) => setDraft({ ...draft, name: event.target.value })} />
              </label>
              <label>
                Descrição
                <input maxLength={2000} value={draft.description} onChange={(event) => setDraft({ ...draft, description: event.target.value })} />
              </label>
            </div>

            <div className="profile-agent-grid">
              {agents.map((agent) => {
                const config = draft.agents[agent];
                return (
                  <fieldset className="profile-agent-card" key={agent}>
                    <legend>{agentLabels[agent]}</legend>
                    <label>
                      Provedor
                      <input list="provider-options" maxLength={100} required value={config.provider} onChange={(event) => updateAgent(agent, "provider", event.target.value)} />
                    </label>
                    <label>
                      Modelo
                      <input maxLength={200} required value={config.model} onChange={(event) => updateAgent(agent, "model", event.target.value)} />
                    </label>
                    <div className="profile-price-fields">
                      <label>
                        Entrada / 1M tokens
                        <input inputMode="decimal" min="0" required step="0.000001" type="number" value={config.input_cost_per_million} onChange={(event) => updateAgent(agent, "input_cost_per_million", event.target.value)} />
                      </label>
                      <label>
                        Entrada em cache / 1M
                        <input inputMode="decimal" min="0" placeholder="Mesmo preço da entrada" step="0.000001" type="number" value={config.cached_input_cost_per_million ?? ""} onChange={(event) => updateAgent(agent, "cached_input_cost_per_million", event.target.value)} />
                      </label>
                      <label>
                        Saída / 1M tokens
                        <input inputMode="decimal" min="0" required step="0.000001" type="number" value={config.output_cost_per_million} onChange={(event) => updateAgent(agent, "output_cost_per_million", event.target.value)} />
                      </label>
                    </div>
                  </fieldset>
                );
              })}
            </div>
            <datalist id="provider-options">
              <option value="openai" />
              <option value="anthropic" />
              <option value="gemini" />
              <option value="local" />
              <option value="mock" />
            </datalist>

            <div className="profile-help">
              <strong>Antes de salvar</strong>
              <span>Provedores em nuvem precisam da chave correspondente no `.env` e de preços válidos para o controle de orçamento.</span>
            </div>

            <div className="profile-actions">
              <button className="button" disabled={busy} type="submit">{busy ? "Salvando…" : "Salvar perfil"}</button>
              {draft.id && <button className="button button-danger" disabled={busy} onClick={() => void remove()} type="button">Excluir perfil</button>}
            </div>
          </form>
        )}
      </section>
    </div>
  );
}

function newDraft(config: SystemConfig): ProfileDraft {
  return {
    id: null,
    name: "",
    description: "",
    agents: agentsFromSystem(config),
  };
}

function agentsFromSystem(config: SystemConfig): AgentProfile["agents"] {
  return Object.fromEntries(
    agents.map((agent) => {
      const current = config.providers.find((item) => item.agent === agent);
      return [agent, {
        provider: current?.provider ?? "mock",
        model: current?.model ?? "mock-llm-v1",
        input_cost_per_million: current?.input_cost_per_million ?? "0",
        cached_input_cost_per_million: current?.cached_input_cost_per_million ?? null,
        output_cost_per_million: current?.output_cost_per_million ?? "0",
      }];
    }),
  ) as AgentProfile["agents"];
}

function cloneAgents(source: AgentProfile["agents"]): AgentProfile["agents"] {
  return Object.fromEntries(
    agents.map((agent) => [agent, { ...source[agent] }]),
  ) as AgentProfile["agents"];
}

function normalizePrice(value: string): string {
  const normalized = value.trim().replace(",", ".");
  return normalized || "0";
}

function normalizeOptionalPrice(value: string | null): string | null {
  const normalized = (value ?? "").trim().replace(",", ".");
  return normalized || null;
}
