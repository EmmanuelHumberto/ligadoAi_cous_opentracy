# Integracao Serial para API Cloud

## Objetivo

Enviar medicoes do firmware para o sistema de OS hospedado na nuvem sem
reescrever o firmware, o Cous, o portal ou o OpenTracy e sem instalar um banco
de dados local.

O sistema de OS web e o componente principal. Ele captura a serial localmente,
abre a sessao da ordem de servico, analisa os dados, produz o diagnostico e
envia o resultado ao portal.

```text
ESP32/firmware --USB serial--> conector local do OS web
                                  |
                                  v
                         Sistema de OS web/cloud
                                  |
                         analise e diagnostico
                                  |
                                  v
                       API de ingestao do portal
```

O firmware nao acessa a internet nem o banco remoto. Ele mantem a publicacao
serial `TMA_DATA`; o OS web valida, organiza e transmite os resultados.

## Escopo da primeira versao

Incluido:

- leitura da saida serial ja existente;
- preservacao do payload bruto recebido do firmware;
- criacao de uma sessao de medicao;
- armazenamento temporario em JSON/JSONL;
- fila de registros pendentes;
- envio HTTPS para a API do sistema de OS;
- autenticacao por Bearer token;
- `Idempotency-Key` para impedir duplicidade;
- retentativas com backoff;
- confirmacao local de envio;
- operacao offline ate a conexao retornar;
- logs de transporte sem dados sensiveis.

Fora da primeira versao:

- banco local;
- alteracao do contrato serial do firmware;
- comunicacao direta do ESP32 com a internet;
- diagnostico fora do contexto de uma ordem de servico;
- sincronizacao completa com OpenTracy;
- alteracao automatica da ficha tecnica do portal sem revisao humana.

## Uso do Cous como referencia

O Cous nao sera o sistema principal da integracao. Seus componentes podem ser reaproveitados como referencia de contratos e comportamento:

- `cous/measurements/serial_capture.py`: captura da porta serial;
- `cous/measurements/validation.py`: validacao dos dados;
- `cous/measurements/store.py`: persistencia local;
- `cous/clients/measurements.py`: cliente HTTP de medicoes;
- `cous/config.py`: configuracao do ambiente;
- `cous/measurements/analysis.py`: analises locais ja disponiveis.

O conector serial do OS web deve reutilizar a mesma semantica de `TMA_DATA`,
validacao e classificacao de grandezas. Nao deve haver um segundo formato de
medicao incompativel com o firmware.

## Contratos HTTP minimos

```http
POST /api/v1/portal/technical-evidence
Authorization: Bearer <token>
Content-Type: application/json
Idempotency-Key: <session_id>
```

Exemplo de corpo:

```json
{
  "schema": "tma.measurement.v1",
  "session_id": "capture-20260909-0001",
  "work_order_id": "OS-2026-00125",
  "machine": {"serial": "MAQ-001", "model": "W1PRO"},
  "source": {
    "type": "firmware_serial",
    "device_id": "esp32s3-001",
    "firmware_version": "1.0.0"
  },
  "observations": [],
  "quality": {"valid": true, "missing": [], "inferred": []},
  "captured_at": "2026-09-09T14:30:00Z",
  "raw_tma_data": []
}
```

O servidor deve responder com `201 Created` ou `200 OK`. Uma repeticao com a
mesma chave deve retornar a sessao ja existente, sem criar uma segunda medicao.

| HTTP | Tratamento local |
|---|---|
| `200`/`201` | marcar como enviado |
| `400`/`422` | preservar como erro de validacao |
| `401`/`403` | interromper envio e solicitar novo token |
| `408`/`429` | aguardar e tentar novamente |
| `5xx` ou sem conexao | manter pendente e aplicar backoff |

## Fila local sem banco

```text
.os-web-data/serial-sync/
  pending/
  sending/
  sent/
  failed/
  state.json
```

Cada sessao deve ser gravada atomicamente em `pending/`. O envio move o arquivo
para `sending/`, executa a requisicao e entao move para `sent/` ou `failed/`.
O processo deve suportar reinicio sem perder ou duplicar sessoes.

O `state.json` deve conter apenas controle operacional: ultimo envio, tentativas
e ultima falha. Os dados da medicao permanecem nos arquivos individuais.

## Configuracao prevista

```toml
[os_portal_sync]
enabled = false
base_url = "https://os.example.com"
measurements_path = "/api/v1/measurement-sessions"
token_env = "OS_PORTAL_API_TOKEN"
spool_dir = ".os-web-data/serial-sync"
connect_timeout_seconds = 5
request_timeout_seconds = 30
max_attempts = 8
backoff_seconds = 5
verify_tls = true
```

Com `enabled = false`, o OS web continua funcionando com armazenamento local
e fila pendente. Quando ativado, o resultado e enviado ao portal por HTTPS.

## Pre-requisitos locais

- Debian 13 ou ambiente Linux compativel;
- Python 3.11 ou superior;
- `uv` instalado;
- dependencias instaladas com `uv sync --extra dev`;
- permissao de leitura da porta serial;
- ESP32 conectado, normalmente `/dev/ttyACM0`;
- firmware emitindo linhas `TMA_DATA` validas;
- relogio sincronizado;
- acesso HTTPS de saida;
- `OS_PORTAL_API_TOKEN` configurado somente no ambiente local;
- diretorio `.cous-data` com permissao de escrita.

Nao e necessario instalar PostgreSQL, Redis, ClickHouse, OpenTracy ou MinIO
para a captura e o envio basico.

## Pre-requisitos cloud

- API HTTPS acessivel publicamente ou por VPN;
- endpoint de ingestao de medicoes;
- autenticacao por token ou OIDC service account;
- validacao do contrato `tma.measurement.v1`;
- suporte a `Idempotency-Key`;
- persistencia da sessao e do payload bruto;
- indice unico para `source + session_id`;
- resposta explicita para aceito, rejeitado e duplicado;
- logs, metricas e politica de retencao;
- ambiente de teste separado da producao.

O banco cloud deve ficar atras das APIs do OS e do portal. O navegador e o
firmware nunca recebem credenciais do banco.

## Sequencia de validacao

1. Testar o parser com linhas `TMA_DATA` gravadas, sem hardware.
2. Criar uma sessao local e verificar o JSON produzido.
3. Simular respostas `201`, `422`, `401`, `429` e `500`.
4. Confirmar retentativa e movimentacao dos arquivos da fila.
5. Reenviar a mesma sessao e verificar idempotencia.
6. Desconectar a rede e confirmar que nada e perdido.
7. Conectar o ESP32 e executar uma coleta real.
8. Confirmar a sessao na API cloud e na ordem de servico.
9. Testar troca de token e expiracao.
10. Fazer backup e restauracao de `.os-web-data/serial-sync`.

## Envio para o portal

Depois da analise e do diagnostico no sistema de OS, o resultado deve ser enviado
ao processo de ingestao ja existente no portal:

- comparacao entre medicoes;
- historico de desempenho;
- defeitos observados;
- alteracoes de componentes;
