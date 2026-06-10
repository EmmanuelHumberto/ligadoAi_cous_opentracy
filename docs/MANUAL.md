# Manual Completo do Cous — Cliente Terminal para OpenTracy

> **Versão do Cous:** 2.0.0  
> **Repositório:** `ligadotattoo/ligadoAi_cous_opentracy`  
> **Requisito:** Python 3.11+  
> **Fases concluídas:** Fundação, A (system prompt), B (indexação medições), B2 (feedback), C (pipeline retrieve), D (traces), E (goldens)

---

## 1. Visão Geral

O **Cous** é um cliente de terminal fino (thin client) para a plataforma OpenTracy, desenvolvido com a biblioteca Rich para interface interativa. Ele substitui o Cous legado que residia em `opentracy-terminal-chat`, que agora serve apenas como referência de UX e contratos — nunca como base de código.

### 1.1 O que o Cous faz

- Terminal interativo com interface rica via **Rich** (painéis, tabelas, cores)
- **Autenticação por dois tokens Bearer** independentes (knowledge + API do agente)
- **Chat com o agente** do OpenTracy via backend HTTP (`/v1/api/<agent_id>/chat`)
- **System prompt automático** — cache com TTL do `system.md` do agente, injetado em todo chat (Fase A)
- **Pipeline retrieve como padrão** — o OpenTracy decide relevância via RAG, sem injeção manual (Fase C)
- **Persistência local de sessões de chat** em arquivos JSONL
- **Resumo manual e automático** de conversa (compressão de contexto por tamanho)
- **Logs JSONL** de eventos do terminal
- **Emissão de traces** compatíveis com o harness de auto-melhoria do OpenTracy (Fase D)
- **Comandos de knowledge:** indexar, validar, buscar, remover, listar documentos
- **Indexação automática de medições** no FAISS após captura (Fase B)
- **Captura, persistência local e sincronização** de medições (TMA_DATA via porta serial)
- **Diagnóstico e laudo** de medições (remoto com fallback local)
- **Feedback humano estruturado** — comandos `/confirmar`, `/corrigir`, `/solucao` (Fase B2)
- **Promoção de feedback a golden** — `/confirmar` promove trace a golden no OpenTracy (Fase E)
- **Modo mock** para desenvolvimento e testes offline

### 1.2 O que o Cous NÃO faz (delegado ao OpenTracy)

- Geração de embeddings e índice vetorial (FAISS)
- Pipeline retrieve/rerank/route/generate — o OpenTracy é o motor cognitivo
- OCR e conversão de documentos
- Chunking de documentos
- Reload manual de corpus
- Decidir relevância de contexto — o pipeline retrieve do OpenTracy assume essa responsabilidade (Fase C)
- Harness de auto-melhoria — o Cous apenas emite traces compatíveis e promove goldens

### 1.3 Objetivos do Projeto

O Cous é a face operacional do ecossistema LigadoAI/OpenTracy para técnicos de manutenção de máquinas de tatuagem. Ele permite:

- Conversar com um agente de IA sobre máquinas, coletas, laudos e diagnósticos
- Capturar dados de sensores (hall, power, course, vibration) via porta serial
- Sincronizar medições com o backend remoto para análise avançada
- Indexar e buscar documentação técnica (datasheets, manuais)
- Gerar diagnósticos e laudos técnicos automaticamente

---

---

## Guia Rápido de Inicialização

### Subir o ecossistema (4 terminais)

```bash
# Terminal 1 — PostgreSQL (deve estar rodando em localhost:5432)
# O banco 'ligadoai' é usado tanto para knowledge quanto para medições.
# Se estiver usando Docker:
docker run -d --name ligadoai-pg \
  -e POSTGRES_USER=ligadoai -e POSTGRES_PASSWORD=ligadoai \
  -e POSTGRES_DB=ligadoai -p 5432:5432 \
  postgres:16

# Terminal 2 — Runtime do OpenTracy (porta 8001)
cd /home/hiatus/Projetos/ligadotattoo/OpenTracy
uv run python -m runtime.server

# Terminal 3 — Backend (porta 8002)
cd /home/hiatus/Projetos/ligadotattoo/OpenTracy/backend
npm run start

# Terminal 4 — Cous (bootstrap + iniciar)
cd /home/hiatus/Projetos/ligadotattoo/ligadoAi_cous_opentracy
uv run cous --bootstrap   # só na primeira vez
uv run cous               # uso normal
```

### Dentro do Cous

```bash
/ajuda                # lista todos os comandos
/capturar             # inicia captura de medição (interativo)
/medicoes             # lista medições salvas
/medicoes FK          # filtra por termo
/medicao <id>         # detalhes de uma medição
/novo                 # nova sessão de chat
/listar               # lista sessões de chat
/exportar             # exporta conversa como markdown
/status               # status do OpenTracy
/sair                 # encerra
```

### Modo offline (sem OpenTracy)

```bash
uv run cous --mock    # clientes fake, não exige tokens
```

## 2. Arquitetura e Estrutura do Projeto

```
ligadoAi_cous_opentracy/
├── config.toml              # Configuração local (não versionada)
├── config.example.toml      # Template de configuração
├── pyproject.toml           # Dependências e entrypoint
├── uv.lock                  # Lockfile do uv
├── README.md                # Documentação de referência
├── docs/
│   ├── ARQUITETURA.md       # Arquitetura do ecossistema Cous + OpenTracy
│   └── MANUAL.md            # Este manual
├── .cous-data/              # Dados locais (não versionados)
│   ├── conversations/       # Sessões de chat JSONL
│   ├── measurements.json    # Store local de medições
│   ├── feedback/            # Registros de feedback (records.jsonl)
│   ├── logs/
│   │   ├── events.jsonl     # Log de eventos do terminal
│   │   └── traces.jsonl     # Traces compatíveis com harness (Fase D)
│   └── system_prompt_snapshot.md  # Cache local do system prompt
└── cous/                    # Código-fonte do cliente
    ├── main.py              # Entrypoint CLI
    ├── config.py            # Carregamento tipado de config.toml (Pydantic)
    ├── auth.py              # Provedores de token (env / arquivo)
    ├── bootstrap.py         # Bootstrap da autenticação
    ├── logger.py            # Logger JSONL de eventos + TraceEmitter
    ├── mocks.py             # Clientes fake para modo --mock
    ├── application/
    │   ├── session.py       # ChatSession + ConversationStore (JSONL)
    │   └── feedback.py      # FeedbackStore — registro de feedback humano (Fase B2)
    ├── cli/
    │   ├── terminal.py      # Loop interativo principal
    │   ├── commands.py      # Router de comandos + handlers
    │   └── renderer.py      # Renderização Rich (tabelas, painéis)
    ├── clients/
    │   ├── base.py          # HTTP client autenticado + ClientError
    │   ├── opentracy.py     # Cliente de chat + health + tools + config + goldens
    │   ├── knowledge.py     # Cliente de knowledge (index/search/validate)
    │   ├── system_prompt.py # SystemPromptCache — cache do system.md com TTL (Fase A)
    │   └── measurements.py  # Cliente de medições (CRUD + sync + diagnose)
    └── measurements/
        ├── store.py         # MeasurementLocalStore (JSON)
        ├── validation.py    # Validação de cabeçalho e snapshots
        ├── serial_capture.py# Captura serial TMA_DATA (Linux-only, termios)
        └── analysis.py      # Análise local (sumarização, busca, laudo, indexação FAISS)
```

