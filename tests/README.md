# tests/ — integração cross-service

- `e2e/`: camada L2 do gate da F1 (`docs/specs/F1-testes-e2e.md`) — roda contra o stack
  `docker compose` real, marker `e2e` (fora do `uv run pytest` default).
  Uso: `E2E_BASE_URL=http://localhost:8080 E2E_ADMIN_USERNAME=... E2E_ADMIN_PASSWORD=... uv run pytest -m e2e tests/e2e -v`
- O banco do stack é persistente: os testes usam sufixo único por execução, toleram 409 nas
  fixtures recriadas e excluem o que criam — rodar a suíte duas vezes seguidas dá verde nas duas.
- A partir da F4, este diretório recebe a suíte de malha fechada MPC↔TFS (RNF-09).
