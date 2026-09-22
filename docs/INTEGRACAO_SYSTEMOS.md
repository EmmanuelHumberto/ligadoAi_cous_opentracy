# Integracao SystemOS

O COUS envia ao SystemOS todos os snapshots salvos que possuem `ordem_servico` no cabecalho.
A entrega ocorre alem da sincronizacao com o OpenTracy: uma falha em um destino nao apaga nem
desfaz o resultado confirmado pelo outro.

## Configuracao

```toml
[systemos]
enabled = true
base_url = "http://192.168.15.182:3001/api/v1"
organization_id = "uuid-da-organizacao"
api_key_env_var = "COUS_SYSTEMOS_TDMA_KEY"
api_key_file = "~/.cous/systemos_tdma_key"
timeout = 30
```

A chave e lida primeiro da variavel de ambiente e, na ausencia dela, do arquivo privado. O arquivo
deve ter permissao `600` e nao deve ser versionado.

Sessoes maiores sao divididas em lotes de 50 frames. As chaves
`cous:<sessao>:<indice-do-lote>` permitem repetir a sincronizacao sem duplicar registros. O recibo e
salvo em `systemos_sync_receipt`; erros ficam em `last_systemos_sync_error` para nova tentativa com
`/sincronizar`.