### 2.1 Dependências

| Biblioteca    | Uso                                |
|---------------|------------------------------------|
| `httpx>=0.27` | HTTP client síncrono               |
| `pydantic>=2` | Validação de configuração tipada   |
| `rich>=13.0`  | Interface de terminal rica          |
| `pytest>=8`   | Testes (dev)                       |
| `ruff>=0.8`   | Linting (dev)                      |

### 2.2 Fluxo de Dados

```
Terminal (Rich) ──► CommandRouter ──► Handlers ──► Clients (HTTP)
                       │                              │
                       ▼                              ▼
                  ConversationStore            OpenTracy Backend (8002)
                  MeasurementLocalStore        OpenTracy Runtime (8001)
                  EventLogger                  System prompt (cache + fallback)
                  FeedbackStore                Traces (TraceEmitter → harness)
                  TraceEmitter                 Goldens (promote-from-trace)
```

---

## 3. Requisitos e Instalação

### 3.1 Pré-requisitos

- **Python 3.11+**
- **uv** (gerenciador de pacotes)
- OpenTracy backend em `http://localhost:8002`
- OpenTracy runtime em `http://localhost:8001`
- Token de knowledge do OpenTracy
- Token de API do agente

**Para captura serial (opcional):**
- Linux (ou sistema compatível com `termios`)
- Porta serial acessível (ex: `/dev/ttyACM0`)

### 3.2 Instalação

```bash
cd ligadotattoo/ligadoAi_cous_opentracy
uv sync --extra dev
```

### 3.3 Configuração

O cliente procura `config.toml` no diretório atual ou na raiz do repositório.
Crie seu arquivo a partir do template:

```bash
cp config.example.toml config.toml
```

**Parâmetros principais de `config.toml`:**

```toml
[opentracy]
backend_url = "http://localhost:8002"   # Backend de chat
runtime_url = "http://localhost:8001"   # Runtime (knowledge + medições)
agent_id = "cous"                        # Nome do agente
timeout = 30                            # Timeout HTTP em segundos

[auth]
token_file = "~/.cous/opentracy_token"              # Token de knowledge
env_var = "COUS_OPENTRACY_TOKEN"                     # Variável de ambiente
api_token_file = "~/.ligadoai/api_token"             # Token da API do agente
api_env_var = "COUS_OPENTRACY_API_TOKEN"             # Variável de ambiente
opentracy_env_file = "../OpenTracy/.env"             # .env do runtime
opentracy_env_key = "OPENTRACY_KNOWLEDGE_AUTH_TOKEN"
opentracy_measurements_env_key = "OPENTRACY_MEASUREMENTS_AUTH_TOKEN"

[memory]
max_history = 10                        # Mensagens recentes enviadas ao agente
max_chars_before_summary = 16000        # Limite para resumo automático

[chat]
conversations_dir = ".cous-data/conversations"  # Sessões de chat JSONL

[measurements]
storage_file = ".cous-data/measurements.json"   # Store local de medições

[logs]
events_file = ".cous-data/logs/events.jsonl"    # Log de eventos do terminal
max_size_mb = 10                                # Tamanho máximo do arquivo de log
backup_count = 3                                # Número de backups rotacionados
traces_file = ".cous-data/logs/traces.jsonl"    # Traces compatíveis com harness (Fase D)

[feedback]
storage_file = ".cous-data/feedback/records.jsonl"  # Registros de feedback humano (Fase B2)

[system_prompt]
cache_ttl_seconds = 300                         # TTL do cache do system prompt
snapshot_file = ".cous-data/system_prompt_snapshot.md"  # Fallback local

[mcp]
timeout_seconds = 30
max_restarts = 3
restart_backoff_seconds = 5
```

**Parâmetros de memória:**

- `max_history` — quantidade de mensagens recentes enviadas como contexto ao agente (além do resumo persistido).
- `max_chars_before_summary` — quando o conteúdo não resumido ultrapassa esse limite, o Cous gera um resumo automático e o persiste na sessão.

---

## 4. Bootstrap e Autenticação

O Cous usa **dois tokens Bearer** independentes:

1. **Token de knowledge** — para indexar/buscar documentos e sincronizar medições
2. **Token de API do agente** — para enviar mensagens de chat ao agente

### 4.1 Executando o Bootstrap

```bash
uv run cous --bootstrap
```

O bootstrap executa as seguintes ações:

1. Cria `~/.cous/opentracy_token` se não existir (token aleatório de 32 bytes url-safe)
2. Aplica permissão `0600` no arquivo
3. Grava o token no `.env` do OpenTracy como:
   - `OPENTRACY_KNOWLEDGE_AUTH_TOKEN`
   - `OPENTRACY_MEASUREMENTS_AUTH_TOKEN`
4. Tenta garantir que o agente configurado em `agent_id` exista no runtime
5. Tenta conectar o canal API via `POST /agents/<agent_id>/channels/api/connect`
6. Quando o runtime devolve um token `ot_*`, salva em `~/.ligadoai/api_token`

