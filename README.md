# Cous OpenTracy

Cliente terminal fino para o OpenTracy.

> 📄 **Documento de arquitetura do ecossistema:** [`docs/ARQUITETURA.md`](docs/ARQUITETURA.md) — define OpenTracy como motor cognitivo e Cous como interface operacional especializada.

Este repositório substitui o Cous legado. O legado em
`../opentracy-terminal-chat` deve ser usado apenas como referência de UX e
contratos, nunca como base de código.

## Escopo

O novo Cous faz:

- terminal interativo com Rich;
- autenticação por token Bearer;
- chat com o agente via backend do OpenTracy;
- persistência local de sessões de chat em JSONL;
- resumo manual e automático de conversa;
- logs JSONL de eventos do terminal;
- comandos de knowledge (`/indexar`, `/buscar`, `/validar`, `/status`);
- captura, persistência local e sincronização de medições.

O novo Cous não faz:

- PostgreSQL direto de knowledge;
- embeddings;
- FAISS;
- OCR;
- conversão de documentos;
- chunking;
- reload manual de corpus.

## Estrutura local

Por padrão o cliente grava dados em `.cous-data/`:

- `.cous-data/conversations/<session_id>.jsonl`
  - sessão de chat persistida;
  - eventos `meta`, `message`, `summary` e `reset`;
  - `summary` é usado como contexto comprimido nas próximas chamadas ao agente.
- `.cous-data/measurements.json`
  - store local de medições antes ou depois da sincronização remota.

## Requisitos

- Python 3.11+
- `uv`
- OpenTracy backend em `http://127.0.0.1:8002`
- OpenTracy runtime em `http://127.0.0.1:8001`
- token de knowledge do OpenTracy
- token de API do agente

Para captura serial:

- Linux ou outro sistema compatível com `termios`
- porta serial acessível, por exemplo `/dev/ttyACM0`

Observação:

- `cous/measurements/serial_capture.py` usa `termios` e `select`;
- hoje a captura serial deve ser tratada como Linux-only.

## Instalação

```bash
uv sync --extra dev
```

## Bootstrap

O bootstrap agora cobre o token de knowledge, o token de medições e o canal API do agente:

```bash
uv run cous --bootstrap
```

Isso:

- cria `~/.cous/opentracy_token` se ele não existir;
- aplica permissão `0600`;
- grava o mesmo valor em `../OpenTracy/.env` como `OPENTRACY_KNOWLEDGE_AUTH_TOKEN`;
- grava o mesmo valor em `../OpenTracy/.env` como `OPENTRACY_MEASUREMENTS_AUTH_TOKEN`;
- tenta garantir a existência do agente configurado em `opentracy.agent_id`;
- tenta conectar o canal API em `POST /agents/<agent_id>/channels/api/connect`;
- quando o runtime devolve um token `ot_*`, salva esse token em `~/.ligadoai/api_token`.

Depois do bootstrap, reinicie o runtime do OpenTracy.

## Configuração

O cliente procura `config.toml` no diretório atual ou na raiz do repositório.

Copie `config.example.toml` para `config.toml` e ajuste os valores conforme o
seu ambiente.

Exemplo:

```toml
[opentracy]
backend_url = "http://127.0.0.1:8002"
runtime_url = "http://127.0.0.1:8001"
agent_id = "cous"
timeout = 30

[auth]
token_file = "~/.cous/opentracy_token"
env_var = "COUS_OPENTRACY_TOKEN"
api_token_file = "~/.ligadoai/api_token"
api_env_var = "COUS_OPENTRACY_API_TOKEN"
opentracy_env_file = "../OpenTracy/.env"
opentracy_env_key = "OPENTRACY_KNOWLEDGE_AUTH_TOKEN"

[memory]
max_history = 10
max_chars_before_summary = 16000

[chat]
conversations_dir = ".cous-data/conversations"

[mcp]
timeout_seconds = 30
max_restarts = 3
restart_backoff_seconds = 5

[logs]
events_file = ".cous-data/logs/events.jsonl"

[measurements]
storage_file = ".cous-data/measurements.json"
```

