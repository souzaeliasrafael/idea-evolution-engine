"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { api, formatConfidence, formatCost } from "@/lib/api";
import type { Project, ProjectScore, Round } from "@/lib/types";

interface ProjectSummary {
  project: Project;
  score: ProjectScore | null;
  round: Round | null;
}

export function Dashboard() {
  const router = useRouter();
  const [items, setItems] = useState<ProjectSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  async function restoreBackup(file: File | undefined) {
    if (!file) return;
    setError(null);
    try {
      const payload = JSON.parse(await file.text()) as unknown;
      const project = await api.restoreBackup(payload);
      router.push(`/projects/${project.id}`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Backup inválido.");
    }
  }

  useEffect(() => {
    let active = true;
    async function load() {
      try {
        const projects = await api.listProjects();
        const summaries = await Promise.all(
          projects.map(async (project) => {
            const [scores, rounds] = await Promise.all([
              api.listScores(project.id),
              api.listRounds(project.id),
            ]);
            return {
              project,
              score: scores.at(-1) ?? null,
              round: rounds.at(-1) ?? null,
            };
          }),
        );
        if (active) setItems(summaries);
      } catch (caught) {
        if (active) setError(caught instanceof Error ? caught.message : "Falha ao carregar projetos.");
      } finally {
        if (active) setLoading(false);
      }
    }
    void load();
    return () => {
      active = false;
    };
  }, []);

  return (
    <div className="page-shell">
      <section className="hero compact-hero">
        <div>
          <p className="eyebrow">Painel de avaliação</p>
          <h1>Ideias com limites claros e decisões rastreáveis.</h1>
          <p className="lede">
            Acompanhe score, confiança, rodadas e custo antes de investir em construção.
          </p>
        </div>
        <div className="hero-actions">
          <label className="button button-secondary file-button">
            Restaurar backup
            <input accept="application/json,.json" onChange={(event) => void restoreBackup(event.target.files?.[0])} type="file" />
          </label>
          <Link className="button" href="/new">
            Avaliar nova ideia
          </Link>
        </div>
      </section>

      {loading && <div className="state-card">Carregando projetos…</div>}
      {error && <div className="alert alert-error">{error}</div>}
      {!loading && !error && items.length === 0 && (
        <section className="empty-state">
          <span className="empty-glyph">◇</span>
          <h2>Nenhuma ideia em avaliação</h2>
          <p>Crie o primeiro projeto e defina quanto os agentes podem consumir.</p>
          <Link className="button" href="/new">
            Criar primeira ideia
          </Link>
        </section>
      )}

      <section className="project-grid" aria-label="Projetos">
        {items.map(({ project, score, round }) => (
          <Link className="project-card" href={`/projects/${project.id}`} key={project.id}>
            <div className="card-heading">
              <div>
                <span className="project-date">
                  {new Date(project.created_at).toLocaleDateString("pt-BR")}
                </span>
                <h2>{project.name}</h2>
              </div>
              <StatusBadge status={project.status} />
            </div>
            <p className="idea-preview">{project.raw_idea}</p>
            <div className="metric-row">
              <Metric label="Score" value={score ? `${score.total_score}` : "—"} />
              <Metric label="Confiança" value={formatConfidence(score?.confidence)} />
              <Metric label="Rodada" value={round ? `${round.round_number}` : "0"} />
            </div>
            <div className="cost-line">
              <span>Custo estimado</span>
              <strong>{formatCost(project.total_cost)}</strong>
            </div>
            {project.max_ai_budget !== null && (
              <div className="budget-track" aria-label="Uso do orçamento">
                <span
                  style={{
                    width: `${Math.min(
                      100,
                      (Number(project.total_cost) / Math.max(Number(project.max_ai_budget), 0.000001)) * 100,
                    )}%`,
                  }}
                />
              </div>
            )}
          </Link>
        ))}
      </section>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="metric">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

export function StatusBadge({ status }: { status: string }) {
  return <span className={`status status-${status.toLowerCase()}`}>{status}</span>;
}
