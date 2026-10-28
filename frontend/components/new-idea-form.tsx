"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useEffect, useRef, useState } from "react";

import { api } from "@/lib/api";
import type { AgentExecutionPlan, AgentProfile } from "@/lib/types";

const agentDepthOptions = [
  { value: 0, label: "0 · Desativado" },
  { value: 1, label: "1 · Padrão" },
  { value: 2, label: "2 · Aprofundado" },
  { value: 3, label: "3 · Intensivo" },
];

export function NewIdeaForm() {
  const router = useRouter();
  const [name, setName] = useState("");
  const [idea, setIdea] = useState("");
  const [budget, setBudget] = useState("");
  const [profileId, setProfileId] = useState("");
  const [agentPlan, setAgentPlan] = useState<AgentExecutionPlan>({
    builder: 1,
    researcher: 1,
    critic: 1,
  });
  const [profiles, setProfiles] = useState<AgentProfile[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [createdId, setCreatedId] = useState<string | null>(null);
  const [progress, setProgress] = useState("Preparando a avaliação");
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const [stopping, setStopping] = useState(false);
  const activeRunController = useRef<AbortController | null>(null);

  useEffect(() => {
    api.listProfiles().then(setProfiles).catch(() => setProfiles([]));
  }, []);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    setCreatedId(null);
    setProgress("Criando o projeto");
    setElapsedSeconds(0);
    const startedAt = Date.now();
    const elapsedTimer = window.setInterval(() => {
      setElapsedSeconds(Math.floor((Date.now() - startedAt) / 1000));
    }, 1000);
    let progressTimer: number | undefined;
    try {
      const normalizedBudget = budget.trim().replace(",", ".");
      if (normalizedBudget && !/^\d+(?:\.\d{1,6})?$/.test(normalizedBudget)) {
        throw new Error("Informe o orçamento usando até seis casas decimais, como 0,05.");
      }
      if (agentPlan.builder + agentPlan.researcher + agentPlan.critic === 0) {
        throw new Error("Mantenha ao menos Builder, Researcher ou Critic ativo.");
      }
      const project = await api.createProject({
        name,
        raw_idea: idea,
        max_ai_budget: normalizedBudget || null,
        agent_profile_id: profileId || null,
        agent_plan: agentPlan,
      });
      setCreatedId(project.id);
      setProgress("Estruturação inicial");
      const controller = new AbortController();
      activeRunController.current = controller;
      progressTimer = window.setInterval(async () => {
        try {
          const status = await api.getRunStatus(project.id);
          setProgress(status.workflow_stage ?? "Preparando a próxima etapa");
        } catch {
          // A transient polling failure must not interrupt the evaluation itself.
        }
      }, 2500);
      await api.runProject(project.id, 1, controller.signal);
      router.push(`/projects/${project.id}`);
    } catch (caught) {
      if (!(caught instanceof DOMException && caught.name === "AbortError")) {
        setError(caught instanceof Error ? caught.message : "Não foi possível iniciar a avaliação.");
      }
    } finally {
      activeRunController.current = null;
      window.clearInterval(elapsedTimer);
      if (progressTimer !== undefined) window.clearInterval(progressTimer);
      setSubmitting(false);
    }
  }

  async function stopInitialEvaluation() {
    if (!createdId) return;
    setStopping(true);
    setError(null);
    try {
      await api.cancelRun(createdId);
      activeRunController.current?.abort();
      router.push(`/projects/${createdId}`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Não foi possível interromper a avaliação.");
      setStopping(false);
    }
  }

  return (
    <div className="form-shell">
      <Link className="back-link" href="/">
        ← Voltar aos projetos
      </Link>
      <div className="form-intro">
        <p className="eyebrow">Nova avaliação</p>
        <h1>Descreva a ideia como ela existe hoje.</h1>
        <p>
          Os agentes vão estruturar, pesquisar, criticar e julgar a proposta em uma rodada inicial.
          Você poderá continuar a evolução na tela do projeto.
        </p>
      </div>
      <form className="idea-form" onSubmit={submit}>
        <label>
          Nome do projeto
          <input
            required
            maxLength={200}
            placeholder="Ex.: Validação de onboarding B2B"
            value={name}
            onChange={(event) => setName(event.target.value)}
          />
        </label>
        <label>
          Descreva sua ideia
          <textarea
            required
            maxLength={50000}
            rows={12}
            placeholder="Qual problema existe, para quem, e como você imagina resolvê-lo? Inclua contexto, restrições e o que ainda é incerto."
            value={idea}
            onChange={(event) => setIdea(event.target.value)}
          />
          <small>{idea.length.toLocaleString("pt-BR")} / 50.000 caracteres</small>
        </label>
        <label>
          Perfil dos agentes (opcional)
          <select value={profileId} onChange={(event) => setProfileId(event.target.value)}>
            <option value="">Configuração padrão do servidor</option>
            {profiles.map((profile) => (
              <option key={profile.id} value={profile.id}>{profile.name}</option>
            ))}
          </select>
          <small>O perfil define provider, modelo e preços de cada agente sem armazenar chaves.</small>
        </label>
        <fieldset className="agent-plan-fieldset">
          <legend>Profundidade máxima dos agentes</legend>
          <p>
            A primeira passagem usa um especialista por etapa. O sistema só usa
            chamadas extras quando score ou confiança justificarem; use 0 para desativar.
          </p>
          <div className="agent-plan-grid">
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
            Structurer prepara a ideia inicial e Judge fecha cada rodada; ambos são
            automáticos. Mais chamadas consomem mais do orçamento de IA.
          </small>
        </fieldset>
        <label>
          Orçamento máximo de IA (opcional)
          <div className="money-input">
            <span>$</span>
            <input
              inputMode="decimal"
              pattern="[0-9]+([,.][0-9]{1,6})?"
              placeholder="0,05"
              value={budget}
              onChange={(event) => setBudget(event.target.value)}
            />
          </div>
          <small>Quando o total for atingido, nenhuma nova chamada de modelo será iniciada.</small>
        </label>
        {error && (
          <div className="alert alert-error">
            {error}
            {createdId && (
              <Link href={`/projects/${createdId}`}>Abrir o projeto criado</Link>
            )}
          </div>
        )}
        {submitting && (
          <div className="evaluation-progress" role="status" aria-live="polite">
            <span className="progress-spinner" aria-hidden="true" />
            <div>
              <strong>{progress}</strong>
              <small>
                {elapsedSeconds}s decorridos. Cada agente pode levar alguns segundos para responder.
              </small>
            </div>
            {createdId && (
              <button
                className="button button-danger button-small"
                disabled={stopping}
                onClick={() => void stopInitialEvaluation()}
                type="button"
              >
                {stopping ? "Parando…" : "Parar avaliação"}
              </button>
            )}
          </div>
        )}
        <button className="button button-wide" disabled={submitting} type="submit">
          {submitting ? "Avaliando…" : "Iniciar avaliação"}
        </button>
      </form>
    </div>
  );
}
