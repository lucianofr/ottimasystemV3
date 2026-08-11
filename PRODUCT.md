# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Stack

Decidida e aprovada nos ADR-001…006 (normativos, `docs/adr/`): React + Vite + shadcn/ui + React Flow (@xyflow/react) + uPlot no frontend · FastAPI + SQLAlchemy 2.0 async · PostgreSQL + TimescaleDB · Redis pub/sub · workers asyncio dedicados (opc-worker, flow-runtime, recorder) · `uv` · Docker Compose on-prem (ADR-023). Sem Celery.

## Users

- **Admin (engenheiro de processos/APC):** monta estratégias de controle avançado num canvas de blocos, configura conexões OPC-UA, tags e MPCs, faz deploy de flows e comissiona malhas. Trabalha em estação de engenharia (desktop).
- **Operador (operador de painel):** conduz o MPC pela tela de operação — modos LOCAL/REMOTO e MAN/AUTO, escrita de SP e de MV em MAN — em sala de controle 24/7, por turnos, em monitores grandes com leitura à distância. Enxerga tudo; não edita engenharia.

Papéis e capacidades fixados no ADR-015 (RBAC admin/operador).

## Product Purpose

OttimaSystem é uma plataforma on-premise de Controle Avançado de Processos (APC) com MPC: o engenheiro desenha a lógica em um canvas de blocos (OPC-Read/Write, MPC, Python-Script, TFS), o motor executa ciclicamente no servidor (scan cycle), e o operador conduz o MPC por faceplates e tendência com predição futura. O controle regulatório permanece nos PIDs do PLC; o sistema assume e devolve malhas de forma bumpless e falha sempre para o lado seguro (PLC no comando).

v1 é uma reescrita completa do zero do sistema legado (Django), sem compatibilidade retroativa. Sucesso = as 6 fases do PRD aceitas, culminando em malha fechada MPC↔TFS verde e operador conduzindo LOCAL/REMOTO/MAN/AUTO com predição sobreposta ao histórico.

## Positioning

**Produto multi-cliente:** plataforma que a LFR Automação implanta em plantas de clientes diversos — deve se comportar como produto comercial, não sistema sob medida. Mecanismo diferenciado: APC completo (canvas de estratégia + MPC do-mpc + operação com predição) instalável numa planta com um único `docker compose up`, sem nenhuma dependência de infraestrutura corporativa (sem IdP, sem PKI, sem cloud). Segurança de processo por construção: watchdog de bit alternante, transferência bumpless nos dois sentidos e boot que nunca reassume malhas sozinho.

## Operating Context

- Rede interna de planta industrial, HTTP, servidor Linux único on-prem (4 vCPU de referência).
- Sala de controle 24/7 por turnos (operação) + estação de engenharia desktop (edição/comissionamento). Sem uso mobile na v1.
- Integra com PLCs/DCS via OPC-UA (≤5 servidores, ~100 tags); modos de PID RCAS/CAS/ROUT; pré-requisito de SP/OUT-tracking configurado no PID do PLC.
- Dimensionamento-alvo: ~10 flows simultâneos, retenção de histórico de 1 mês.
- Documentos normativos: `docs/PRD.md` (aprovado), `docs/adr/ADR-001…023` (prevalecem sobre o PRD em conflito), `docs/GLOSSARY.md`.

## Capabilities and Constraints

- Capacidades v1: auth local + RBAC; CRUD de projetos (1 ativo), conexões OPC-UA com 3 modos de segurança e certificados X.509, tags; editor de flows com 5 blocos e hot-swap; motor scan-cycle asyncio; MPC (SOPDT/IOPDT, TSS→Np/Nc derivados, restrições com precedência sobre CVs, multiplicador de execução, orçamento de solver 70%); tela de operação (faceplates + tendência uPlot com overlay de predição); eventos/auditoria com banner de alarmes sem ACK; export/import JSON sem segredos.
- Não-objetivos v1 (não inventar): versionamento de flows, ACK de alarmes, ideal resting values, identificação de modelos, AD/LDAP, HTTPS, i18n, multi-projeto ativo, histórico > 1 mês, app mobile, relatórios.
- **UI 100% pt-BR** (ADR-023). Terminologia fixada pelo `docs/GLOSSARY.md` (MV/CV/SP/DV, LOCAL/REMOTO, MAN/AUTO, deploy, faceplate, predição…) — não renomear conceitos.
- Invariantes de segurança: nenhuma escrita em planta sem flow em deploy + watchdog vivo + REMOTO; falha de comunicação cessa escritas e para o flow (watchdog é por flow, não por conexão); retomada exige deploy manual.
- UI orientada a estado publicado: reflete o barramento, nunca eco de comando.

## Brand Commitments

- Nome do produto: **OttimaSystem**.
- **Identidade visual própria de produto** (decisão do usuário, 2026-08-03): OttimaSystem não segue a identidade da LFR Automação; LFR aparece no máximo como assinatura/rodapé ("by LFR Automação").
- **Mundo visual comprometido** (2026-08-03): direção "Console OttimaSystem" aprovada e registrada em `DESIGN.md` (seed; normativo para SPECs/planos). Logo do produto ainda não existe.

## Evidence on Hand

- `docs/PRD.md` — PRD v1.0 aprovado (2026-08-03).
- `docs/adr/` — 23 ADRs normativos.
- `docs/GLOSSARY.md` — vocabulário do domínio.
- Existe um sistema legado em Django (antecessor funcional), sem compromisso de compatibilidade; nenhum screenshot ou asset dele no repositório.
- **Ausências a não fabricar:** não há logos de clientes, depoimentos, casos, benchmarks públicos, preços ou material de marketing no repositório.

## Product Principles

1. **Falhar para o lado seguro é inegociável:** qualquer dúvida resolve-se devolvendo o comando ao PLC; o sistema nunca reassume sozinho.
2. **Estado publicado é a única verdade:** toda superfície reflete o que o barramento publicou; comandos são intenção, nunca confirmação.
3. **Operação e engenharia são mundos distintos:** o operador de turno precisa de clareza à distância e ação em 1 gesto; o engenheiro precisa de densidade e precisão de configuração.
4. **Vocabulário APC canônico em pt-BR:** o glossário governa nomes na UI; não traduzir nem apelidar termos consagrados (SP, MV, CV, RCAS, bumpless).
5. **Produto instalável, não projeto:** tudo deve funcionar em qualquer planta com `docker compose up` — zero suposições sobre infraestrutura do cliente.

## Accessibility & Inclusion

Operação em sala de controle 24/7: legibilidade à distância em monitores grandes, turnos longos (fadiga visual), estados de alarme distinguíveis sem depender apenas de cor. Nenhum padrão formal (WCAG/ISA) foi exigido pelo usuário até agora — registrar como decisão em aberto se um cliente exigir.