**Após o bootstrap, reinicie o runtime do OpenTracy.**

### 4.2 Autenticação em Tempo de Execução

O `TokenProvider` tenta carregar o token nesta ordem:

1. Variável de ambiente (`COUS_OPENTRACY_TOKEN` / `COUS_OPENTRACY_API_TOKEN`)
2. Arquivo de token (`~/.cous/opentracy_token` / `~/.ligadoai/api_token`)

Falhas de autenticação:
- `401` — token ausente, inválido ou expirado
- `403` — token válido mas sem permissão para a ação
- Arquivo com permissão incorreta gera `AuthError`

---

## 5. Execução e Modos de Operação

### 5.1 Execução Normal

```bash
uv run cous
```

Requer tokens configurados e runtime OpenTracy ativo.

### 5.2 Modo Mock (Desenvolvimento / Testes Offline)

```bash
uv run cous --mock
```

No modo mock:
- **Não exige tokens** nem OpenTracy ativo
- Usa clientes fake locais (`MockOpenTracyClient`, `MockKnowledgeClient`, `MockMeasurementsClient`)
- Todas as operações de chat, knowledge e medições são simuladas
- Útil para validar UX do terminal e testar fluxos locais sem hardware

### 5.3 Flags Disponíveis

```
uv run cous [--mock] [--bootstrap] [--no-runtime] [--config <arquivo.toml>]
```

| Flag            | Descrição                                            |
|-----------------|------------------------------------------------------|
| `--mock`        | Clientes fake locais, sem OpenTracy real             |
| `--bootstrap`   | Prepara tokens de autenticação e sai                 |
| `--no-runtime`  | Reservado (ainda não altera comportamento)           |
| `--config`      | Usa arquivo de configuração específico               |

### 5.4 Ao Iniciar

O terminal exibe um banner de boas-vindas e tenta reabrir a sessão de chat mais recente. Se não houver nenhuma, cria uma nova com ID no formato:

```
chat_20260609_104530_ab12cd
```

---

## 6. Referência Completa de Comandos

Todos os comandos são prefixados com `/`. O router aceita aliases (atalhos).

### 6.1 Comandos Gerais

| Comando       | Alias        | Descrição                                    |
|---------------|--------------|----------------------------------------------|
| `/ajuda`      | `/h`         | Lista todos os comandos disponíveis          |
| `/sair`       | `/q`, `/exit`| Encerra o programa                           |
| `/limpar`     | `/cls`       | Limpa a tela                                 |
| `/status`     | `/st`        | Mostra status do OpenTracy (4 verticais)     |
| `/tools`      | —            | Lista MCP tools expostas pelo agente         |

#### `/status`
Mostra uma tabela com 4 verticais:
- **OpenTracy backend** — `ok` / `offline`
- **OpenTracy runtime** — `ok` / `offline`
- **Knowledge API** — `ok` / `auth_falhou` / `indisponivel`, com docs e chunks
- **Measurements API** — `ok` / `desabilitado` / `auth_falhou`, com backend, db e auth

---

### 6.2 Comandos de Chat

| Comando      | Alias | Descrição                                           |
|--------------|-------|-----------------------------------------------------|
| `/novo`      | `/n`  | Cria nova sessão de chat persistida                |
| `/listar`    | `/ls` | Lista sessões de chat persistidas (tabela)         |
| `/carregar`  | `/cg` | Carrega sessão por ID ou prefixo único             |
| `/memoria`   | —     | Mostra sessão atual, nº de mensagens e resumo      |
| `/resumo`    | —     | Pede ao agente resumo técnico da conversa atual    |

#### Fluxo de Sessão de Chat

1. Cada sessão recebe um ID: `chat_AAAAMMDD_HHMMSS_xxxxxx`
2. O arquivo JSONL contém eventos:
   - `meta` — metadados da sessão
   - `message` — mensagens user/assistant
   - `summary` — resumo persistido (contexto comprimido)
   - `reset` — limpeza de histórico
3. Ao enviar mensagem ao agente, o Cous anexa:
   - O resumo persistido como mensagem `system` (se existir)
   - As últimas `max_history` mensagens como histórico
4. **Resumo automático:** após cada resposta, se `pending_summary_chars() > max_chars_before_summary`, gera resumo automático
5. **Contexto de medições:** se a mensagem contém termos como "medição", "coleta", "laudo", "snapshot", etc., o Cous anexa contexto local das medições mais relevantes

#### `/novo`
- Cria nova sessão de chat e troca a sessão corrente
- A sessão anterior continua preservada em disco

#### `/listar`
Mostra tabela com colunas: ID, Msgs, Resumo (sim/não), Atualizada, Preview

#### `/carregar <id-ou-prefixo>`
- Aceita ID completo ou prefixo único
- Se chamado sem argumento, carrega a sessão mais recente

#### `/memoria`
- Mostra: session_id, número de mensagens, se tem resumo persistido

#### `/resumo`
- Envia a conversa completa ao agente com instrução de resumo técnico
- Usa canal `terminal_summary`
- O resumo é salvo como evento `summary` no JSONL da sessão

---

### 6.3 Comandos de Feedback (Fases B2 e E)

| Comando                     | Descrição                                                           |
|-----------------------------|---------------------------------------------------------------------|
| `/confirmar [comentário]`   | Confirma que a última resposta estava correta — promove trace a golden |
| `/corrigir <texto>`         | Registra correção para a última resposta                            |
| `/solucao [id_medicao] <descrição>` | Registra solução aplicada após diagnóstico                   |

#### `/confirmar [comentário]`
- Confirma a última resposta do agente como correta
- Registra no `FeedbackStore` local (JSONL)
- Chama `POST /evals/goldens/promote-from-trace/{trace_id}` para promover o trace a golden no OpenTracy (Fase E)
- Exibe confirmação com `trace_id` promovido

#### `/corrigir <texto>`
- Registra uma correção para a última resposta do agente
- O texto deve conter a informação correta ou o erro identificado
- Registrado no `FeedbackStore` como tipo `correction`

#### `/solucao [id_medicao] <descrição>`
- Registra a solução técnica aplicada após um diagnóstico
- Opcionalmente associada a uma medição específica
- Registrado no `FeedbackStore` como tipo `solution`

---

### 6.4 Comandos de Knowledge

