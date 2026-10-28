"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import type { FormEvent, ReactNode } from "react";

import { api } from "@/lib/api";
import type { FinanceOverview } from "@/lib/types";

const AGENT_LABELS: Record<string, string> = {
  STRUCTURER: "Estruturador",
  BUILDER: "Builder",
  RESEARCHER: "Pesquisador",
  CRITIC: "Crítico",
  JUDGE: "Juiz",
  IMPROVER: "Melhorador",
  PRODUCT_ARCHITECT: "Arquiteto de produto",
  SOLUTION_ARCHITECT: "Arquiteto de solução",
  TECHNICAL_CRITIC: "Crítico técnico",
  ROADMAP_PLANNER: "Planejador de roadmap",
};

function money(value: string | number) {
  const amount = Number(value);
  const digits = Math.abs(amount) < 0.01 && amount !== 0 ? 6 : 2;
  return new Intl.NumberFormat("pt-BR", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(amount);
}

function integer(value: number) {
  return new Intl.NumberFormat("pt-BR").format(value);
}

function dateTime(value: string | null) {
  return value
    ? new Intl.DateTimeFormat("pt-BR", { dateStyle: "short", timeStyle: "short" }).format(new Date(value))
    : "Nunca";
}

function providerName(value: string) {
  if (value.toLowerCase() === "openai") return "OpenAI";
  return value.charAt(0).toUpperCase() + value.slice(1);
}

function barHeight(value: string, maximum: number) {
  const amount = Number(value);
  return amount > 0 && maximum > 0 ? `${Math.max(2, amount / maximum * 100)}%` : "0";
}

export function FinanceDashboard() {
  const [days, setDays] = useState(30);
  const [data, setData] = useState<FinanceOverview | null>(null);
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [noticeTone, setNoticeTone] = useState<"success" | "warning">("success");
  const [manual, setManual] = useState({
    provider: "anthropic",
    model: "",
    amount: "",
    date: new Date().toISOString().slice(0, 10),
    lineItem: "",
    note: "",
  });

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setData(await api.getFinanceOverview(days));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Falha ao carregar o financeiro.");
    } finally {
      setLoading(false);
    }
  }, [days]);

  useEffect(() => {
    void load();
  }, [load]);

  async function sync(provider: string) {
    setSyncing(provider);
    setError(null);
    setNotice(null);
    try {
      const result = await api.syncFinanceProvider(provider, days);
      if (result.entries_seen === 0) {
        setNoticeTone("warning");
        setNotice(`${providerName(provider)} respondeu sem custos disponíveis. O faturamento pode ainda estar sendo processado; tente sincronizar novamente em alguns minutos.`);
      } else {
        setNoticeTone("success");
        setNotice(`${providerName(provider)} sincronizada: ${result.entries_written} lançamento(s).`);
      }
      await load();
    } catch (caught) {
      const message = caught instanceof Error ? caught.message : "Falha ao sincronizar o provedor.";
      await load();
      setError(message);
    } finally {
      setSyncing(null);
    }
  }

  async function addManualCost(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true);
    setError(null);
    setNotice(null);
    const start = new Date(`${manual.date}T00:00:00.000Z`);
    const end = new Date(start);
    end.setUTCDate(end.getUTCDate() + 1);
    try {
      await api.addManualCost({
        provider: manual.provider,
        period_start: start.toISOString(),
        period_end: end.toISOString(),
        amount: manual.amount,
        currency: "USD",
        model: manual.model || null,
        line_item: manual.lineItem || null,
        note: manual.note || null,
      });
      setManual((current) => ({ ...current, amount: "", lineItem: "", note: "" }));
      setNotice("Custo manual adicionado.");
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Falha ao registrar o custo.");
    } finally {
      setSaving(false);
    }
  }

  const chartMax = useMemo(() => {
    if (!data) return 0;
    return Math.max(0, ...data.daily.flatMap((item) => [Number(item.estimated_cost), Number(item.reconciled_cost)]));
  }, [data]);

  if (loading && !data) {
    return <div className="page-shell"><div className="state-card">Carregando painel financeiro…</div></div>;
  }

  return (
    <div className="page-shell finance-page">
      <section className="hero compact-hero finance-hero">
        <div>
          <p className="eyebrow">Controle financeiro</p>
          <h1>Estimativas rápidas. Faturas reconciliadas.</h1>
          <p className="lede">Acompanhe custo, tokens e orçamento por provedor, modelo, agente e projeto sem misturar estimativa operacional com cobrança oficial.</p>
        </div>
        <div className="finance-toolbar">
          <label>
            Período
            <select value={days} onChange={(event) => setDays(Number(event.target.value))}>
              <option value={7}>7 dias</option>
              <option value={30}>30 dias</option>
              <option value={90}>90 dias</option>
              <option value={365}>365 dias</option>
            </select>
          </label>
          <button className="button button-secondary" disabled={loading} onClick={() => void load()} type="button">{loading ? "Atualizando…" : "Atualizar"}</button>
        </div>
      </section>

      {error && <div className="alert alert-error">{error}</div>}
      {notice && <div className={`alert alert-${noticeTone}`}>{notice}</div>}

      {data && (
        <>
          <section className="finance-summary" aria-label="Resumo financeiro">
            <FinanceCard label={`Estimado · ${days} dias`} value={money(data.summary.estimated_cost)} detail={`${integer(data.summary.total_runs)} execuções`} />
            <FinanceCard label={`Reconciliado · ${days} dias`} value={money(data.summary.reconciled_cost)} detail="Cobrança do provedor + lançamentos manuais" />
            <FinanceCard label="Diferença" value={money(data.summary.variance)} detail="Reconciliado menos estimado" tone={Number(data.summary.variance) > 0 ? "warning" : "normal"} />
            <FinanceCard label="Estimado total" value={money(data.summary.all_time_estimated_cost)} detail={`${money(data.summary.configured_budget)} em orçamentos configurados`} />
          </section>

          <section className="finance-kpis" aria-label="Uso de tokens e alertas">
            <div><span>Tokens de entrada</span><strong>{integer(data.summary.input_tokens)}</strong></div>
            <div><span>Tokens em cache</span><strong>{integer(data.summary.cached_input_tokens)}</strong></div>
            <div><span>Tokens de saída</span><strong>{integer(data.summary.output_tokens)}</strong></div>
            <div><span>Tokens de raciocínio</span><strong>{integer(data.summary.reasoning_tokens)}</strong></div>
            <div><span>Buscas web</span><strong>{integer(data.summary.web_search_calls)}</strong></div>
            <div><span>Custo de ferramentas</span><strong>{money(data.summary.tool_cost)}</strong></div>
            <div><span>Projetos no limite</span><strong>{integer(data.summary.projects_at_or_over_budget)}</strong></div>
          </section>

          <section className="finance-explainer">
            <div><strong>Orçamento das ideias</strong><span>Usa a estimativa instantânea dos preços definidos nos perfis e pode interromper o loop antes de outra chamada.</span></div>
            <div><strong>Fatura reconciliada</strong><span>Vem do provedor ou de lançamento manual. Custos agregados não são atribuídos artificialmente a um projeto interno.</span></div>
          </section>

          {(data.summary.unpriced_runs > 0 || data.summary.unsupported_currency_entries > 0) && (
            <div className="alert alert-warning">
              {data.summary.unpriced_runs > 0 && <span>{data.summary.unpriced_runs} execução(ões) de nuvem sem preço configurado.</span>}
              {data.summary.unsupported_currency_entries > 0 && <span>{data.summary.unsupported_currency_entries} lançamento(s) fora de USD não entram nos totais.</span>}
            </div>
          )}

          <section className="finance-connectors">
            <header><div><p className="eyebrow">Conectores de faturamento</p><h2>Reconciliação oficial</h2></div></header>
            <div className="connector-grid">
              {data.connectors.map((connector) => (
                <article className="connector-card" key={connector.provider}>
                  <div className="connector-heading">
                    <div><strong>{providerName(connector.provider)}</strong><small>Última sincronização: {dateTime(connector.last_synced_at)}</small></div>
                    <span className={`connector-status ${connector.configured ? "ready" : "pending"}`}>{connector.configured ? "Configurado" : "Pendente"}</span>
                  </div>
                  <p>{connector.guidance}</p>
                  {!connector.configured && connector.provider === "openai" && <code>OPENAI_ADMIN_KEY</code>}
                  <button className="button button-small" disabled={!connector.configured || syncing !== null} onClick={() => void sync(connector.provider)} type="button">
                    {syncing === connector.provider ? "Sincronizando…" : `Sincronizar ${days} dias`}
                  </button>
                </article>
              ))}
              <article className="connector-card connector-future">
                <div><strong>Outros provedores</strong><small>Anthropic, Gemini, OpenRouter e futuros serviços</small></div>
                <p>Registre abaixo um custo manual agora. Quando houver uma API de cobrança disponível, basta adicionar um adaptador no backend.</p>
              </article>
            </div>
          </section>

          <section className="panel finance-chart-panel">
            <header><h2>Evolução diária</h2><span>USD · últimos {days} dias</span></header>
            <div className="panel-body">
              <div className="chart-legend"><span className="estimated">Estimado</span><span className="reconciled">Reconciliado</span></div>
              <div className="cost-chart" aria-label="Gráfico de custos diários">
                {data.daily.map((item) => (
                  <div className="cost-day" key={item.date} title={`${item.date}: estimado ${money(item.estimated_cost)}, reconciliado ${money(item.reconciled_cost)}`}>
                    <div className="cost-bars">
                      <span className="estimated" style={{ height: barHeight(item.estimated_cost, chartMax) }} />
                      <span className="reconciled" style={{ height: barHeight(item.reconciled_cost, chartMax) }} />
                    </div>
                    {(data.daily.length <= 31 || item.date.endsWith("-01")) && <small>{item.date.slice(5)}</small>}
                  </div>
                ))}
              </div>
            </div>
          </section>

          <div className="finance-two-column">
            <FinanceTable title="Por provedor" count={data.by_provider.length} headers={["Provedor", "Execuções", "Buscas / ferramentas", "Estimado", "Reconciliado", "Diferença"]}>
              {data.by_provider.map((item) => <tr key={item.provider}><td><strong>{providerName(item.provider)}</strong><small>{item.models.join(", ") || "Sem modelo identificado"}</small></td><td>{integer(item.runs)}</td><td>{integer(item.web_search_calls)} / {money(item.tool_cost)}</td><td>{money(item.estimated_cost)}</td><td>{money(item.reconciled_cost)}</td><td>{money(item.variance)}</td></tr>)}
            </FinanceTable>
            <FinanceTable title="Por agente" count={data.by_agent.length} headers={["Agente", "Execuções", "Entrada / saída", "Buscas / ferramentas", "Estimado"]}>
              {data.by_agent.map((item) => <tr key={item.agent}><td><strong>{AGENT_LABELS[item.agent] ?? item.agent}</strong></td><td>{integer(item.runs)}</td><td>{integer(item.input_tokens)} / {integer(item.output_tokens)}</td><td>{integer(item.web_search_calls)} / {money(item.tool_cost)}</td><td>{money(item.estimated_cost)}</td></tr>)}
            </FinanceTable>
          </div>

          <FinanceTable title="Por modelo" count={data.by_model.length} headers={["Modelo", "Execuções", "Entrada / cache", "Saída / raciocínio", "Buscas / ferramentas", "Estimado", "Reconciliado"]}>
            {data.by_model.map((item) => <tr key={`${item.provider}:${item.model}`}><td><strong>{item.model}</strong><small>{providerName(item.provider)}</small></td><td>{integer(item.runs)}</td><td>{integer(item.input_tokens)} / {integer(item.cached_input_tokens)}</td><td>{integer(item.output_tokens)} / {integer(item.reasoning_tokens)}</td><td>{integer(item.web_search_calls)} / {money(item.tool_cost)}</td><td>{money(item.estimated_cost)}</td><td>{item.reconciled_cost === null ? <small>Não atribuído</small> : money(item.reconciled_cost)}</td></tr>)}
          </FinanceTable>

          <FinanceTable title="Por projeto" count={data.by_project.length} headers={["Projeto", "Execuções", `Estimado · ${days} dias`, "Estimado total", "Orçamento", "Saldo"]}>
            {data.by_project.map((item) => <tr key={item.project_id}><td><Link href={`/projects/${item.project_id}`}><strong>{item.name}</strong></Link><small>{item.status}</small></td><td>{integer(item.runs)}</td><td>{money(item.period_estimated_cost)}</td><td>{money(item.all_time_estimated_cost)}</td><td>{item.max_ai_budget === null ? "Sem limite" : money(item.max_ai_budget)}</td><td className={item.budget_exhausted ? "finance-negative" : ""}>{item.remaining_ai_budget === null ? "—" : money(item.remaining_ai_budget)}</td></tr>)}
          </FinanceTable>

          <section className="panel manual-cost-panel">
            <header><h2>Adicionar custo manual</h2><span>Para qualquer provedor</span></header>
            <form className="manual-cost-form" onSubmit={(event) => void addManualCost(event)}>
              <label>Provedor<input maxLength={100} required value={manual.provider} onChange={(event) => setManual({ ...manual, provider: event.target.value })} /></label>
              <label>Modelo<input maxLength={200} placeholder="Opcional" value={manual.model} onChange={(event) => setManual({ ...manual, model: event.target.value })} /></label>
              <label>Valor em USD<input min="0" required step="0.000001" type="number" value={manual.amount} onChange={(event) => setManual({ ...manual, amount: event.target.value })} /></label>
              <label>Data<input required type="date" value={manual.date} onChange={(event) => setManual({ ...manual, date: event.target.value })} /></label>
              <label>Item da fatura<input maxLength={300} placeholder="Opcional" value={manual.lineItem} onChange={(event) => setManual({ ...manual, lineItem: event.target.value })} /></label>
              <label>Observação<input maxLength={2000} placeholder="Opcional" value={manual.note} onChange={(event) => setManual({ ...manual, note: event.target.value })} /></label>
              <button className="button" disabled={saving} type="submit">{saving ? "Salvando…" : "Registrar custo"}</button>
            </form>
          </section>

          <div className="finance-two-column">
            <FinanceTable title="Lançamentos recentes" count={data.recent_cost_entries.length} headers={["Provedor", "Período", "Origem", "Item", "Valor"]}>
              {data.recent_cost_entries.map((item) => <tr key={item.id}><td><strong>{providerName(item.provider)}</strong><small>{item.model ?? "Modelo não informado"}</small></td><td>{new Date(item.period_start).toLocaleDateString("pt-BR")}</td><td>{item.source === "PROVIDER_API" ? "API" : "Manual"}</td><td>{item.line_item ?? "—"}</td><td>{money(item.amount)}</td></tr>)}
            </FinanceTable>
            <FinanceTable title="Histórico de sincronização" count={data.recent_syncs.length} headers={["Provedor", "Status", "Quando", "Itens", "Detalhe"]}>
              {data.recent_syncs.map((item) => <tr key={item.id}><td><strong>{providerName(item.provider)}</strong></td><td><span className={`connector-status ${item.status === "COMPLETED" ? "ready" : "failed"}`}>{item.status === "COMPLETED" ? "Concluída" : "Falhou"}</span></td><td>{dateTime(item.completed_at)}</td><td>{integer(item.entries_written)}</td><td>{item.error ?? "—"}</td></tr>)}
            </FinanceTable>
          </div>
        </>
      )}
    </div>
  );
}

function FinanceCard({ label, value, detail, tone = "normal" }: { label: string; value: string; detail: string; tone?: "normal" | "warning" }) {
  return <article className={`finance-card ${tone}`}><span>{label}</span><strong>{value}</strong><small>{detail}</small></article>;
}

function FinanceTable({ title, count, headers, children }: { title: string; count: number; headers: string[]; children: ReactNode }) {
  return <section className="panel finance-table"><header><h2>{title}</h2><span>{count} item(ns)</span></header><div className="panel-body table-wrap"><table><thead><tr>{headers.map((header) => <th key={header}>{header}</th>)}</tr></thead><tbody>{children}</tbody></table>{count === 0 && <p className="finance-empty">Nenhum dado no período.</p>}</div></section>;
}