Parâmetros relevantes:

- `memory.max_history`
  - quantidade de mensagens recentes enviadas ao agente, além do resumo persistido.
- `memory.max_chars_before_summary`
  - quando o conteúdo ainda não resumido ultrapassa esse limite, o Cous gera um resumo automático e o persiste na sessão.
- `chat.conversations_dir`
  - diretório dos arquivos JSONL de conversa.
- `measurements.storage_file`
  - store local de medições.
- `mcp.*`
  - reserva a configuração operacional do cliente para integrações MCP.
- `logs.events_file`
  - arquivo JSONL onde o terminal grava eventos de sessão, comandos, chat e resumo.

## Execução

```bash
uv run cous
```

Parâmetros disponíveis:

- `--bootstrap`
  - prepara o token de knowledge.
- `--config <arquivo.toml>`
  - usa um arquivo de configuração específico.
- `--mock`
  - usa clientes fake locais para chat, knowledge e medições;
  - não exige tokens nem OpenTracy ativo;
  - útil para validar UX do terminal e fluxo local.

## Testes

Execução padrão:

```bash
uv run pytest
```

Testes de integração do terminal:

```bash
uv run pytest -m terminal -s
```

Em CI headless, exclua os testes marcados como `terminal`:

```bash
uv run pytest -m "not terminal"
```

## Sessões de chat

Ao iniciar, o Cous:

- tenta reabrir a sessão de chat mais recente em `conversations/`;
- se não houver nenhuma, cria uma nova.

Cada sessão recebe um ID como:

```text
chat_20260609_104530_ab12cd
```

Comandos de sessão de chat:

- `/novo`
  - cria uma nova sessão de chat persistida;
  - troca a sessão corrente.
- `/listar`
  - lista as sessões de chat persistidas.
- `/carregar <id-ou-prefixo>`
  - carrega uma sessão de chat existente;
  - aceita prefixo único.
- `/memoria`
  - mostra a sessão corrente, número de mensagens e se já existe resumo persistido.
- `/resumo`
  - pede ao agente um resumo técnico da conversa atual;
  - salva esse resumo na própria sessão JSONL.
- `/deletar_chat <id-ou-prefixo>`
  - remove permanentemente uma sessão de chat do disco;
  - exige confirmação interativa;
  - não permite deletar a sessão ativa;
  - reporta erro se o prefixo for ambíguo.
- `/exportar [id]`
  - exporta a sessão como arquivo Markdown em `.cous-data/exports/`;
  - sem argumento, exporta a sessão atual.

Resumo automático:

- depois de cada resposta do agente, o cliente mede o conteúdo ainda não resumido;
- se passar de `max_chars_before_summary`, gera um resumo automático;
- esse resumo volta como mensagem comprimida de contexto nas próximas chamadas.

## Comandos de knowledge

- `/status`
  - mostra backend, runtime, knowledge API e measurements API.
- `/tools`
  - lista MCP tools expostas pelo backend do agente.
- `/validar`
  - valida arquivo ou pasta para knowledge;
  - se não receber argumento, pergunta interativamente.
- `/indexar <arquivo|pasta>`
  - cria jobs de ingestão no OpenTracy;
  - faz polling até terminal status.
- `/indexados`
  - lista documentos indexados.
- `/buscar`
  - busca na base de conhecimento;
  - se não receber argumento, pergunta interativamente.
- `/remover <document_id>`
  - remove documento indexado;
  - se não receber argumento, pergunta interativamente.

## Medições

Fluxo principal:

1. `/capturar`
2. preencher cabeçalho
3. capturar snapshots TMA_DATA
4. escolher `salvar`, `descartar`, `sair` ou `refazer`
5. sincronizar com o runtime de medições

Comandos:

- `/capturar`
  - cria uma sessão local de medição;
  - captura serial se `sem_serial` não estiver ativo;
  - valida snapshots antes de persistir.
- `/medicoes [filtro]`
  - lista sessões de medição locais.