| Comando      | Descrição                                               |
|--------------|---------------------------------------------------------|
| `/validar`   | Valida arquivo ou pasta para knowledge                 |
| `/indexar`   | Cria jobs de ingestão no OpenTracy + polling           |
| `/indexados` | Lista documentos indexados (tabela)                    |
| `/buscar`    | Busca na base de conhecimento (tabela de resultados)   |
| `/remover`   | Remove documento do índice por ID                      |

#### Tipos de Arquivo Suportados
`.md`, `.txt`, `.docx`

#### `/validar [arquivo|pasta]`
- Se não receber argumento, pergunta interativamente
- Para cada arquivo, mostra:
  - `OK` — aprovado (chars, tipo de conteúdo)
  - `REPROVADO` — com códigos de erro (ex: `empty_document`)
- Resumo final: X aprovados, Y reprovados

#### `/indexar <arquivo|pasta>`
- Se for diretório, varre recursivamente e processa em lote
- Valida antes de indexar (arquivos reprovados são ignorados)
- Cria um job de ingestão e faz polling a cada 1s (até 120s)
- Estados de job: `indexed`, `failed`, `cancelled`, `skipped`
- Em caso de falha, mostra código e mensagem de erro

#### `/indexados`
- Tabela: ID, Título, Fabricante, Modelo, Status

#### `/buscar [consulta]`
- Se não receber argumento, pergunta interativamente
- Tabela de resultados: Score, Fonte, Trecho (120 chars)

#### `/remover [document_id]`
- Se não receber argumento, pergunta interativamente
- Remove o documento do índice remoto

---

### 6.5 Comandos de Medições

| Comando        | Alias  | Descrição                                                    |
|----------------|--------|--------------------------------------------------------------|
| `/capturar`    | `/cp`  | Cria sessão de medição/coleta (interativa ou por argumentos) |
| `/medicoes`    | `/m`   | Lista sessões de medição locais (tabela, com filtro opcional)|
| `/medicao`     | `/md`  | Mostra detalhes completos de uma medição                     |
| `/sincronizar` | `/sync`| Sincroniza medições com o runtime (uma ou todas pendentes)   |
| `/diagnostico` | `/dg`  | Gera diagnóstico de uma medição (remoto com fallback local)  |
| `/laudo`       | `/ld`  | Gera laudo em markdown de uma medição                        |

#### `/capturar`
Fluxo completo:

1. **Preenchimento do cabeçalho** (interativo ou por argumentos inline)
2. **Validação do cabeçalho** (antes de criar a sessão)
3. **Captura serial** (a menos que `sem_serial=sim`)
4. **Validação de snapshots** (filtragem por tipo)
5. **Ação pós-captura:** salvar, descartar, sair ou refazer
6. **Sincronização automática** (tenta sincronizar após salvar)

#### Cabeçalho da Medição — Campos

**Dados da máquina:**
- `fabricante` (padrão: DKLAB)
- `modelo`
- `numero_serie` (alias: `serie`, `serial`)
- `tipo_maquina` (padrão: tattoo_machine)
- `tipo_motor` (padrão: coreless)
- `sistema_transmissao` (padrão: direct, alias: `transmissao`)
- `curso_nominal_mm` (alias: `curso`)
- `curso_min_mm`
- `curso_max_mm`

**Dados da coleta:**
- `tipo_coleta` (padrão: desempenho, alias: `coleta`)
  - Opções: `desempenho`, `reparo`, `pos-reparo`, `homologacao`, `bancada`, `calibracao`, `laudo_calibracao`
- `peca_substituida` (obrigatória para `reparo` e `pos-reparo`)
- `observacoes`
- `tecnico`

**Conexão serial:**
- `porta_serial` (padrão: /dev/ttyACM0, alias: `porta`)
- `baudrate` (padrão: 115200)
- `duracao_seg` (padrão: 30.0, alias: `duracao`)

**Seleção de TMA_DATA:**
- `verticais` — lista das verticais a capturar: `hall`, `power`, `course`, `vibration`
- `sem_serial` — criar sessão sem capturar agora (alias: `dry_run`, `no_serial`)

#### Captura por Argumentos (Inline)

```bash
/capturar fabricante="FK Irons" modelo=Flux serie=SN123 tipo_coleta=desempenho transmissao=direct porta=/dev/ttyACM0 verticais=hall,power,course,vibration
```

#### Validação do Cabeçalho

Regras aplicadas antes de criar a sessão:
- `peca_substituida` é obrigatória em `reparo` e `pos-reparo`
- `verticais` não pode ficar vazia
- `baudrate` deve ser positivo
- `duracao_seg` deve ser positiva
- Quando os três valores de curso existem, `curso_nominal_mm` deve ficar entre `curso_min_mm` e `curso_max_mm`
- Verticais desconhecidas são rejeitadas

#### Validação de Snapshots

Cada snapshot é validado:
- `type` deve estar na lista de verticais permitidas da sessão
- `type` é obrigatório
- `timestamp_us` (se presente) deve ser >= 0
- Snapshot deve ter payload útil (mais que apenas `type`)

Snapshots inválidos são contabilizados como rejeitados e não entram na sessão.

#### `/medicoes [filtro]`
- Tabela: ID, Fabricante, Modelo, Status, Sync, Snapshots, Atualizada
- Filtro por texto busca nos campos do cabeçalho e ID

#### `/medicao [id]`
- Sem argumento: sugere a sessão mais recente
- Mostra tabela detalhada com todos os campos do cabeçalho + snapshots + sync

#### `/sincronizar [id]`
- Com ID: sincroniza uma sessão específica
- Sem ID: sincroniza todas as pendentes (status `saved`, `diagnosed` ou `reported` e sync_status != `synced`)
- Fluxo da sincronização:
  1. Se já tem `remote_id`, faz GET para obter a sessão remota
  2. Se não tem, faz POST para criar sessão remota com o cabeçalho
  3. Envia snapshots via POST para o endpoint remoto
  4. Atualiza `sync_status`, `remote_id` e `last_sync_error` localmente

#### `/diagnostico [id]`
- Prefere o backend remoto quando a sessão já tem `remote_id`
- Se não tem `remote_id`, tenta sincronizar primeiro
- Cai para modo local se o runtime falhar
- Retorna: status `approved` (sim/não), resumo, e a sessão atualizada

