# ADR-023 — Escopo de plataforma da v1: pt-BR, auth local, HTTP interno, Compose on-prem

**Status:** Aceito · 2026-08-03

## Decisão
- **UI somente pt-BR** (sem i18n).
- **Autenticação local por usuário e senha** (hash Argon2/bcrypt + JWT). Sem AD/LDAP.
- **HTTP** na rede interna da planta é suficiente (sem TLS na v1).
- **Deploy: Docker Compose em um servidor Linux on-prem** (serviços: frontend, api, opc-worker, flow-runtime, recorder, redis, timescaledb).

## Consequências
- (+) Zero dependência de infraestrutura corporativa (IdP, PKI web) para instalar numa planta.
- TLS/LDAP ficam como evolução sem impacto arquitetural (proxy/keycloak podem ser adicionados depois).
