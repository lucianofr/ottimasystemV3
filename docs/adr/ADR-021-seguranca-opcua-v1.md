# ADR-021 — Segurança OPC-UA: anônimo, usuário/senha e certificado desde a v1

**Status:** Aceito · 2026-08-03

## Contexto
Os servidores-alvo variam (gateways, servidores embarcados); o nível de segurança deve ser escolha do usuário por conexão.

## Decisão
Configuração **por conexão**:
- **SecurityPolicy/Mode:** None · Basic256Sha256 (Sign) · Basic256Sha256 (SignAndEncrypt);
- **Autenticação:** anônimo · usuário/senha · **certificado X.509** — tudo disponível **desde a v1**.
- O sistema gerencia seu certificado de instância de aplicação (gera autoassinado, exporta para trust list do servidor) e permite importar/confiar no certificado do servidor.

## Consequências
- asyncua cobre os três modos; a complexidade fica no formulário de conexão + gestão de certificados (par de chaves em volume persistente).
- Segredos (senhas/chaves) nunca saem no export de projeto (ADR-012): re-informados no import.
