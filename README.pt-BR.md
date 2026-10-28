# Idea Evolution Engine (IEE)

> English version: [README.md](README.md)

Sistema de agentes de IA que **gera ideias de negócio** e **avalia a viabilidade** de cada uma
com evidências rastreáveis, custo controlado e decisão humana nos pontos críticos. A ideia sai
de um texto cru e chega a uma decisão auditável: aprovar, pivotar, testar, pesquisar mais ou
descartar.

## O que o projeto faz

O IEE tem três módulos que podem ser usados juntos ou separados.

### 1. Descoberta de oportunidades (gerar ideias)

Começa antes de existir uma ideia. A partir de um **perfil do fundador** (habilidades, capital,
horas por semana, meta de receita, mercados e modelos preferidos, exclusões e tolerância a
risco), uma **campanha** com orçamento próprio em dólares roda no máximo quatro etapas:

1. **Opportunity Scout** busca na web sinais atuais de dor de mercado.
2. **Idea Generator** cria de 3 a 5 candidatos.
3. O backend elimina duplicados e aplica **restrições obrigatórias** (tipo de cliente, entrega
   digital, automação mínima, tempo máximo de MVP, trabalho humano recorrente, aconselhamento
   regulado, marketplace de dois lados, recorrência de receita, canal de aquisição).
4. **Opportunity Researcher** pesquisa na web só os melhores candidatos.
5. Cada candidato pesquisado recebe um **Market Reality Score** determinístico (demanda,
   disposição a pagar, concorrentes pagos, aquisição, recorrência, margem e qualidade da
   evidência).
6. **Portfolio Judge** monta um ranking comparável dos finalistas.

O fundador pode **aprovar** ou **rejeitar** cada ideia com motivos. Essa memória alimenta as
próximas campanhas (só ideias novas, modo equilibrado ou melhorias das aprovadas). Cada
candidato também tem um formulário de **validação comercial** (visitas, leads, pré-vendas,
clientes pagantes, receita e gasto de aquisição). Uma ideia escolhida vira projeto com
**Transformar em projeto**, levando junto toda a pesquisa.

### 2. Avaliação de viabilidade (rodadas de agentes)

Cada projeto passa por rodadas limitadas (3 por padrão, teto de 5):

```text
Ideia -> Structurer -> Researcher -> Builder -> Critic
      -> Researcher -> Builder -> Judge -> Improver -> decisão
```

- O **Structurer** transforma o texto cru na versão V0 da ideia.
- O **Researcher** levanta hipóteses e evidências (com busca na web quando o provedor permite).
- O **Builder** melhora o conceito e cria uma nova versão imutável.
- O **Critic** registra críticas falsificáveis contra a versão atual.
- O segundo **Researcher** verifica as objeções do Critic e o **Builder** final aplica o que foi
  confirmado.
- O **Judge** dá notas por critério, e a aplicação calcula a pontuação final.
- O **Improver** transforma a avaliação num plano para a rodada seguinte.

Decisões `PIVOT`, `APPROVE` e `DISCARD` pausam em `AWAITING_CONFIRMATION` até uma pessoa aceitar,
continuar mesmo assim ou dar uma instrução de pivô. `TEST` cria um experimento e pausa até ele
terminar. Três melhorias seguidas de menos de 3 pontos marcam o projeto como estagnado.

Também é possível **conversar com o Judge** por texto ou voz (OpenAI Realtime). Cada mensagem
roda uma rodada completa e devolve a nova decisão.

### 3. Blueprint de desenvolvimento (opcional)

Depois de um conceito estruturado, um pipeline separado gera requisitos, alternativas de
arquitetura, revisão técnica e roadmap: **Product Architect**, até três **Solution Architects**,
**Technical Critic** e **Roadmap Planner**. Não gera código.

## Como a viabilidade é medida

O Judge avalia 12 critérios. O modelo dá a nota de cada um; o **cálculo é feito por código**,
não pelo modelo:

| Critério | Peso |
|---|---|
| Problema real | 15 |
| Viabilidade técnica | 15 |
| Intensidade do problema | 10 |
| Mercado | 10 |
| Diferenciação | 10 |
| Viabilidade econômica | 10 |
| Usuários identificáveis | 5 |
| Distribuição | 5 |
| Defensabilidade | 5 |
| Risco legal e regulatório | 5 |
| MVP testável | 5 |
| Escalabilidade | 5 |

A pontuação vai de 0 a 100 e vem com confiança, bloqueios, incógnitas e próximos passos.
Experimentos concluídos viram evidência com nota de qualidade de 0 a 5 e permitem uma
reavaliação focada do Judge.

## Princípios de engenharia

As regras completas estão em [PROJECT_RULES.md](PROJECT_RULES.md). As principais:

- Agentes nunca chamam APIs de IA diretamente; tudo passa por `LLMProvider`.
- Toda saída de agente tem schema tipado (Pydantic) e todo `AgentRun` é persistido.
- Versões da ideia são imutáveis e prompts são versionados.
- Não existem loops infinitos: há limite de rodadas e de custo.
- Fatos, suposições e inferências não se misturam, e toda evidência aponta para a fonte.
- Segredos nunca entram no repositório; credenciais ficam em variáveis de ambiente.

## Arquitetura

| Camada | Tecnologia |
|---|---|
| Backend | Python 3.11+, FastAPI, SQLAlchemy assíncrono, Alembic, SQLite |
| Frontend | Next.js, TypeScript |
| IA | Adaptadores para OpenAI, Anthropic, Gemini e serviços locais compatíveis com OpenAI, além de um provedor *mock* determinístico |
| Testes | pytest (backend), Playwright (ponta a ponta), GitHub Actions |
| Execução | Local ou Docker Compose |