#### `/laudo [id]`
- Mesmo comportamento do diagnóstico (remoto com fallback local)
- Retorna laudo em markdown (renderizado no painel do agente)
- Status da sessão atualizado para `reported`

---

## 7. Estados de Sincronização

| Estado          | Significado                                                    |
|-----------------|----------------------------------------------------------------|
| `local_only`    | Sessão criada, ainda não sincronizada                          |
| `synced`        | Sessão sincronizada com o backend remoto                       |
| `sync_failed`   | Tentativa remota falhou; sessão preservada localmente          |
| `mock_synced`   | Apenas no modo `--mock`                                        |

---

## 8. Estados de Sessão de Medição

| Estado       | Significado                                       |
|--------------|---------------------------------------------------|
| `draft`      | Sessão criada, cabeçalho preenchido               |
| `saved`      | Snapshots salvos, sessão finalizada               |
| `abandoned`  | Sessão pausada (operador escolheu "sair")         |
| `diagnosed`  | Diagnóstico gerado (local ou remoto)              |
| `reported`   | Laudo gerado (local ou remoto)                    |

---

## 9. Funcionalidades do Chat

### 9.1 System Prompt Automático (Fase A)

A cada mensagem enviada ao agente, o Cous injeta o `system.md` do OpenTracy como mensagem de sistema (`role: "system"`). O system prompt é obtido via `GET /agent/config` e mantido em cache com TTL configurável (padrão: 300s). Em caso de falha na obtenção remota, um snapshot local é usado como fallback.

Isso garante que o agente sempre responda com a especialização de domínio definida no `system.md`, que é a superfície treinável do OpenTracy — o harness pode modificá-la ao longo do tempo.

### 9.2 Pipeline Retrieve como Padrão (Fase C)

O Cous **não injeta mais contexto de medições manualmente** no `request_text`. Em vez disso:

1. Após cada `/capturar`, as medições são automaticamente indexadas no FAISS do OpenTracy via `POST /knowledge/index` (Fase B)
2. O pipeline retrieve do OpenTracy (`retrieve → rerank → route → generate`) busca os documentos relevantes — incluindo sumários de medições — automaticamente
3. O agente recebe o contexto via RAG, sem intervenção manual do Cous

A remoção da injeção manual foi validada com um gate A/B: o pipeline retrieve com `multilingual-e5-base` iguala ou supera a injeção manual para queries em português.

### 9.3 Emissão de Traces (Fase D)

Após cada resposta do agente, o Cous emite um trace compatível com o harness de auto-melhoria do OpenTracy:

- **Local:** `.cous-data/logs/traces.jsonl`
- **Formato:** compatível com `StageOutcome` do runtime (stage, technique, variant, duration_ms, docs_in, docs_out)
- **Metadados:** `trace_id`, `session_id`, `channel="terminal"`, `request`, `response`, `duration_ms`
- **Uso:** O harness proposer consome esses traces para gerar propostas de melhoria no agente (Fase G)

### 9.4 Resumo Automático

O resumo automático é disparado quando:
- O total de caracteres nas mensagens ainda não resumidas (`pending_summary_chars()`) ultrapassa `max_chars_before_summary` (padrão: 16000)
- Ocorre após cada resposta do agente
- O resumo é persistido como evento `summary` no JSONL e usado como contexto comprimido nas próximas chamadas

---

## 10. Logs de Eventos

O terminal grava eventos JSONL em `.cous-data/logs/events.jsonl`.

**Eventos registrados:**

| Evento               | Descrição                                   |
|----------------------|---------------------------------------------|
| `startup`            | Inicialização do terminal                   |
| `terminal_ready`     | Terminal pronto para input                  |
| `input_received`     | Input recebido (com flag is_command)        |
| `command_dispatch`   | Comando despachado (command + args)         |
| `command_unknown`    | Comando não reconhecido                     |
| `chat_user`          | Mensagem do usuário enviada ao agente       |
| `chat_assistant`     | Resposta do agente recebida                 |
| `chat_error`         | Erro na comunicação com o agente            |
| `summary_updated`    | Resumo atualizado (automático ou manual)    |
| `summary_error`      | Falha ao gerar resumo automático            |
| `chat_session_created` | Nova sessão de chat criada               |
| `chat_session_loaded`  | Sessão de chat carregada                 |
| `terminal_exit`      | Encerramento do terminal                    |
| `feedback_confirmed` | Feedback confirmado pelo operador (Fase B2) |
| `feedback_corrected` | Correção registrada pelo operador (Fase B2) |
| `feedback_solution`  | Solução aplicada registrada (Fase B2)       |
| `golden_promoted`    | Trace promovido a golden no OpenTracy (Fase E) |

---

## 11. Estrutura de Dados Locais

### 11.1 `.cous-data/conversations/<session_id>.jsonl`

Arquivo JSONL com uma entrada por linha. Tipos de evento:

```jsonl
{"type": "meta", "session_id": "chat_20260609_104530_ab12cd", "created_at": "...", "updated_at": "..."}
{"type": "message", "session_id": "chat_...", "role": "user", "content": "Qual o diagnóstico?", "timestamp": "..."}
{"type": "message", "session_id": "chat_...", "role": "assistant", "content": "Diagnóstico: ...", "timestamp": "..."}
{"type": "summary", "session_id": "chat_...", "summary": "Resumo técnico...", "summarized_until": 2, "timestamp": "..."}
{"type": "reset", "session_id": "chat_...", "timestamp": "..."}
```

### 11.2 `.cous-data/measurements.json`

```json
{
  "sessions": [
    {
      "id": "med_20260609_104530_ab12cd",
      "status": "saved",
      "sync_status": "synced",
      "remote_id": "uuid-do-backend",
      "header": {
        "fabricante": "DKLAB",
        "modelo": "W1PRO",
        "tipo_coleta": "desempenho",
        "verticais": ["hall", "power"],
        ...
      },
      "snapshots": [
        {"type": "hall_snapshot", "timestamp_us": 1, "frequency_hz": 120, ...}
      ],
      "total_snapshots": 1,
      "valid_snapshots": 1,
      "invalid_snapshots": 0,
      "snapshots_by_type": {"hall": 1},
      "created_at": "2026-06-09T10:45:30.123456+00:00",
      "updated_at": "2026-06-09T10:46:00.123456+00:00"
    }
  ]
}
```