- `/medicao <id-ou-prefixo>`
  - mostra detalhes da sessão;
  - sem argumento, sugere a sessão mais recente e permite confirmar ou trocar.
- `/sincronizar [id]`
  - envia sessões salvas para o runtime de medições do OpenTracy;
  - sem argumento, sincroniza as pendentes.
- `/diagnostico [id]`
  - prefere o backend remoto quando a sessão já tiver `remote_id`;
  - cai para modo local se o runtime falhar;
  - sem argumento, sugere a sessão mais recente.
- `/laudo [id]`
  - mesmo comportamento do diagnóstico;
  - prefere laudo remoto, com fallback local;
  - sem argumento, sugere a sessão mais recente.

Validação antes de persistir:

- o cliente valida o cabeçalho antes de criar a sessão;
- `peca_substituida` é obrigatória em `reparo` e `pos-reparo`;
- `verticais` não pode ficar vazia;
- `baudrate` e `duracao_seg` devem ser positivos;
- quando os três valores de curso existem, `curso_nominal_mm` deve ficar entre `curso_min_mm` e `curso_max_mm`;
- snapshots são filtrados antes de salvar localmente e snapshots inválidos são contabilizados como rejeitados;
- o backend remoto repete a validação do cabeçalho e rejeita payload inválido com HTTP `422`.

Descoberta de coletas no chat:

- quando a pergunta mencionar coleta, medição, laudo, diagnóstico, máquina, snapshot ou termos próximos, o Cous anexa um contexto local com as medições mais relevantes;
- se não houver match textual exato, ele usa as sessões recentes como fallback;
- isso evita o caso em que a coleta foi salva localmente mas o agente responde como se não existisse.

Estados de sincronização:

- `local_only`
  - sessão ainda não sincronizada.
- `synced`
  - sessão sincronizada com o backend remoto.
- `sync_failed`
  - tentativa remota falhou; a sessão continua preservada localmente.

## Integração com o OpenTracy

O chat usa:

- backend HTTP do OpenTracy em `backend_url`
- endpoint `/v1/api/<agent_id>/chat`

As medições usam:

- runtime HTTP do OpenTracy em `runtime_url`
- endpoint `/measurements/status`
- endpoint `/measurements/sessions`

## Higiene de repositório

Arquivos operacionais e artefatos locais não devem ser versionados:

- `.cous-data/`
- `.run/`
- `*.backup`

O objetivo é manter no Git apenas código, testes, documentação e arquivos de configuração que realmente fazem parte do produto.

## Logs de eventos

O terminal grava eventos JSONL em `logs.events_file`.

Exemplos de eventos:

- `startup`
- `terminal_ready`
- `command_dispatch`
- `chat_user`
- `chat_assistant`
- `chat_error`
- `summary_updated`

Isso preserva um histórico técnico local sem depender do runtime do OpenTracy.

O comando `/status` já mostra se a vertical de medições está em:

- `memory`
- `postgres`

e se o runtime está com:

- `db=sim|nao`
- `auth=sim|nao`

## Observações de design

- O cliente injeta contexto local de medições no `request_text` do chat quando encontra termos relevantes.
- Isso é deliberado para o MVP e evita depender de uma vertical de RAG específica para medições.
- Quando houver uma camada mais rica de recuperação para medições, esse acoplamento pode ser revisado.

## Testes

Rodar a suíte local do Cous:

```bash
./.venv/bin/pytest
```

## Estado atual

Implementado:

- autenticação com dois tokens;
- bootstrap do token de knowledge, do token de medições e do canal API do agente;
- `--mock` com clientes fake locais;
- store local de medições;
- sincronização para o runtime remoto de medições;
- diagnóstico e laudo com preferência por backend remoto;
- sessões de chat persistidas em JSONL;
- `/novo`, `/listar`, `/carregar` para chat;
- `/resumo` manual;
- resumo automático por tamanho;
- logs JSONL de eventos do terminal;
- configuração `[mcp]` e `[logs]` específicas no cliente.

Ainda em aberto:

- a captura serial segue Linux-only por usar `termios`/`select`.