Cada agente pode usar um provedor e um modelo diferentes. O detalhamento técnico de cada fase
está em [PROJECT_SPEC.md](PROJECT_SPEC.md).

## Estrutura do repositório

```text
.
├── backend/
│   ├── app/
│   │   ├── agents/          # Structurer, Builder, Critic, Researcher, Judge, Improver, descoberta e blueprint
│   │   ├── api/             # Rotas FastAPI
│   │   ├── billing/         # Conciliação de custos com provedores
│   │   ├── core/            # Configuração e logs
│   │   ├── database/        # Modelos SQLAlchemy e sessão
│   │   ├── domain/          # Enums do domínio
│   │   ├── llm/             # LLMProvider, roteador e adaptadores de provedores
│   │   ├── orchestration/   # Orquestrador, transições, estagnação e progresso
│   │   ├── schemas/         # Contratos Pydantic
│   │   ├── scoring/         # Motor de pontuação determinístico
│   │   └── services/        # Regras de negócio
│   ├── alembic/             # Migrações do banco (0001 a 0024)
│   ├── prompts/             # Prompts versionados de cada agente
│   ├── evals/               # Experimentos de especialização de prompts
│   ├── tools/               # Scripts de custo e comparação de modelos
│   └── tests/               # Testes do backend
├── frontend/
│   ├── app/                 # Páginas: início, nova ideia, projetos, descoberta, finanças, perfis, prompts
│   ├── components/          # Telas e painéis
│   ├── lib/                 # Cliente da API e tipos
│   └── e2e/                 # Teste de navegador com Playwright
├── .github/workflows/ci.yml # CI: backend, frontend e ponta a ponta
├── docker-compose.yml
├── .env.example             # Modelo de configuração, sem segredos
├── PROJECT_RULES.md         # Regras do projeto
├── PROJECT_SPEC.md          # Especificação técnica por fase
└── PROVIDERS.md             # Configuração de provedores, modelos e custos
```

## Como rodar

### Requisitos

- Python 3.11 ou mais novo
- Node.js 20.9 ou mais novo
- Docker com Compose (opcional)

### Configuração

Copie `.env.example` para `.env` na raiz. Sem alterações, tudo roda com o provedor **mock**, sem
custo e sem chave de API. Para usar modelos reais, preencha a chave do provedor e os preços por
milhão de tokens de cada agente (veja [PROVIDERS.md](PROVIDERS.md)). O `.env` nunca deve ser
enviado ao repositório.

### Backend

```bash
cd backend
python -m venv .venv
# ative o ambiente virtual
python -m pip install -e ".[test]"
alembic upgrade head
uvicorn app.main:app --reload
```

A documentação interativa da API fica em `http://127.0.0.1:8000/docs`.

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Abra `http://localhost:3000`. As principais telas são o painel de projetos, nova ideia,
detalhe do projeto, **Descobrir** (`/discover`), **Financeiro** (`/finance`), **Perfis** e
**Prompts**.

### Docker

```bash
docker compose up --build
```

Interface na porta 3000 e API na porta 8000. O banco fica no volume `iee_data`.

## Custos e segurança operacional

- Cada projeto e cada campanha têm **orçamento de IA** próprio. Quando o custo acumulado chega
  ao teto, nenhuma nova chamada começa.
- O painel **Financeiro** separa o custo **estimado** (calculado na hora, por token e por busca
  na web) do custo **conciliado** (vindo da API de cobrança do provedor ou lançado à mão).
- Execuções podem ser **canceladas** com segurança; a requisição em andamento é interrompida e a
  rodada é fechada.
- `GET /system/config` mostra a configuração sem expor nenhuma credencial.
- Relatórios em JSON ou Markdown e backup/restauração de projetos estão disponíveis pela API e
  pela interface.

## Testes

```bash
cd backend && pytest
cd frontend && npm run typecheck && npm run build && npm run test:e2e
```

Os testes do backend usam SQLite em memória e nunca chamam APIs externas.

## Estado atual

- Fases 1 a 10 concluídas, mais endurecimento operacional, Improver, conversa com o Judge por
  texto e voz, cancelamento entre processos e triagem de modelos por custo e qualidade (veja a
  seção *Roadmap* do [README.md](README.md)).
- Módulo de descoberta com memória de feedback, validação comercial e passagem para projeto
  (migração 0024).
- Os 138 testes do backend passam. Eles foram atualizados para três mudanças de comportamento
  recentes: o Builder não devolve mais `raw_idea` (o servidor preserva a ideia original), cada
  chamada do Researcher foca uma única hipótese aberta e a migração 0024 criou a tabela
  `discovery_handoffs`.

## Documentação

| Arquivo | Conteúdo |
|---|---|
| [README.md](README.md) | Guia completo em inglês: API, variáveis de ambiente, fluxo e roadmap |
| [PROJECT_SPEC.md](PROJECT_SPEC.md) | Especificação técnica e decisões de arquitetura por fase |
| [PROVIDERS.md](PROVIDERS.md) | Provedores, modelos por agente, preços e conciliação de custos |
| [PROJECT_RULES.md](PROJECT_RULES.md) | Regras de engenharia do projeto |
| [backend/evals/README.md](backend/evals/README.md) | Experimentos de especialização de prompts |