---

### 11.3 `.cous-data/feedback/records.jsonl`

Registros de feedback humano (Fase B2). Um registro por linha:

```jsonl
{"type": "confirmation", "session_id": "chat_...", "trace_id": "trace_...", "content": "Diagnóstico correto", "timestamp": "..."}
{"type": "correction", "session_id": "chat_...", "trace_id": "trace_...", "content": "Não era a bucha, era o capacitor", "timestamp": "..."}
{"type": "solution", "session_id": "chat_...", "measurement_id": "med_...", "content": "Troquei a fonte e resolveu", "timestamp": "..."}
```

Tipos de feedback:
- `confirmation` — operador confirma que a resposta estava correta (promovível a golden)
- `correction` — operador corrige a resposta do agente
- `solution` — operador registra a solução técnica aplicada

### 11.4 `.cous-data/logs/traces.jsonl`

Traces compatíveis com o harness de auto-melhoria do OpenTracy (Fase D):

```jsonl
{"ts": "2026-06-09T10:45:30.123456+00:00", "trace_id": "trace_...", "session_id": "chat_...", "channel": "terminal", "request": "...", "response": "...", "duration_ms": 1234, "agent_version": "v0.0.5", "stages": [{"stage": "retrieve", "technique": "dense", "variant": "multilingual-e5-base", "duration_ms": 45, "docs_in": 30, "docs_out": 5}]}
```

---

## 12. Integração com OpenTracy — Endpoints Usados

### 12.1 Chat (via backend — porta 8002)

| Método | Endpoint                                      | Uso                  |
|--------|-----------------------------------------------|----------------------|
| POST   | `/v1/api/{agent_id}/chat`                     | Enviar mensagem      |
| GET    | `/v1/agents/{agent_id}/mcp/tools`             | Listar MCP tools     |
| POST   | `/v1/evals/goldens/promote-from-trace/{trace_id}` | Promover trace a golden (Fase E) |
| GET    | `/health`                                     | Health check         |

### 12.2 Knowledge (via runtime — porta 8001)

| Método | Endpoint                           | Uso                  |
|--------|------------------------------------|----------------------|
| GET    | `/knowledge/status`                | Status do knowledge  |
| POST   | `/knowledge/validate`              | Validar documento    |
| POST   | `/knowledge/index`                 | Indexar documento    |
| GET    | `/knowledge/jobs/{job_id}`         | Status do job        |
| GET    | `/knowledge/documents`             | Listar documentos    |
| POST   | `/knowledge/search`                | Buscar documentos    |
| DELETE | `/knowledge/documents/{id}`        | Remover documento    |

### 12.3 Medições (via runtime — porta 8001)

| Método | Endpoint                                        | Uso                    |
|--------|-------------------------------------------------|------------------------|
| GET    | `/measurements/status`                          | Status das medições    |
| POST   | `/measurements/sessions`                        | Criar sessão remota    |
| GET    | `/measurements/sessions/{id}`                   | Obter sessão remota    |
| POST   | `/measurements/sessions/{id}/snapshots`         | Enviar snapshots       |
| POST   | `/measurements/sessions/{id}/diagnose`          | Diagnóstico remoto     |
| POST   | `/measurements/sessions/{id}/report`            | Laudo remoto           |

### 12.4 Bootstrap (via runtime — porta 8001)

| Método | Endpoint                                    | Uso                      |
|--------|---------------------------------------------|--------------------------|
| GET    | `/agents/{agent_id}`                        | Verificar agente         |
| POST   | `/agents`                                   | Criar agente             |
| POST   | `/agents/{agent_id}/channels/api/connect`   | Conectar canal API       |
| POST   | `/agents/{agent_id}/channels/api/rotate`    | Rotacionar token API     |
| GET    | `/agent/config`                             | Obter config do agente (system prompt, Fase A) |

---

## 13. Fluxo Completo para Testar Todas as Funcionalidades

Este fluxo cobre **todas** as funcionalidades do Cous, do bootstrap ao laudo, passando por modo mock e modo real.

### Fase 0 — Preparação do Ambiente

```bash
# 1. Entre no diretório do projeto
cd /home/hiatus/Projetos/ligadotattoo/ligadoAi_cous_opentracy

# 2. Instale as dependências
uv sync --extra dev

# 3. Execute os testes para garantir integridade
./.venv/bin/pytest -v

# 4. Verifique a configuração
cat config.toml
```

### Fase 1 — Bootstrap (Autenticação)

```bash
# 5. Execute o bootstrap
uv run cous --bootstrap

# Saída esperada:
# - Token Cous: ~/.cous/opentracy_token (criado)
# - Token API do agente: ~/.ligadoai/api_token (criado)
# - OpenTracy .env: ../OpenTracy/.env (atualizado)
# - Agente criado no runtime (ou já existente)
# - Canal API pronto (ou aviso se runtime offline)
```

### Fase 2 — Modo Mock (Teste Offline de Todos os Comandos)

```bash
# 6. Inicie o Cous em modo mock
uv run cous --mock
```

Dentro do terminal mock, execute:

