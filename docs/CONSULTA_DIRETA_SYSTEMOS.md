# Consultar uma OS diretamente no SystemOS

Reabra o Cous e execute:

```text
/diagnostico os 1141
```

`/diagnostico 1141` e um atalho. Para UUID, use `/diagnostico os <UUID>`.
O comando envia somente a identidade ao runtime OpenTracy. O runtime le os
registros salvos no SystemOS por credencial propria, processa correlacoes V4 e
usa a rota configurada `qwen3.5:4b` no Ollama do Windows, pelo tunel 11436.
Nao e necessario indexar a OS ou criar captura/fila de diagnostico para essa consulta.
O pipeline pode consultar conhecimento tecnico e preservar traces de execucao.

A conclusao e validada pelo SystemOS antes de ser exibida. Se a OS mudou
durante a inferencia, a resposta e recusada para evitar apresentar texto antigo.
Nada e aplicado a OS. Rascunhos nao salvos e conteudo visual dos anexos nao sao incluidos.
Os servicos sugeridos sao os registrados na OS, sem inventar execucao ou conformidade.

`/diagnostico <id de coleta>` conserva o fluxo de captura anterior.
O chat usa token do gateway; a consulta usa token knowledge/V3, separados na composicao.

Na configuracao local `config.toml`, `[opentracy] chat_timeout = 900` permite
aguardar a inferencia por CPU. O runtime precisa ter as variaveis
`OPENTRACY_SYSTEMOS_URL`, `OPENTRACY_SYSTEMOS_READ_KEY` e
`OPENTRACY_SYSTEMOS_ORGANIZATION_ID`. Nao coloque credenciais no Git.
As credenciais ja foram instaladas neste ambiente. Mantenha o tunel e o Ollama ativos.

Validacao real OS 1141: tres coletas/42 frames, modelo qwen3.5:4b no Windows por CPU, 443,32 segundos, conclusao validada sem descarte de paragrafos. Nenhuma alteracao na OS e nenhuma nova entrada em documentos/capturas/fila do OpenTracy. O resultado integra a conversa local para perguntas seguintes, com trace de rastreabilidade.
