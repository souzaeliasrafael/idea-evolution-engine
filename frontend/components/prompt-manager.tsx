"use client";

import Link from "next/link";
import { FormEvent, useEffect, useMemo, useState } from "react";

import { api } from "@/lib/api";
import type { AgentPrompt, AgentPromptVersion, PromptAgent } from "@/lib/types";

const agentLabels: Record<PromptAgent, string> = {
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
  OPPORTUNITY_SCOUT: "Opportunity Scout",
  IDEA_GENERATOR: "Idea Generator",
  OPPORTUNITY_RESEARCHER: "Opportunity Researcher",
  PORTFOLIO_JUDGE: "Portfolio Judge",
};

const discoveryAgents = new Set<PromptAgent>([
  "OPPORTUNITY_SCOUT", "IDEA_GENERATOR", "OPPORTUNITY_RESEARCHER", "PORTFOLIO_JUDGE",
]);

export function PromptManager() {
  const [prompts, setPrompts] = useState<AgentPrompt[]>([]);
  const [selectedAgent, setSelectedAgent] = useState<PromptAgent>("STRUCTURER");
  const [draft, setDraft] = useState("");
  const [versions, setVersions] = useState<AgentPromptVersion[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const selected = useMemo(
    () => prompts.find((item) => item.agent === selectedAgent) ?? null,
    [prompts, selectedAgent],
  );

  useEffect(() => {
    let active = true;
    Promise.all([api.listPrompts(), api.listDiscoveryPrompts()])
      .then(([standard, discovery]) => {
        if (!active) return;
        const items = [...standard, ...discovery];
        setPrompts(items);
        const initial = items.find((item) => item.agent === selectedAgent);
        if (initial) setDraft(initial.content);
      })
      .catch((caught) => {
        if (active) setError(caught instanceof Error ? caught.message : "Falha ao carregar os prompts.");
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    if (selected) setDraft(selected.content);
    const listVersions = discoveryAgents.has(selectedAgent)
      ? api.listDiscoveryPromptVersions(selectedAgent)
      : api.listPromptVersions(selectedAgent);
    listVersions.then(setVersions).catch(() => setVersions([]));
  }, [selected, selectedAgent]);

  function replacePrompt(updated: AgentPrompt) {
    setPrompts((current) => current.map((item) => item.agent === updated.agent ? updated : item));
    setDraft(updated.content);
  }

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const updated = discoveryAgents.has(selectedAgent)
        ? await api.updateDiscoveryPrompt(selectedAgent, draft)
        : await api.updatePrompt(selectedAgent, draft);
      replacePrompt(updated);
      setVersions(discoveryAgents.has(selectedAgent)
        ? await api.listDiscoveryPromptVersions(selectedAgent)
        : await api.listPromptVersions(selectedAgent));
      setNotice(`${agentLabels[selectedAgent]} salvo como ${updated.version}.`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Não foi possível salvar o prompt.");
    } finally {
      setBusy(false);
    }
  }

  async function reset() {
    if (!window.confirm(`Restaurar o prompt padrão do ${agentLabels[selectedAgent]}? O histórico personalizado será preservado.`)) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const updated = discoveryAgents.has(selectedAgent)
        ? await api.resetDiscoveryPrompt(selectedAgent)
        : await api.resetPrompt(selectedAgent);
      replacePrompt(updated);
      setVersions(discoveryAgents.has(selectedAgent)
        ? await api.listDiscoveryPromptVersions(selectedAgent)
        : await api.listPromptVersions(selectedAgent));
      setNotice(`${agentLabels[selectedAgent]} restaurado para ${updated.default_version}.`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Não foi possível restaurar o prompt.");
    } finally {
      setBusy(false);
    }
  }

  if (loading) return <div className="page-shell"><div className="state-card">Carregando prompts…</div></div>;

  return (
    <div className="page-shell prompt-page">
      <Link className="back-link" href="/">← Voltar aos projetos</Link>
      <section className="hero compact-hero prompt-hero">
        <div>
          <p className="eyebrow">Configuração dos agentes</p>
          <h1>Controle o raciocínio sem alterar o contrato.</h1>
          <p className="lede">
            Cada salvamento cria uma nova versão. O schema JSON, os limites e a validação permanecem protegidos no backend.
          </p>
        </div>
      </section>

      {error && <div className="alert alert-error">{error}</div>}
      {notice && <div className="alert alert-success">{notice}</div>}

      <section className="prompt-workspace">
        <aside className="prompt-agent-list" aria-label="Agentes">
          {prompts.map((item) => (
            <button
              className={item.agent === selectedAgent ? "prompt-agent active" : "prompt-agent"}
              key={item.agent}
              onClick={() => {
                setSelectedAgent(item.agent);
                setError(null);
                setNotice(null);
              }}
              type="button"
            >
              <span>{agentLabels[item.agent]}</span>
              <small>{item.version}{item.customized ? " · personalizado" : " · padrão"}</small>
            </button>
          ))}
        </aside>

        {selected && (
          <form className="prompt-editor" onSubmit={save}>
            <header>
              <div>
                <p className="eyebrow">{selected.agent}</p>
                <h2>{agentLabels[selected.agent]}</h2>
              </div>
              <span className={selected.customized ? "prompt-version custom" : "prompt-version"}>
                {selected.version}
              </span>
            </header>

            <label htmlFor="agent-prompt">Instruções do agente</label>
            <textarea
              id="agent-prompt"
              maxLength={20_000}
              minLength={20}
              required
              rows={24}
              spellCheck
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
            />
            <div className="prompt-editor-meta">
              <small>{draft.length.toLocaleString("pt-BR")} / 20.000 caracteres</small>
              <small>Afeta apenas novas execuções; rodadas em andamento não mudam.</small>
            </div>

            <div className="prompt-actions">
              <button className="button" disabled={busy || draft.trim() === selected.content} type="submit">
                {busy ? "Salvando…" : "Salvar nova versão"}
              </button>
              <button className="button button-secondary" disabled={busy || !selected.customized} onClick={() => void reset()} type="button">
                Restaurar padrão
              </button>
            </div>

            <details className="prompt-default">
              <summary>Ver prompt padrão {selected.default_version}</summary>
              <pre>{selected.default_content}</pre>
            </details>

            <section className="prompt-history">
              <h3>Histórico personalizado</h3>
              {versions.length === 0 ? (
                <p className="muted">Nenhuma versão personalizada criada.</p>
              ) : (
                <ol>
                  {versions.map((item) => (
                    <li key={item.id}>
                      <div>
                        <strong>custom-v{item.version}</strong>
                        {item.is_active && <span>ativa</span>}
                      </div>
                      <small>{new Date(item.created_at).toLocaleString("pt-BR")}</small>
                    </li>
                  ))}
                </ol>
              )}
            </section>
          </form>
        )}
      </section>
    </div>
  );
}