```
# --- Comandos Gerais ---
/ajuda            # Lista todos os comandos
/status           # Mostra status dos 4 componentes
/tools            # Lista MCP tools (mock.search, mock.measurements)
/limpar
           # Limpa a tela

# --- Comandos de Chat ---
/listar           # Lista sessões (deve estar vazia)
/memoria          # Mostra a sessão atual
ola, como vai?    # Envia mensagem de chat (resposta mock)
/novo             # Cria nova sessão
/n                # Alias: cria outra sessão
/listar           # Lista — deve mostrar as sessões criadas
/carregar         # Carrega a mais recente (Enter vazio)
/memoria          # Confirma a sessão carregada
/resumo           # Gera resumo via agente mock
/novo             # Cria mais uma sessão
nova mensagem     # Envia mensagem na nova sessão (para ter conteúdo)
/resumo           # Resume a sessão atual

# --- Comandos de Knowledge ---
# Primeiro, crie um arquivo de teste (em outro terminal):
# echo "# Teste de Knowledge" > /tmp/teste_knowledge.md

/validar /tmp/teste_knowledge.md    # Deve aprovar
/indexar /tmp/teste_knowledge.md    # Deve indexar com polling
/indexados                          # Deve listar o documento
/buscar teste                       # Deve encontrar
/buscar                             # Interativo — digite "teste"
/remover                            # Interativo — digite o ID
/indexados                          # Confirma remoção

# --- Comandos de Medições ---
/medicoes                          # Lista (vazia)
/m                                 # Alias — confirma vazia

# Captura interativa:
/capturar
# Siga os prompts:
#   Fabricante [DKLAB]: FK Irons
#   Modelo: Flux
#   Numero de serie: SN123
#   Tipo de maquina [tattoo_machine]: <Enter>
#   Tipo de motor [coreless]: brushless
#   Sistema de transmissao [direct]: <Enter>
#   Curso nominal mm: 3.5
#   Curso minimo mm: 3.0
#   Curso maximo mm: 4.0
#   Tipo de coleta [desempenho]: <Enter>
#   Observacoes: teste mock
#   Tecnico responsavel: Tecnico A
#   Porta serial [/dev/ttyACM0]: <Enter>
#   Baudrate [115200]: <Enter>
#   Duracao segundos [30.0]: 5
#   Coletar hall_snapshot? [sim]: s
#   Coletar power_snapshot? [sim]: s
#   Coletar course_snapshot? [sim]: n
#   Coletar vibration_snapshot? [sim]: n
#   Cabecalho pronto. Escolha a acao [salvar]: <Enter>
#   (captura serial — mock simula snapshots)
#   Pos-captura: salvar, descartar, sair ou refazer [salvar]: <Enter>

# Captura por argumentos (modo sem serial):
/capturar fabricante=DKLAB modelo=W1PRO serie=1199 coleta=desempenho sem_serial=sim verticais=hall,power

/medicoes                         # Lista — deve mostrar as sessões
/medicoes FK                      # Filtra por "FK"
/m                                 # Alias
/medicao                          # Sem argumento — sugere a mais recente
/md                               # Alias
/medicao <id-parcial>             # Por prefixo do ID

/diagnostico                      # Sem argumento — usa a mais recente
/dg                               # Alias
/laudo                            # Gera laudo em markdown
/ld                               # Alias

/sincronizar                      # Sincroniza todas as pendentes
/sync                             # Alias
/sincronizar <id-parcial>         # Sincroniza uma específica

# Após sync — verifique os estados:
/medicoes                         # Sync deve mostrar "mock_synced"
/medicao                          # Detalhes com remote_id preenchido

# Teste de contexto de medições no chat:
qual o diagnostico da maquina W1PRO?   # Deve anexar contexto local
/sair                             # Encerra
```

### Fase 3 — Modo Real (com OpenTracy Ativo)

```bash
# 7. Inicie o Cous normalmente
uv run cous
```

Repita o mesmo fluxo da Fase 2, mas agora com:

- **Chat real** com o agente do OpenTracy
- **Knowledge real** indexando no backend
- **Medições reais** com sincronização para o runtime
- **Diagnóstico e laudo** processados remotamente

**Atenção:** A captura serial real requer:
- Máquina de tatuagem conectada via serial (ex: `/dev/ttyACM0`)
- Firmware enviando linhas `TMA_DATA {"type":"hall_snapshot",...}`

### Fase 4 — Captura Serial Real (Linux)

```bash
# 8. Conecte a máquina de tatuagem via USB
# 9. Verifique a porta serial
ls /dev/ttyACM* /dev/ttyUSB*

# 10. Inicie o Cous e capture
uv run cous
/capturar
# Preencha os dados da máquina e use a porta serial correta
# Durante a captura, o terminal mostra contagem em tempo real:
#   capturado hall=1 power=1
#   capturado hall=2 power=2
#   ...
```

### Fase 5 — Verificação de Logs e Dados Persistentes

```bash
# 11. Verifique os logs de eventos
cat .cous-data/logs/events.jsonl | python3 -m json.tool

# 12. Verifique as sessões de chat
ls -la .cous-data/conversations/
cat .cous-data/conversations/chat_*.jsonl | head -20

# 13. Verifique as medições salvas
cat .cous-data/measurements.json | python3 -m json.tool | head -50
```

---

## 14. Casos de Teste Específicos

### 14.1 Validação de Cabeçalho

| Cenário                                      | Erro Esperado                                     |
|----------------------------------------------|----------------------------------------------------|
| `tipo_coleta=reparo` sem `peca_substituida`  | `peca_substituida obrigatoria para reparo/pos-reparo` |
| `verticais` vazio                            | `selecione ao menos uma vertical`                  |
| `baudrate=0`                                 | `baudrate deve ser positivo`                       |
| `duracao_seg=0`                              | `duracao_seg deve ser positiva`                    |
| `curso_nominal=2`, `curso_min=3`, `curso_max=4` | `curso_nominal_mm deve ficar entre curso_min_mm e curso_max_mm` |
| `verticais=foo,bar`                          | `verticais invalidas: bar, foo`                    |

### 14.2 Validação de Snapshots

| Cenário                                      | Resultado         |
|----------------------------------------------|-------------------|
| Snapshot com tipo não permitido na sessão    | Rejeitado         |
| Snapshot sem campo `type`                    | Rejeitado         |
| Snapshot com `timestamp_us` negativo         | Rejeitado         |
| Snapshot apenas com `type` (sem payload)     | Rejeitado         |
| Snapshot válido                              | Aceito            |

### 14.3 Resumo Automático

| Cenário                                      | Comportamento     |
|----------------------------------------------|-------------------|
| Mensagens acumuladas < `max_chars_before_summary` | Nenhum resumo  |
| Mensagens acumuladas > `max_chars_before_summary` | Resumo gerado e persistido |

### 14.4 Recuperação de Medições no Chat (Fase C)

Com a remoção da injeção manual, o pipeline retrieve do OpenTracy é responsável por encontrar medições relevantes:

| Situação                                      | Comportamento                                    |
|-----------------------------------------------|--------------------------------------------------|
| Medição indexada no FAISS                     | Pipeline retrieve encontra automaticamente       |
| Query com termos de domínio (vibração, hall)  | Retriever ranqueia sumários de medições          |
| Medição apenas local (não sincronizada)       | Não disponível para o agente (sincronize primeiro)|

