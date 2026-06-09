# Cous OpenTracy

Cliente terminal fino para o OpenTracy.

Este repositorio substitui o Cous legado. O legado em
`../opentracy-terminal-chat` deve ser usado apenas como referencia de UX e
contratos, nunca como base de codigo.

## Responsabilidades

- Interface terminal.
- Sessao local.
- Cliente HTTP autenticado para OpenTracy.
- Comandos de conhecimento via `/knowledge/*`.
- Persistencia local de medicoes em `.cous-data/measurements.json`.

## Fora do escopo

- PostgreSQL direto.
- Embeddings.
- FAISS.
- OCR.
- Conversao de documentos.
- Chunking.
- Reload manual de corpus.

## Bootstrap local

```bash
uv run cous --bootstrap
```

Esse comando cria o token local do Cous e grava o mesmo valor em
`../OpenTracy/.env` como `OPENTRACY_KNOWLEDGE_AUTH_TOKEN`.

Depois reinicie o runtime do OpenTracy para carregar o `.env`.
