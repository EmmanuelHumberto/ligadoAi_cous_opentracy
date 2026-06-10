# OpenTracy + Cous — Arquitetura para Especialização Contínua

> **Versão 2.0** — 2026-06-09  
> **Status:** documento de arquitetura e direção estratégica  
> **Escopo:** define como OpenTracy (motor cognitivo) e Cous (interface operacional) se complementam para produzir um assistente que aprende com a operação real.

---

## Índice

1. [Diagnóstico: o estado atual](#1-diagnóstico-o-estado-atual)
2. [Princípios arquiteturais](#2-princípios-arquiteturais)
3. [Visão estratégica](#3-visão-estratégica)
4. [O que o OpenTracy entrega (motor cognitivo)](#4-o-que-o-opentracy-entrega-motor-cognitivo)
5. [O que o Cous entrega (interface operacional)](#5-o-que-o-cous-entrega-interface-operacional)
6. [Análise crítica: o que o Cous não explora do framework](#6-análise-crítica-o-que-o-cous-não-explora-do-framework)
7. [Persistência: arquivos vs banco de dados](#7-persistência-arquivos-vs-banco-de-dados)
8. [Arquitetura alvo — três camadas](#8-arquitetura-alvo--três-camadas)
9. [Fontes de conhecimento operacional](#9-fontes-de-conhecimento-operacional)
10. [Fluxo conceitual](#10-fluxo-conceitual)
11. [Decisão arquitetural: memory dupla](#11-decisão-arquitetural-memory-dupla)
12. [Trade-offs arquiteturais](#12-trade-offs-arquiteturais)
13. [Dependências entre fases — paralelismo](#13-dependências-entre-fases--paralelismo)
14. [Requisitos não-funcionais](#14-requisitos-não-funcionais)
15. [Plano de migração revisado](#15-plano-de-migração-revisado)
16. [Contratos de interface](#16-contratos-de-interface)
17. [Novos componentes no Cous](#17-novos-componentes-no-cous)
18. [Checklist de implementação](#18-checklist-de-implementação)
19. [Referência: estrutura de diretórios](#19-referência-estrutura-de-diretórios)

---

## 1. Diagnóstico: o estado atual

### 1.1 Como a UI web consome o OpenTracy

```
┌───────────┐   POST /v1/webhook    ┌───────────┐   POST /run    ┌──────────────┐
│  UI web   │ ────────────────────→ │ Backend   │ ─────────────→ │  Runtime     │
│ (React)   │  {request, history}   │ (Hono/TS) │               │  (Python)    │
│           │                       │           │               │              │
│           │                       │           │               │ agent.yaml → │
│           │                       │           │               │  retrieve    │
│           │                       │           │               │  rerank      │
│           │                       │           │               │  route       │
│           │                       │           │               │  generate    │
│           │                       │           │               │              │
│           │ ←── response ──────── │ ←─────── │               │ system.md    │
│           │  {response,           │          │               │ FAISS index  │
│           │   trace_id,           │          │               │ traces/      │
│           │   duration_ms,        │          │               │              │
│           │   stages[]}           │          │               │              │
└───────────┘                       └───────────┘               └──────────────┘
```

A UI web:
- Envia `{request, history}`
- Recebe `{response, trace_id, duration_ms, stages[]}`
- `stages[]` mostra o pipeline: quantos docs entraram, qual modelo foi usado, latência
- **Não persiste conversas** — estado vive na memória do navegador

### 1.2 Como o Cous consome o OpenTracy hoje

```
┌───────────┐   POST /v1/api/{agent}/chat   ┌───────────┐
│  Cous     │ ─────────────────────────────→ │ Backend   │
│(terminal) │  {request, history, channel}   │ (Hono/TS) │
│           │                                │           │
│           │  request já contém:            │           │
│           │  • texto do operador           │           │
│           │  • contexto de medições local  │           │
│           │    injetado manualmente        │           │
│           │                                │           │
│           │ ←── {response, trace_id} ───── │           │
└───────────┘                                └───────────┘
```

O Cous:
- Envia `{request, history, channel}`
- Injeta contexto de medições **manualmente** no `request` (sem passar pelo pipeline retrieve)
- Recebe apenas `{response, trace_id}` — ignora `stages[]`
- **Não envia system prompt** — o agente responde sem especialização
- **Persiste conversas** em JSONL local (ponto forte)

### 1.3 O gap fundamental

O Cous trata o OpenTracy como **proxy HTTP burro** — envia texto, recebe texto. Ignora completamente:
- Pipeline retrieve (RAG)
- System prompt treinável
- Roteamento inteligente
- Traces estruturados
- Harness de evolução

Enquanto isso, faz coisas que o framework não faz:
- Captura serial de sensores (TMA_DATA)
- Persistência local de conversas e medições
- Injeção manual de contexto de medições
- Resiliência com fallbacks locais

---

## 2. Princípios arquiteturais

Estes princípios devem orientar qualquer decisão de design no ecossistema Cous + OpenTracy:

**Princípio 1 — Não duplicar capacidades do OpenTracy.**  
Se o OpenTracy já provê RAG, routing, memory, traces, evals ou harness, o Cous não deve reimplementá-los. Deve integrar-se a eles.

**Princípio 2 — O Cous amplia o contexto, não substitui o pipeline.**  
O Cous coleta dados especializados (medições, feedback, arquivos técnicos) e os entrega ao OpenTracy. Quem decide o que é relevante para a resposta é o pipeline retrieve, não o Cous.

**Princípio 3 — Conhecimento operacional é tão importante quanto conhecimento documental.**  
Datasheets e manuais são a base. Mas diagnósticos reais, casos resolvidos e feedback humano são o que transforma um assistente genérico em um especialista.

**Princípio 4 — Todo dado relevante deve poder alimentar traces e evolução futura.**  
Se uma interação gerou aprendizado, ela precisa ser registrada de forma estruturada para que evals e harness possam consumi-la.

---

## 3. Visão estratégica

### 3.1 Objetivo

O objetivo do projeto não é apenas fornecer uma interface de conversação para o OpenTracy.

O objetivo é criar uma **camada operacional especializada** capaz de **capturar, estruturar e preservar conhecimento técnico** gerado durante o uso real do sistema, e **alimentar o OpenTracy** com dados de alta qualidade para que seus mecanismos de evolução produzam um agente progressivamente mais especializado.

### 3.2 Separação de responsabilidades

```
OpenTracy = Motor Cognitivo          Cous = Interface Operacional Especializada
─────────────────────────────────    ─────────────────────────────────────────
RAG                                  Persistência operacional
Routing                              Captura de contexto (serial, sensores)
Memory                               Integração com ferramentas locais
Traces                               Integração com fontes de dados técnicas
Evals                                Registro de feedback humano
Harness                              Preservação de conhecimento operacional
Evolução do agente                   Indexação de medições como documentos
```

### 3.3 A inversão necessária

```
HOJE:                              ALVO:

Cous decide O QUE enviar           Cous coleta dados especializados
  ↓                                  ↓
Cous monta contexto manualmente    Cous entrega ao OpenTracy
  ↓                                  ↓
OpenTracy é um proxy burro         OpenTracy processa com pipeline
  ↓                                  ↓
Resposta sem RAG/especialização    Resposta com RAG + routing + evolução
```

O Cous **não deve decidir** o que é relevante — ele deve **coletar e entregar**. Quem decide relevância é o pipeline retrieve do OpenTracy.

---

## 4. O que o OpenTracy entrega (motor cognitivo)

### 4.1 Pipeline do agente — 4 estágios

Definido em `agent/agent.yaml`. Esta é a **superfície treinável** — o harness pode modificar qualquer knob.

| Estágio | Técnica | Função |
|---------|---------|--------|
| **retrieve** | RAG densa, 30 chunks, `all-MiniLM-L6-v2` | Busca documentos relevantes na base FAISS |
| **rerank** | Cross-encoder `ms-marco-MiniLM` | Reordena por relevância semântica |
| **route** | `small_first`, threshold 0.7 | Decide `deepseek-chat` vs `deepseek-reasoner` |
| **generate** | Prompt strategies, temp 0.3 | Usa `system.md` como prompt base |

**Cross-cutting — memory:** janela 20, sumarização após 50 mensagens.

### 4.2 System prompt treinável

`agent/prompts/system.md` — define a identidade, domínio e restrições do agente. É **mutável pelo harness**.

### 4.3 Harness — loop de auto-melhoria

```
traces → proposer → critics → evals → approver → executor → agent/ (patch)
```

Baseado no algoritmo AHE (Lin et al., arxiv 2604.25850). Opera sobre traces reais, propõe edições no agente, avalia com goldens, aplica patches versionados com rollback.

### 4.4 Infraestrutura de evals

- **goldens/** — perguntas + respostas esperadas
- **rubrics/** — critérios de avaliação
- **runners/** — executores de teste
- **suites/** — conjuntos por domínio
- **reports/** — atribuição por trace

### 4.5 Persistência no OpenTracy

| Dado | Backend padrão | Backend escalável |
|------|---------------|-------------------|
| Traces | `traces/` (arquivos) | ClickHouse |
| Medições | Em memória | PostgreSQL |
| Knowledge | FAISS (`corpora/indexed/`) | FAISS |
| Conversas | **Não persiste** | — |

---

## 5. O que o Cous entrega (interface operacional)

### 5.1 Funcionalidades atuais

| Funcionalidade | Detalhe |
|---------------|---------|
| **Chat** | Envia texto + histórico para o agente |
| **Contexto de medições** | Detecta termos de domínio e injeta resumo local no `request` |
| **Memory local** | Janela 10, sumarização por tamanho (16K chars) + fallback local. **A partir da Fase A, o runtime é canônico para memória ativa (seção 11); o Cous mantém histórico apenas para offline, exportação e fallback.** |
| **Captura serial** | TMA_DATA via `termios` — hall, power, course, vibration |
| **Persistência local** | Conversas JSONL, medições JSON, índice de conversas |
| **Sincronização** | Envia medições para o runtime |
| **Diagnóstico/Laudo** | Remoto com fallback local |
| **Comandos knowledge** | `/indexar`, `/buscar`, `/validar`, `/remover` |
| **Resiliência** | Escrita atômica, tolerância a JSONL corrompido, fallbacks |

### 5.2 Pontos fortes exclusivos

**Injeção de contexto local de medições.** Detecta termos como "vibração", "hall", "rpm", "máquina" na pergunta e anexa automaticamente um resumo das medições mais relevantes. O OpenTracy não tem isso nativamente.

**Persistência local robusta.** JSONL + JSON com escrita atômica (`write-to-temp + fsync + os.replace`), índice de conversas para listagem rápida, sobrevive a reinicializações. A UI web não persiste conversas.

**Resiliência operacional.** Fallback local para resumo, diagnóstico e laudo quando o runtime está offline.

---

## 6. Análise crítica: o que o Cous não explora do framework

Esta seção identifica capacidades do OpenTracy que o Cous **atualmente não controla ou não explora explicitamente**. Algumas dessas funcionalidades podem estar sendo executadas pelo runtime sem participação do Cous — a análise foca no que o cliente conscientemente utiliza.

| Ferramenta do OpenTracy | Situação no Cous | Oportunidade |
|-------------------------|------------------|--------------|
| **Pipeline retrieve (RAG)** | Não explorado explicitamente | O Cous não injeta resultados da base de conhecimento no contexto do chat |
| **System prompt (`system.md`)** | Não enviado pelo cliente | O agente pode responder sem a especialização de domínio definida no prompt |
| **Pipeline route** | Não controlado pelo Cous | Sem visibilidade ou influência sobre a escolha small/big model |
| **Traces estruturados** | Apenas logs JSONL locais | Sem captura de `stages[]` (docs_in/out, modelo, latência por etapa) |
| **Harness** | Não integrado | O agente não recebe melhorias automáticas baseadas em uso |
| **Evals** | Não implementado | Sem medição de qualidade das respostas |
| **Experiments** | Não implementado | Sem capacidade de testar variações do agente |
| **Knowledge no chat** | Isolado | Resultados de `/buscar` são exibidos no terminal mas não alimentam a conversa |

---

## 7. Persistência: arquivos vs banco de dados

### 7.1 O que o Cous usa hoje

JSONL + JSON em arquivos (`.cous-data/`). Isso foi um **acerto para o escopo atual**:

- Zero dependência de infraestrutura
- Portabilidade total (copia a pasta)
- Inspeção direta (`cat` + `jq`)
- Backup trivial (`cp -r`)

### 7.2 O papel futuro do PostgreSQL

O PostgreSQL **não** deve ser tratado apenas como storage de histórico. Sua função principal é atuar como **memória operacional estruturada**, capaz de responder consultas como:

- "Quais diagnósticos foram feitos para máquinas Phantom com vibração acima de 800mg?"
- "Qual foi a evolução do consumo elétrico da máquina serial X nos últimos 30 dias?"
- "Quantas sessões de reparo resultaram em troca de bucha?"

Entidades relevantes:

```
Conversas, Sessões, Medições, Diagnósticos,
Feedbacks, Relatórios, Casos resolvidos, Eventos
```

A migração de JSONL → PostgreSQL deve ocorrer quando o volume de dados justificar queries relacionais. Até lá, JSONL/JSON atende.

### 7.3 Critérios para migração

| Critério | JSONL/JSON (hoje) | PostgreSQL (futuro) |
|----------|-------------------|---------------------|
| Volume | ✅ Até ~1000 sessões | ✅ Milhões |
| Concorrência | ❌ Single-process | ✅ Multi-cliente |
| Queries complexas | ❌ Sem joins/agregação | ✅ SQL completo |
| Portabilidade | ✅ Copiar pasta | ❌ pg_dump/pg_restore |
| Dependência | ✅ Zero | ❌ Serviço rodando |
| Setup | ✅ Imediato | ❌ Schema + migração |

---

## 8. Arquitetura alvo — três camadas

```
┌─────────────────────────────────────────────────────────────┐
│ Camada 1 — Aquisição Operacional (Cous)                      │
│                                                              │
│ • Captura serial TMA_DATA (hall, power, course, vibration)  │
│ • Persistência local → PostgreSQL (memória operacional)      │
│ • Terminal interativo                                        │
│ • Sincronização com runtime                                  │
│ • Indexação de medições como documentos na base FAISS        │
│ • Registro de feedback humano                                │
│ • Integração com fontes de dados técnicas                    │
│                                                              │
│ Interface → Camada 2:                                        │
│   POST /chat {request, history, system}                     │
│   POST /knowledge/index {documento}                          │
│   POST /measurements/sessions {header, snapshots}            │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│ Camada 2 — Inteligência (OpenTracy runtime)                  │
│                                                              │
│ • Pipeline retrieve → rerank → route → generate              │
│ • System prompt (system.md) — superfície treinável           │
│ • Memory (janela 20, sumarização 50)                         │
│ • Traces (por canal, com stages: docs_in/out, modelo, ms)   │
│                                                              │
│ Interface → Camada 3:                                        │
│   traces/ → alimenta o harness                              │
│   agent/ → superfície mutável                                │
│   evals/ → avaliação de qualidade                            │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│ Camada 3 — Evolução (OpenTracy harness)                      │
│                                                              │
│ • Proposer: sugere melhorias baseado em traces reais         │
│ • Critics: avalia pontos fortes e fracos                     │
│ • Evals: testa com goldens + detecção de regressão           │
│ • Approver: KEEP / IMPROVE / ROLLBACK_AND_PIVOT              │
│ • Executor: aplica patches versionados em agent/             │
│                                                              │
│ Ciclo: traces → proposta → avaliação → patch → novos traces  │
└─────────────────────────────────────────────────────────────┘
```

---

## 9. Fontes de conhecimento operacional

O sistema deve ser capaz de registrar e estruturar informações de múltiplas fontes:

### 9.1 Conversas

```
Pergunta → Resposta → Correções → Feedback → Conclusão
```

Cada interação relevante pode gerar: aprendizado operacional, casos de referência, conhecimento validado.

### 9.2 Diagnósticos

```
Problema observado → Hipótese gerada → Diagnóstico final → Resultado obtido
```

Exemplos de diagnóstico, material para avaliação, material para evolução futura.

### 9.3 Medições

```
Vibração, Temperatura, Corrente, Pressão, Dados de sensores
```

### 9.4 Coleta serial

```
Analisadores, Instrumentação, Dispositivos embarcados, Equipamentos industriais
```

### 9.5 Arquivos técnicos

```
Laudos, Relatórios, Planilhas, PDFs, Documentação
```

### 9.6 Conhecimento validado

```
Boas práticas, Procedimentos, Soluções recorrentes, Casos resolvidos
```

### 9.7 Feedback humano estruturado

Feedback humano é o tipo de dado operacional com maior potencial de impacto sobre a qualidade do agente. Diferente de métricas automáticas, ele carrega julgamento técnico que nenhum sensor pode produzir.

Formatos de feedback que o Cous deve capturar:

| Tipo | Exemplo | Valor para evolução |
|------|---------|---------------------|
| **Resposta correta** | Operador confirma que o diagnóstico está certo | Goldens para evals |
| **Resposta incorreta** | Operador corrige: "não era a bucha, era o capacitor" | Casos de edge para re-treino |
| **Diagnóstico confirmado** | Técnico aplica a solução sugerida e resolve | Validação de conhecimento |
| **Diagnóstico descartado** | Técnico reporta que a hipótese não se confirmou | Refinamento de heurísticas |
| **Solução aplicada** | "Troquei a fonte e resolveu" | Mapeamento problema → solução |
| **Resultado obtido** | "Vibração caiu de 900mg para 300mg após ajuste" | Evidência quantitativa |

Cada feedback deve ser registrado de forma estruturada (tipo, sessão, timestamp, conteúdo) para que:
- **Evals** possam usá-lo como golden de referência
- **Harness** possa identificar padrões de erro e propor correções no agente
- **Traces** possam correlacionar feedback com o contexto que o gerou

---

## 10. Fluxo conceitual

```
                        Operação Real
                             │
                             ▼
                     Captura de Contexto
                    (Cous: serial, sensores,
                     comandos, feedback)
                             │
                             ▼
                   Persistência Estruturada
                  (JSONL/JSON local hoje; PostgreSQL
                   como memória operacional na Fase F)
                             │
                             ▼
               Base de Conhecimento Operacional
              (FAISS: documentos indexados, sumários
               de medições, conhecimento validado)
                             │
                             ▼
                    Contexto para o Agente
               (Pipeline retrieve → rerank → generate)
                             │
                             ▼
                          Traces
              (por canal, com stages, latência, scores)
                             │
                             ▼
                          Evals
              (goldens, detecção de regressão, rubricas)
                             │
                             ▼
                         Harness
              (propõe, critica, avalia, aplica patches)
                             │
                             ▼
                Especialização Progressiva
```

### 10.1 Resultado esperado

Ao longo do tempo, o sistema evolui de:

```
Assistente que consulta documentos
```

para:

```
Assistente especializado que acumula experiência operacional,
utiliza conhecimento validado e melhora continuamente a partir
dos dados gerados durante sua utilização.
```

---

## 11. Decisão arquitetural: memory dupla

**Problema:** O Cous mantém janela de 10 mensagens + sumarização por 16K chars. O runtime tem janela de 20 + sumarização após 50. Enviando `history` em cada requisição, o modelo recebe contexto duplicado.

**Decisão:** O runtime é a fonte canônica de memória durante sessões ativas. O Cous mantém histórico local apenas para persistência offline, exportação e fallback. `history` completo é enviado na primeira mensagem da sessão; nas mensagens seguintes, envia-se apenas o resumo comprimido (se existir) para reconectar o runtime ao estado da sessão sem reenviar o histórico bruto.

**Edge case — runtime reinicia entre mensagens:** O runtime não persiste sessões entre reinicializações. Se o servidor cair entre duas mensagens, a segunda chega com `history=[]` e o runtime perde o contexto. O `history_for_model()` mitiga isso: se há resumo salvo, ele é incluído como `role: "system"` em todas as requisições, não apenas na primeira. Isso garante que o contexto comprimido sobreviva a reinicializações do runtime.

```python
def _send_chat(text: str, ctx: CommandContext) -> None:
    ctx.session.add("user", text)

    # Runtime é canônico para memória ativa.
    # Envia histórico completo apenas na primeira mensagem.
    # Envia resumo comprimido em toda requisição (sobrevive a restart do runtime).
    is_first_message = len(ctx.session.history) <= 1
    history = ctx.session.history_for_model(
        ctx.config.memory.max_history
    ) if (is_first_message or ctx.session.summary) else []

    result = ctx.opentracy.chat(
        text, history=history, session_id=ctx.session.session_id,
        channel="terminal",
    )


---

## 12. Raciocínio de trade-offs arquiteturais

### Memória dupla e não única

**Decisão:** O runtime mantém a memória canônica durante sessões ativas; o Cous persiste histórico local como fallback offline.

**Alternativa rejeitada:** Memória única no runtime, com o Cous sendo stateless (como a UI web). Rejeitada porque o terminal opera em ambientes com conectividade intermitente — um técnico em bancada não pode perder o contexto da conversa se o Wi-Fi cair.

**Custo:** Complexidade de sincronização entre as duas memórias. Mitigado pelo fato de que o runtime é sempre a fonte da verdade quando online — o Cous nunca "mergeia" históricos, apenas reenvia.

### PostgreSQL e não SQLite

**Decisão:** PostgreSQL como destino de migração quando o volume de dados justificar queries multi-entidade.

**Alternativa considerada:** SQLite — portátil, zero infraestrutura, mesma filosofia do JSONL atual. Rejeitada como destino de migração, não como ferramenta. SQLite é excelente para single-process; o trigger da migração é justamente o momento em que o sistema passa a ter múltiplos consumidores (dashboard web, múltiplos terminais). Nesse ponto, PostgreSQL oferece concorrência real e queries analíticas que SQLite não comporta.

**Ressalva:** Se o trigger nunca disparar (uso permanece single-terminal), a migração nunca ocorre — e JSONL continua sendo a escolha certa. A arquitetura não força PostgreSQL; ela o posiciona como resposta a uma condição objetiva.

### Promover trace existente e não criar golden direto

**Decisão:** Feedback vira golden via `promote-from-trace`, não via criação direta.

**Alternativa rejeitada:** `POST /evals/goldens` com o feedback diretamente. Rejeitada porque o harness já consome traces como fonte primária — promover um trace preserva a cadeia causal completa (pergunta → pipeline → resposta → feedback). Criar um golden direto perderia o contexto de retrieval (quais documentos estavam presentes, qual modelo foi usado, qual a latência), informação essencial para o harness diagnosticar por que uma resposta foi boa ou ruim.

**Custo:** `FeedbackRecord` precisa carregar `trace_id` desde o momento da coleta (Fase B2), adicionando um campo à estrutura. Custo aceito pelo ganho de rastreabilidade.

---

## 13. Dependências entre fases — o que paraleliza

A ordem linear A → B → C → D → E → F → G esconde que metade do trabalho é paralelizável:

```
Fundação (componentes novos)
    │
    ├── Fase A (system prompt) ─────────────┐
    ├── Fase B (indexação de medições) ─────┤
    ├── Fase B2 (feedback) ─────────────────┤ paralelizável
    └── Fase D (stages + TraceEmitter) ─────┘
                    │
                    ▼
              Fase C (remover injeção manual)
              └── Gate: eval A/B
                    │
                    ▼
              Fase E (sync feedback → goldens)
                    │
                    ▼
              Fase F (PostgreSQL)
                    │
                    ▼
              Fase G (harness)
```

**Sequência crítica (não paralelizável):** Fundação → Fase B → Fase C → Fase E → Fase G. A Fase C depende de B (medições indexadas para o gate A/B). A Fase E depende de B2 (feedback coletado). A Fase G depende de D (traces emitidos) e E (goldens promovidos).

**Paralelizável:** Fases A, B2 e D podem ser implementadas simultaneamente por times diferentes ou na mesma sprint, pois não compartilham estado.

---

## 14. Requisitos não-funcionais

### Latência

| Operação | Alvo | Degradação aceitável |
|----------|------|---------------------|
| Pipeline retrieve → generate | < 3000ms | < 5000ms (operador espera) |
| Captura serial | Tempo real (30-120s) | Timeout com salvamento parcial |
| Polling de job (knowledge) | < 120s (6 chamadas com backoff) | Timeout local; job continua no runtime |
| Feedback (local) | < 10ms (append JSONL) | Bloqueia em OSError (logado, não propagado) |

### Disponibilidade

| Cenário | Comportamento |
|---------|---------------|
| Runtime offline | Chat via mock; medições acumulam localmente; sync quando reconectar |
| FAISS offline | Chat funciona sem knowledge (fallback para conhecimento pré-treinado + medições locais) |
| Harness offline | Chat funciona normalmente; agente não evolui |
| Disco cheio | Logger captura OSError; chat e medições continuam operando |
| Token expirado | Erro 401 exibido; operador reexecuta bootstrap |

### Volume

| Artefato | Crescimento estimado | Limite antes de warning |
|----------|---------------------|------------------------|
| Conversas JSONL | ~50/mês/técnico, ~1KB cada | 1000 conversas |
| Medições JSON | ~100/dia/técnico, ~300 snapshots cada, ~100KB por sessão | 10K medições |
| Logs de eventos | ~500 eventos/dia, ~200B cada | Rotação em 10MB, 3 backups |
| Goldens | ~10/mês (após feedback ativo) | Sem limite (dataset versionado) |

**Critério para migração PostgreSQL:** > 10K medições OU > 2 terminais simultâneos OU dashboard web ativo. Até lá, JSONL/JSON atende.

### Tolerância a falhas

```
Falha no FAISS      → chat funciona sem knowledge
Falha no harness    → chat funciona normalmente
Falha no PostgreSQL → medições continuam em JSON local
Falha no runtime    → Cous opera offline com mocks
Falha no disco      → logger captura OSError, não derruba terminal
Falha no token      → erro 401, operador notificado
```

**Falha catastrófica (evitada por design):** corrupção de goldens. Se um feedback incorreto for promovido a golden, o harness pode aprender conhecimento falso. Por isso a Fase E permanece com supervisão humana e rollback versionado.

---

## 15. Plano de migração revisado

### 15.1 Fases com gates de validação

| Fase | O que fazer | Gate de entrada | Risco |
|------|-------------|----------------|-------|
| **A** | Enviar `system` no payload; `SystemPromptCache` com TTL + snapshot local | Nenhum | Baixo |
| **B** | Indexar sumários de medições após `/capturar` e `/sincronizar` | Nenhum | Baixo |
| **B2** | Implementar `FeedbackStore` + comandos `/confirmar`, `/corrigir`, `/solucao` | Fundação (novos componentes) | Baixo |
| **D** | Capturar `stages[]` da resposta; `TraceEmitter` para traces compatíveis | Nenhum | Baixo |
| **E** | Sincronizar FeedbackStore como goldens via `POST /evals/goldens` | Fases B2 + D | Médio |
| **C** | Remover injeção manual de contexto | **Gate:** eval A/B em 10+ queries mostra retrieve ≥ injeção manual | Alto |
| **F** | Migrar para PostgreSQL | Trigger: multi-terminal OU dashboard web | Alto |
| **G** | Conectar harness via traces do canal "terminal" | Fases D + E | Alto |

### 15.2 Por que a Fase C requer validação

Remover a injeção manual de contexto de medições pressupõe que o pipeline retrieve do OpenTracy recuperará os sumários indexados com qualidade equivalente. Isso depende de:

1. Threshold e chunk size do retrieve adequados para vocabulário técnico (hall, TMA_DATA, curso nominal)
2. O embedder `all-MiniLM-L6-v2` representar bem o domínio de máquinas de tatuagem
3. Os sumários markdown gerados por `build_markdown_report()` rankearem bem para queries como "qual a vibração da FK Irons?"

**Gate obrigatório:** comparar respostas com injeção manual vs via pipeline retrieve para 10-15 queries de domínio reais. Só migrar quando retrieve igualar ou superar a injeção manual.

### 15.3 Mudanças imediatas no código

#### `cous/clients/opentracy.py` — system prompt

```python
def chat(self, request, *, history=None, channel="terminal", system=None):
    payload = {"request": request, "channel": channel}
    if history:
        payload["history"] = history
    if system:
        payload["system"] = system
    return self._auth.post(
        f"{self._backend_url}/v1/api/{self._config.agent_id}/chat",
        payload,
    )
```

#### `cous/measurements/analysis.py` — indexar medições

```python
def index_measurement_session(session, knowledge_client):
    """Gera documento markdown com metadata normalizada e indexa no OpenTracy."""
    markdown = build_markdown_report(session)
    metadata = {
        "source": "measurement",
        "session_id": session["id"],
        "machine": f"{session.get('header',{}).get('fabricante','')} {session.get('header',{}).get('modelo','')}",
        "serial": session.get("header", {}).get("numero_serie", ""),
        "tipo_coleta": session.get("header", {}).get("tipo_coleta", ""),
    }
    doc_path = write_temp_markdown(session["id"], markdown)
    knowledge_client.index(doc_path, metadata=metadata)
```

### 15.4 O que NÃO fazer

- **Não reinventar RAG.** O OpenTracy já tem retrieve, rerank, embeddings, FAISS.
- **Não duplicar o harness.** Basta gerar traces compatíveis.
- **Não ignorar o `system.md`.** É a superfície treinável.
- **Não tratar PostgreSQL só como storage.** É memória operacional estruturada.
- **Não remover injeção manual sem validação A/B.** É a funcionalidade com maior risco de regressão.

### 15.5 Análise prática: o que cada fase exige de cada repositório

> **Verificação realizada em 2026-06-09** contra o código-fonte real do runtime (`server.py`) e backend (`handler.ts`). As respostas abaixo são factuais, não especulativas.

#### Incerteza 1: o backend repassa `system` ao runtime?

**Resposta:** NÃO. O `RunRequest` do runtime (`server.py:71`) não tem campo `system`:

```python
class RunRequest(BaseModel):
    request: str
    history: Optional[list[HistoryMessage]] = None
    session_id: Optional[str] = None
    channel: Optional[str] = "web"
    ...
```

Não há campo `system` no modelo. Seria necessário adicioná-lo.

**Porém:** `HistoryMessage` aceita `role: "system"`, então o Cous poderia enviar o system prompt como uma mensagem de histórico com role `system` sem modificar o runtime. Isso é um workaround, não a solução ideal.

#### Incerteza 2: `GET /agent/{agent_id}/system` existe?

**Resposta:** NÃO como rota dedicada. Existe `GET /agent/config` que retorna `AgentConfigView`:

```python
class AgentConfigView(BaseModel):
    version: str
    description: Optional[str] = None
    system_prompt: AgentPromptView   # content, path, version
    models: AgentModelsView
    integrations: list[IntegrationStatus]
```

O `SystemPromptCache` deve chamar `GET /agent/config` e extrair `system_prompt.content`, em vez de uma rota `/agent/{id}/system` dedicada.

#### Incerteza 3: `POST /evals/goldens` existe?

**Resposta:** NÃO como criação direta. O ecossistema de goldens funciona por **promoção de traces**, não por upload:

| Endpoint | O que faz |
|----------|-----------|
| `POST /evals/goldens/promote-from-trace/:trace_id` | Promove um trace existente a golden |
| `PUT /datasets/goldens` | Versiona e atualiza metadados do dataset |
| `GET /datasets/goldens/export` | Exporta goldens como NDJSON |

**Consequência para a Fase E:** O fluxo primário é `promote-from-trace` — o `FeedbackRecord` já inclui `trace_id` desde a Fase B2, então o Cous só precisa chamar `POST /evals/goldens/promote-from-trace/{trace_id}` para cada registro confirmado. O fluxo alternativo (`PUT /datasets/goldens` com NDJSON) só é necessário se o `promote-from-trace` não aceitar o formato de trace emitido pelo `TraceEmitter`.

#### Incerteza 4: formato real de um trace

**Resposta:** Confirmado. `StageOutcome` no runtime:

```python
class StageOutcome(BaseModel):
    stage: str           # "retrieve", "rerank", "route", "generate"
    technique: str
    variant: str
    duration_ms: int
    docs_in: int
    docs_out: int
    routing_model: Optional[str] = None
    error: Optional[str] = None
```

O `TraceEmitter` do Cous deve emitir exatamente este formato para ser compatível com o harness.

#### Fases que são trabalho quase exclusivo do Cous

**Fase A — System prompt no chat.** ⚠️ **Achado:** o `RunRequest` não tem campo `system`. Workaround imediato: enviar o system prompt como `HistoryMessage(role="system")` no array `history`. Isso funciona sem modificar o runtime. O `SystemPromptCache` deve chamar `GET /agent/config` (não `/agent/{id}/system`) e extrair `system_prompt.content`.

**Fase B — Indexar medições.** O Cous chama `POST /knowledge/index` que já existe no runtime. Zero trabalho no OpenTracy.

**Fase B2 — FeedbackStore + comandos.** Tudo local no Cous: `FeedbackStore` em JSONL, comandos `/confirmar`, `/corrigir`, `/solucao`. Zero trabalho no OpenTracy — o feedback fica em JSONL local até a Fase E.

**Fase D — Capturar stages[] e TraceEmitter.** O runtime já gera `stages[]` e já devolve na resposta — a UI web já recebe esse campo. O Cous simplesmente não estava lendo. Zero trabalho no OpenTracy.

#### Fase que é só código do Cous, sem mudança no OpenTracy

**Fase C — Remover injeção manual.** É puramente remoção de código do Cous. O pipeline retrieve já existe e já funciona. O único trabalho é o gate operacional de validação — rodar o teste A/B em 10+ queries — que não é código de nenhum dos lados.

#### Fases que exigem trabalho real no OpenTracy

**Fase E — Sincronizar feedback como goldens.** O endpoint `POST /evals/goldens` não existe hoje. Alguém precisa criá-lo no runtime Python. Sem ele, o `export_as_goldens()` do Cous gera o arquivo localmente mas não tem para onde enviar.

**Fase F — PostgreSQL.** Trabalho no runtime: schema, migrations, troca do backend em memória por PostgreSQL para medições. O Cous só ajusta a URL de sincronização.

**Fase G — Harness via traces do canal "terminal".** O harness já existe, mas precisa ser configurado para consumir traces do canal `"terminal"` além do `"web"`. Pode ser uma linha de config ou exigir lógica de filtragem no proposer — depende de como está implementado.

#### Resumo por fase

| Fase | Cous | OpenTracy | Bloqueante? |
|------|------|-----------|-------------|
| **A** | `SystemPromptCache` (chama `GET /agent/config`); enviar system como `HistoryMessage(role="system")` | **Verificado:** `RunRequest` não tem campo `system`, mas `HistoryMessage` aceita `role:"system"` como workaround | Não — workaround existe |
| **B** | `index_measurement_session()` | Nada — `/knowledge/index` já existe | Não |
| **B2** | `FeedbackStore`, `/confirmar`, `/corrigir`, `/solucao` | Nada — tudo local | Não |
| **D** | Ler `stages[]`, `TraceEmitter` (formato `StageOutcome` compatível) | **Verificado:** runtime devolve `stages[]` com `StageOutcome(stage, technique, variant, duration_ms, docs_in, docs_out, routing_model, error)` | Não |
| **C** | Remover `build_chat_context()` | Nada — gate é operacional | Não |
| **E** | `sync_feedback()` — fluxo: emitir feedback como trace → `POST /evals/goldens/promote-from-trace/:trace_id` | **Verificado:** não há `POST /evals/goldens` direto. Existe `promote-from-trace` e `PUT /datasets/goldens` | Sim — requer adaptação de fluxo |
| **F** | Ajustar URL de sync | Schema PostgreSQL + migrations no runtime | Sim |
| **G** | Emitir traces no formato `StageOutcome` | Configurar harness para canal `"terminal"` | Sim |

#### Conclusão prática

As fases **A até D** — que entregam o maior valor imediato (system prompt, medições indexadas, feedback capturado, pipeline visível) — são trabalho quase exclusivamente do Cous. Dá para executá-las sem tocar no OpenTracy. A Fase A tem workaround imediato (`HistoryMessage(role="system")`) e `SystemPromptCache` via `GET /agent/config`.

As fases **E, F e G** dependem de trabalho real no OpenTracy, mas são as últimas da sequência e têm gates de entrada que naturalmente postergam esse momento. Quando chegar lá, o escopo no OpenTracy é bem delimitado.

### 15.6 Pontos críticos verificados no código

**1. O workaround do `system` já existe parcialmente — de forma não intencional.**  
Em `session.py:history_for_model()`, quando há um resumo salvo, ele é injetado como `{"role": "system", "content": "Resumo persistido..."}` no array `history`. Isso significa que o Cous **já envia** `role: "system"` ao runtime toda vez que há sumarização ativa. O `SystemPromptCache` (seção 17.2) fará o mesmo para o `system.md` do agente — sem tocar no OpenTracy.

**2. `session_id` nunca era enviado ao runtime — corrigido.**  
Em `opentracy.py:chat()`, o payload não incluía `session_id`. O `RunRequest` do runtime tem esse campo e o propaga para `ExecutionRecord` e traces. Sem ele, todos os traces do canal `"terminal"` ficavam com `session_id: null`, e o harness não conseguia reconstituir cadeias causais. **Corrigido no código:** `chat()` agora aceita `session_id` e `terminal.py:_send_chat` o passa (`ctx.session.session_id`).

**3. Injeção de contexto de medições vs pipeline retrieve — o gate A/B é essencial.**  
`build_chat_context()` em `analysis.py` faz matching lexical de termos técnicos (`rpm`, `hall`, `vibration`, `FK Irons`) com score direto. O `all-MiniLM-L6-v2` do pipeline retrieve faz similaridade semântica de embedding. Para vocabulário especializado não-inglês, o matching lexical pode superar o semântico. O gate A/B (10+ queries) está correto. Ação adicional se o gate falhar: aumentar `k` em `retrieve.yaml` (atualmente 30 chunks) antes de abandonar a Fase C.

**4. Mock corrigido.** `MockMeasurementsClient.sync_pending_sessions()` não aceitava `on_progress`. Corrigido para compatibilidade com o handler `_sync_measurements`. Código morto removido.

---

## 16. Contratos de interface

### 16.1 `POST /run` (runtime) — equivalente do chat via backend

**Modelo verificado no código** (`server.py:71`):

```python
class RunRequest(BaseModel):
    request: str
    history: Optional[list[HistoryMessage]] = None
    session_id: Optional[str] = None
    channel: Optional[str] = "web"

class HistoryMessage(BaseModel):
    role: Literal["user", "assistant", "system"]
    content: str
```

⚠️ **Não há campo `system` no `RunRequest`.** Workaround: enviar o system prompt como `HistoryMessage(role="system")` no array `history`.

**Resposta** (`server.py:89`):
```python
class RunResponse(BaseModel):
    response: Optional[str]
    trace_id: str
    success: bool
    duration_ms: int
    error: Optional[str] = None
    agent_version: Optional[str] = None
    stages: list[StageOutcome]
```

### 16.2 `GET /agent/config` — system prompt (verificado)

Retorna `AgentConfigView` com `system_prompt: AgentPromptView`:
```json
{
  "version": "v0.1.0",
  "system_prompt": {
    "path": "prompts/system.md",
    "content": "You are Cous, a specialized technical assistant...",
    "version": "abc123"
  },
  "models": {...},
  "integrations": [...]
}
```

O `SystemPromptCache` chama este endpoint (não um `/agent/{id}/system` inexistente).

### 16.3 `POST /knowledge/index` — indexar medições (verificado)

Já existe, usado pelo Cous hoje.

### 16.4 `POST /evals/goldens/promote-from-trace/:trace_id` — promover feedback (verificado)

Promove um trace existente a golden. **Fluxo para a Fase E:** Cous emite feedback como trace compatível → chama `promote-from-trace` → o runtime transforma em golden.

### 16.5 `PUT /datasets/goldens` — alternativa para merge de goldens

Versiona e atualiza metadados do dataset de goldens. Pode ser usado como alternativa se o Cous exportar feedbacks como NDJSON compatível.

---

## 17. Novos componentes no Cous

### 17.1 FeedbackStore

**Arquivo:** `cous/application/feedback.py`

Registro estruturado de feedback humano. Append-only JSONL, tolerante a corrupção, exportável como goldens para evals.

```python
class FeedbackRecord:
    id: str
    type: str           # "confirmed" | "correction" | "solution_applied"
    session_id: str
    trace_id: str       # trace_id da resposta que gerou o feedback (necessário para promote-from-trace)
    measurement_id: str | None
    content: str
    original_response: str
    timestamp: str

class FeedbackStore:
    def record(self, *, feedback_type, session_id, content, original_response, measurement_id=None) -> FeedbackRecord
    def list_records(self, feedback_type=None) -> list[FeedbackRecord]
    def export_as_goldens(self, output_path) -> int  # Exporta confirmed → formato OpenTracy evals
```

### 17.2 SystemPromptCache

**Arquivo:** `cous/clients/system_prompt.py`

Cache com TTL (padrão 300s) para system prompt. Fallback para snapshot local em caso de falha. Isola o Cous de mudanças do harness durante uma sessão.

```python
class SystemPromptCache:
    def get(self) -> str  # GET /agent/config → extrai system_prompt.content; fallback snapshot local
```

### 17.3 TraceEmitter

**Arquivo:** `cous/logger.py` (extensão)

Converte eventos do terminal em traces compatíveis com o harness. O formato deve ser verificado contra traces reais gerados pelo runtime (canal "web") antes da Fase G. Um trace de referência do runtime deve ser usado como golden para garantir compatibilidade de schema.

```python
class TraceEmitter:
    def emit_chat(self, *, trace_id, session_id, request, response, duration_ms, stages=None, feedback=None) -> None
```

### 17.4 Comandos de feedback no terminal

| Comando | Função |
|---------|--------|
| `/confirmar [comentário]` | Confirma que a última resposta estava correta — gera golden |
| `/corrigir <texto>` | Registra correção para a última resposta |
| `/solucao [id_medicao] <descrição>` | Registra solução aplicada após diagnóstico |

### 17.5 CommandContext expandido

```python
@dataclass
class CommandContext:
    # ... campos existentes ...
    feedback_store: FeedbackStore          # Novo
    system_prompt_cache: SystemPromptCache # Novo
    trace_emitter: TraceEmitter            # Novo
```

---

## 18. Checklist de implementação

### Fundação (pode começar agora, sem mudança no runtime)

- [ ] `feedback.py` — `FeedbackStore` com `record()`, `list_records()`, `export_as_goldens()`
- [ ] `system_prompt.py` — `SystemPromptCache` com TTL + fallback snapshot
- [ ] `logger.py` — `TraceEmitter` com formato compatível com harness
- [ ] `commands.py` — `CommandContext` com novos campos
- [ ] `commands.py` — handlers `/confirmar`, `/corrigir`, `/solucao`
- [ ] `session.py` — método `last_assistant_message()`
- [ ] `config.py` — `FeedbackConfig`, `SystemPromptConfig`, `LogsConfig.traces_file`
- [ ] `mocks.py` — `MockFeedbackStore`
- [ ] `config.example.toml` — novas seções `[feedback]`, `[system_prompt]`, `traces_file`

### Fase A — System prompt no chat

- [ ] `clients/opentracy.py` — parâmetro `session_id` no `chat()` ✅ já feito
- [ ] `terminal.py` — passar `ctx.session.session_id` no `chat()` ✅ já feito
- [ ] `clients/system_prompt.py` — `SystemPromptCache` via `GET /agent/config` com TTL + fallback snapshot
- [ ] `terminal.py` — injetar system prompt como `history[0] role="system"`
- [ ] `main.py` — bootstrap do `SystemPromptCache`

### Fase B — Indexar medições

- [ ] `measurements/analysis.py` — `index_measurement_session()` com metadata
- [ ] `commands.py` — indexar após `/capturar` e `/sincronizar`

### Fase D — Stages + traces

- [ ] `clients/opentracy.py` — retornar `stages[]`
- [ ] `terminal.py` — `TraceEmitter.emit_chat()` após cada chat
- [ ] `renderer.py` — `render_stages()` para o painel de operações

### Fase C — Remover injeção manual (com gate)

- [ ] **Gate:** eval A/B em 10+ queries — retrieve ≥ injeção manual
- [ ] `terminal.py` — remover `build_chat_context()` do `_send_chat`

---

## 19. Referência: estrutura de diretórios

```
OpenTracy/                         Cous (ligadoAi_cous_opentracy)/
├── agent/          ← treinável    └── cous/
│   ├── agent.yaml                     ├── cli/
│   ├── pipeline/                      │   ├── terminal.py    ← loop + contexto
│   │   ├── retrieve.yaml              │   ├── commands.py    ← /comandos
│   │   ├── rerank.yaml                │   └── renderer.py    ← UI terminal
│   │   ├── route.yaml                 ├── clients/
│   │   ├── generate.yaml              │   ├── opentracy.py   ← POST /chat
│   │   └── memory.yaml                │   ├── knowledge.py   ← API knowledge
│   └── prompts/system.md              │   └── measurements.py← API medições
├── harness/        ← evolução        ├── measurements/
│   ├── proposer/                      │   ├── store.py       ← persistência
│   ├── critics/                       │   ├── analysis.py    ← sumarização
│   ├── approver/                      │   ├── validation.py  ← validação
│   ├── executor/                      │   └── serial_capture ← TMA_DATA
│   └── rollback/                      ├── application/
├── evals/          ← qualidade        │   └── session.py     ← conversas JSONL
│   ├── goldens/                       ├── config.py
│   ├── runners/                       ├── auth.py
│   └── suites/                        ├── logger.py
├── corpora/        ← conhecimento     └── mocks.py
│   └── indexed/index.faiss
├── traces/         ← registros
├── experiments/    ← testes
├── backend/        ← gateway HTTP
├── ui/             ← interface web
└── runtime/        ← motor Python
```

---

## Apêndice A — O Ciclo de Vida do Conhecimento Operacional

Este apêndice traça o percurso de um único dado operacional — uma medição de vibração — através do sistema, ilustrando como cada camada da arquitetura transforma dado bruto em conhecimento institucional.

### A.1 Um dado, sete estados

```
┌──────────────────────────────────────────────────────────────────────────┐
│                                                                          │
│  [1] DADO BRUTO                                                          │
│  "hall:freq=125.27Hz,rpm=7516,duty=544 power:V=7998mV,I=-85mA"          │
│  Capturado via serial TMA_DATA, sem interpretação.                       │
│  │                                                                       │
│  ▼                                                                       │
│  [2] DADO ESTRUTURADO                                                    │
│  {type:"hall_snapshot", frequency_hz:125.27, rpm:7516.08, ...}          │
│  Validado, normalizado, persistido em JSON local.                        │
│  │                                                                       │
│  ▼                                                                       │
│  [3] SUMÁRIO DE DOMÍNIO                                                  │
│  "Phantom x1: freq_media=125.27Hz, rpm_media=7516,                      │
│   vibração: RMS=900.46mg, pico=1250mg"                                   │
│  Indexado como documento no FAISS. O pipeline retrieve pode encontrá-lo. │
│  │                                                                       │
│  ▼                                                                       │
│  [4] CONTEXTO RECUPERADO                                                 │
│  Dos 30 chunks do retrieve, 3 são desta medição.                         │
│  O agente os recebe como contexto para a resposta.                       │
│  │                                                                       │
│  ▼                                                                       │
│  [5] DIAGNÓSTICO OU RESPOSTA                                             │
│  "RMS 900mg está acima da referência de 600mg. Verifique bucha e eixo."  │
│  │                                                                       │
│  ▼                                                                       │
│  [6] FEEDBACK VALIDADO                                                   │
│  Técnico: "Troquei a bucha, vibração caiu para 300mg."                  │
│  /confirmar → FeedbackStore → trace → promote-to-golden.                 │
│  │                                                                       │
│  ▼                                                                       │
│  [7] CONHECIMENTO INSTITUCIONAL                                          │
│  Golden: "vibração >800mg → verificar bucha (evidência: Phantom x1,     │
│  série 1212, resolvido com troca)". Harness usa em evals e propostas.    │
│                                                                          │
└──────────────────────────────────────────────────────────────────────────┘
```

### A.2 Por que isso importa

Sistemas RAG tradicionais param no estado 4 — recuperam documentos e respondem. O objetivo desta arquitetura é alcançar o estado 7, onde o sistema não apenas consulta conhecimento, mas **produz conhecimento novo** a partir da operação.

A diferença entre um assistente genérico e um especialista não é o modelo — é a densidade e qualidade dos estados 5→6→7 acumulados ao longo do tempo.

---

## Apêndice B — O Espectro Autônomo-Supervisionado

O harness de auto-melhoria do OpenTracy opera em um espectro, não em modo binário. Esta seção define os modos operacionais e os critérios para transição entre eles.

### B.1 Modos operacionais

| Modo | Quem decide | Gatilho | Risco |
|------|-------------|---------|-------|
| **Fully Supervised** | Humano aprova cada patch no `agent/` | Política de aprovação manual | Zero |
| **Gate-Guarded** | Harness propõe; evals aprovam; humano revisa | Evals passam + threshold de confiança | Baixo |
| **Eval-Driven** | Harness propõe; evals aprovam automaticamente | Evals passam + ausência de regressão | Médio |
| **Continuous** | Harness autônomo 24/7 | Traces novos disponíveis | Alto |

### B.2 Critérios de transição

```
Fully Supervised ──→ Gate-Guarded ──→ Eval-Driven ──→ Continuous
        │                   │                │
        │   Cobertura de    │   Taxa de       │   Sem regressão
        │   goldens > 50    │   falsos         │   em 30+ iterações
        │   casos           │   positivos      │   consecutivas
        │                   │   < 5%           │
        ▼                   ▼                ▼
   Modo inicial         Após 3 meses     Após 6+ meses
   (Fase A-D)           operação         operação estável
```

### B.3 Por que começar supervisionado

O Cous opera em um domínio de alto risco — diagnóstico de máquinas de tatuagem usadas em procedimentos com agulhas. Um diagnóstico incorreto promovido a golden pode gerar recomendações erradas que se propagam para todos os técnicos.

O custo de um falso positivo no harness não é uma resposta ruim — é **conhecimento corrompido** que contamina o agente para sempre. Por isso a Fase E (promoção de feedback a golden) é a última antes do harness — e deve permanecer com supervisão humana até que a taxa de correções (`/corrigir`) sobre diagnósticos seja consistentemente < 5%.

---

## Apêndice C — Modos de Falha e Resiliência

Arquiteturas de aprendizado contínuo têm modos de falha específicos que sistemas estáticos não enfrentam. Esta seção cataloga os principais e define como o sistema sobrevive a cada um.

### C.1 Catálogo de modos de falha

| Modo | Sintoma | Causa | Resiliência |
|------|---------|-------|-------------|
| **Knowledge rot** | Agente piora ao longo do tempo | Goldens enviesados ou feedback incorreto promovido | Rollback de versão do `agent/`; evals com detecção de regressão |
| **Context collapse** | Respostas genéricas, perda de especificidade | Pipeline retrieve falha; modelo responde só com conhecimento pré-treinado | Fallback: injeção lexical mantida como safety net até gate A/B passar |
| **Harness spiral** | Harness propõe → aprova → propõe sem melhoria real | Loop de auto-reforço sem diversidade de traces | Métrica de diversidade: se 3 iterações consecutivas mudam < 5% dos evals, pausa o harness |
| **Feedback starvation** | Sem goldens novos por semanas | Técnicos não usam `/confirmar` ou `/corrigir` | Prompt proativo: após 10 chats sem feedback, agente pergunta "esta resposta foi útil?" |
| **Trace orphanage** | Traces existem mas harness não os consome | `session_id` nulo ou canal não configurado | **Corrigido:** `session_id` enviado em todo chat. Validação: health check do harness reporta traces orphans |
| **Disk exhaustion** | `.cous-data/` enche o disco | Logs, conversas ou medições sem limite | Rotação de logs implementada (Fase 3). Cotas: máx 1000 conversas, máx 10K medições antes de warning |
| **Serial dropout** | Captura TMA_DATA incompleta | Cabo solto, EMI, buffer overflow | Timeout de captura + retry automático. Sessão parcial salva como `draft` com snapshots válidos |
| **Model bankruptcy** | Custo de API explode | Routing falha e usa `deepseek-reasoner` para "olá" | Route pipeline monitorado; alerta se > 20% das chamadas usam modelo grande |

### C.2 Princípio de degradação graciosa

Nenhuma falha em componente de aprendizado pode bloquear a operação básica:

```
Falha no FAISS      → chat funciona sem knowledge (modo fallback)
Falha no harness    → chat funciona normalmente (agente não evolui)
Falha no PostgreSQL → medições continuam em JSON local
Falha no runtime    → Cous opera offline com mocks locais
Falha no disco      → logger captura OSError, não derruba o terminal
```

A única falha catastrófica é **corrupção de goldens** — porque conhecimento falso é pior que conhecimento zero. Daí a permanência do modo supervisionado na Fase E.

### C.3 O paradoxo do aprendizado contínuo

Sistemas que aprendem com sua própria operação enfrentam um paradoxo:

> Se o sistema aprende com respostas que ele mesmo gerou, e essas respostas contêm erros, o aprendizado amplifica os erros.

A arquitetura resolve isso com três salvaguardas:
1. **Feedback humano** é a única fonte de goldens (nunca auto-promoção)
2. **Evals** detectam regressão antes do deploy
3. **Rollback** versionado permite desfazer qualquer iteração