### 14.5 Sincronização

| Cenário                                            | Resultado                       |
|----------------------------------------------------|---------------------------------|
| Sessão `saved` sem `remote_id`                     | POST cria sessão + envia snaps  |
| Sessão `synced` já sincronizada                    | Ignorada no sync em lote        |
| Sessão `draft` ou `abandoned`                      | Ignorada no sync em lote        |
| Falha na chamada HTTP                              | `sync_status` = `sync_failed`   |

---

## 15. Resolução de Problemas

| Problema                                      | Solução                                          |
|-----------------------------------------------|--------------------------------------------------|
| `Token nao encontrado`                        | Execute `uv run cous --bootstrap`                |
| `Arquivo de token tem permissao 0o644`        | `chmod 0600 ~/.cous/opentracy_token`             |
| `Timeout ao comunicar com OpenTracy`          | Verifique se backend (8002) e runtime (8001) online |
| `Token ausente, invalido ou expirado` (401)   | Reexecute o bootstrap ou atualize o token        |
| `Token valido, mas sem permissao` (403)       | Verifique permissões do token no OpenTracy       |
| `Falha na captura serial`                     | Verifique porta, baudrate, permissões (dialout)  |
| `Comando desconhecido`                        | Use `/ajuda` para ver a lista                    |
| `Sessao de chat nao encontrada`               | Use `/listar` e copie o ID exato                 |

---

## 16. Comandos Rápidos de Referência

```
/ajuda | /h                    — Lista comandos
/sair | /q | /exit             — Encerra
/limpar | /cls                 — Limpa tela
/status | /st                  — Status OpenTracy
/tools                         — MCP tools

/novo | /n                     — Nova sessão chat
/listar | /ls                  — Lista sessões chat
/carregar [id] | /cg [id]      — Carrega sessão
/memoria                       — Info da sessão atual
/resumo                        — Resume conversa

/confirmar [comentário]        — Confirma resposta (promove golden, Fase E)
/corrigir <texto>              — Corrige resposta (Fase B2)
/solucao [id] <desc>           — Registra solução aplicada (Fase B2)

/validar [path]                — Valida doc
/indexar <path>                — Indexa doc
/indexados                     — Lista docs
/buscar [query]                — Busca knowledge
/remover [id]                  — Remove doc

/capturar | /cp                — Nova medição (interativo ou args)
/medicoes [filtro] | /m [f]    — Lista medições
/medicao [id] | /md [id]       — Detalhes medição
/sincronizar [id] | /sync [id] — Sincroniza medições
/diagnostico [id] | /dg [id]   — Diagnóstico
/laudo [id] | /ld [id]         — Laudo markdown
```

---

## 17. Executando a Suíte de Testes

```bash
cd /home/hiatus/Projetos/ligadotattoo/ligadoAi_cous_opentracy
./.venv/bin/pytest -v
```

A suíte cobre:
- Autenticação e tokens (env vs arquivo, permissões)
- Bootstrap (criação de token, atualização de .env, rotação de API token)
- Event Logger (JSONL)
- Comandos (router, parsing de cabeçalho, aliases, validação)
- Serial capture (parsing TMA_DATA, filtragem, normalização)
- Measurement client (CRUD, filtro, relatório, sync, diagnose, report)
- Chat sessions (persistência, carga, resolução de prefixo, resumo)
- Resumo automático (gatilho por tamanho)

---

## 18. Checklist de Verificação Completa

Use esta checklist para garantir que todas as funcionalidades foram testadas:

- [ ] Bootstrap executa sem erros (tokens criados, .env atualizado)
- [ ] Modo `--mock` inicia sem exigir OpenTracy
- [ ] `/ajuda` lista todos os comandos
- [ ] `/status` mostra 4 verticais (backend, runtime, knowledge, measurements)
- [ ] `/tools` lista MCP tools
- [ ] `/limpar` limpa a tela
- [ ] Chat: mensagem de texto livre recebe resposta do agente
- [ ] `/novo` cria nova sessão
- [ ] `/listar` lista sessões com metadados corretos
- [ ] `/carregar` carrega por prefixo e por vazio (mais recente)
- [ ] `/memoria` mostra stats da sessão atual
- [ ] `/resumo` gera e persiste resumo
- [ ] Resumo automático dispara quando acima do threshold
- [ ] `/validar` aprova/rejeita arquivos corretamente
- [ ] `/indexar` indexa com polling e mostra status
- [ ] `/indexados` lista documentos
- [ ] `/buscar` retorna resultados com scores
- [ ] `/remover` remove documento
- [ ] `/capturar` interativo — preenche todos os campos
- [ ] `/capturar` por argumentos — aceita aliases
- [ ] Validação de cabeçalho rejeita casos inválidos
- [ ] `/capturar sem_serial=sim` funciona sem porta serial
- [ ] Snapshots inválidos são rejeitados e contabilizados
- [ ] `/medicoes` lista com filtro
- [ ] `/medicao` mostra detalhes completos
- [ ] `/sincronizar` (individual e lote)
- [ ] `/diagnostico` remoto com fallback local
- [ ] `/laudo` remoto com fallback local, markdown renderizado
- [ ] Contexto de medições anexado ao chat em consultas relevantes
- [ ] Logs JSONL gravados com eventos corretos
- [ ] Dados persistidos em `.cous-data/` sobrevivem a reinicializações
- [ ] `/sair` encerra o programa
- [ ] `pytest` passa sem falhas
- [ ] System prompt é carregado do runtime e injetado no chat (Fase A)
- [ ] `/confirmar` registra feedback e promove trace a golden (Fases B2 + E)
- [ ] `/corrigir` registra correção no FeedbackStore (Fase B2)
- [ ] `/solucao` registra solução aplicada (Fase B2)
- [ ] Traces são emitidos em `.cous-data/logs/traces.jsonl` após cada chat (Fase D)
- [ ] Medições são indexadas automaticamente no FAISS após `/capturar` (Fase B)
- [ ] Pipeline retrieve encontra medições sem injeção manual (Fase C)
- [ ] FeedbackStore persiste em `.cous-data/feedback/records.jsonl`
