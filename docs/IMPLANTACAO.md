# Guia de implantação — OttimaSystem v1

Público-alvo: o engenheiro de APC que implanta o OttimaSystem numa planta de cliente —
sobe o stack, comissiona as malhas e mantém a instalação em operação. Este guia é
**operacional**: descreve como colocar o sistema no ar e mantê-lo, com cada passo
ancorado no requisito ou na decisão de arquitetura que o governa. O que o sistema **é**
— contratos, schemas, comportamento normativo — está em `docs/PRD.md` e nos
`docs/adr/ADR-001…024`; este documento não repete o que já está lá, só aponta.

Vocabulário: **arquivo de projeto** é o JSON de export/import (projeto + conexões +
tags + flows, sem dados históricos). "Bundle" é nome interno de código
(`ProjectImportIn.bundle`) e não aparece em nenhuma tela.

## 1. Instalação e primeiro boot

**Pré-requisitos de host:** Linux on-prem com Docker Engine e o plugin Compose v2
(comando `docker compose`, não o binário legado `docker-compose`) — o
`deploy/docker-compose.yml` usa `depends_on: condition: service_healthy`, recurso do
Compose V2 (ADR-023). Porta HTTP única liberada para a rede da planta (padrão 80,
variável `OTTIMA_HTTP_PORT`) — é a única porta publicada; os demais serviços conversam
só na rede interna do compose. Como referência de dimensionamento do host: os testes de
carga usam 4 vCPU como hardware de referência para o orçamento do solver do MPC
(RNF-02).

**Configuração (`deploy/.env`):** copie `deploy/.env.example` para `deploy/.env` e
preencha. Variáveis obrigatórias:

| Variável | Função |
|---|---|
| `OTTIMA_HTTP_PORT` | porta única publicada pelo frontend/nginx |
| `POSTGRES_DB`/`POSTGRES_USER`/`POSTGRES_PASSWORD` | credenciais do container `timescaledb` |
| `OTTIMA_SECRET_KEY` | segredo do JWT de sessão (RNF-04) |
| `OTTIMA_FERNET_KEY` | chave de cifra dos segredos de conexão OPC (senhas), spec F1 §5.4 |
| `OTTIMA_TOKEN_TTL_HOURS` | validade do token de sessão, em horas |
| `OTTIMA_ADMIN_USERNAME`/`OTTIMA_ADMIN_PASSWORD`/`OTTIMA_ADMIN_NAME` | admin criado no primeiro boot (seed, só com a tabela `users` vazia) |
| `OTTIMA_LOG_LEVEL` | nível de log dos 4 serviços Python |

`OTTIMA_SECRET_KEY` e `OTTIMA_FERNET_KEY` **não têm geração automática** — é decisão
registrada (fora do escopo da F6, §1.2 da spec de portabilidade): o `.env.example` já
documenta o comando de cada uma, gere e cole o valor antes de subir o stack pela
primeira vez:

```bash
# OTTIMA_SECRET_KEY
openssl rand -hex 32

# OTTIMA_FERNET_KEY
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Essa geração manual não é pendência do produto: é a única pendência de segredo que o
guia trata fora do fluxo de import (§5 adiante trata os segredos de **conexão**, que são
outra coisa).

**Subir o stack:**

```bash
cd deploy
docker compose up -d --build
```

Sobem **7 serviços**: `timescaledb`, `redis`, `api`, `opc-worker`, `flow-runtime`,
`recorder`, `frontend` (ADR-023). `docker compose ps` deve mostrar todos `healthy`
depois de alguns segundos — os healthchecks têm `start_period` de até 30 s no `api` (a
espera pelo Postgres/Redis) e 10-15 s nos demais.

> Nota: existe um segundo arquivo, `deploy/docker-compose.e2e.yml`. Ele é um overlay
> **exclusivo de teste** — acrescenta o simulador OPC-UA (`opcsim`) e publica portas de
> host para a suíte automatizada; produção nunca o usa (comentário no próprio arquivo,
> ADR-023: "uma única porta"). A instalação numa planta de cliente sobe só com o comando
> acima.

**Seed inicial:** o entrypoint do `api` roda migrations, depois `python -m
ottima_api.seed` antes do `uvicorn`. O seed é idempotente: só cria o admin quando a
tabela `users` está vazia, usando `OTTIMA_ADMIN_USERNAME`/`OTTIMA_ADMIN_PASSWORD`/
`OTTIMA_ADMIN_NAME` do `.env`. Se essas variáveis estiverem ausentes com a tabela vazia,
o seed registra erro no log e **não cria admin nenhum** — login fica impossível até
corrigir o `.env` e reiniciar o container `api`.

**Verificação:**

```bash
curl -fsS http://localhost:${OTTIMA_HTTP_PORT:-80}/api/health
```

Corpo esperado: `{"status": "ok", "service": "api", "version": "...", "redis_ok": true,
"db_ok": true}` — os dois booleanos vêm de um heartbeat de fundo (a rota nunca faz I/O
síncrono na resposta); `status` só é `"ok"` com os dois `true`. Login com o admin do
seed (`POST /api/auth/login`) e abertura da **Home** confirmam a instalação: a Home
mostra as três lâmpadas de worker (`opc-worker`/`flow-runtime`/`recorder`, via `GET
/api/health/workers`) e a lista de flows do projeto ativo — nenhum projeto ainda existe
no dia 1, então a tela de Projetos parte do estado "nenhum projeto cadastrado".

**Troubleshooting — healthcheck vermelho:** `docker compose ps` aponta o serviço; `docker
compose logs <serviço>` traz a causa. `api` "unhealthy" geralmente é `timescaledb`/`redis`
ainda não prontos (o `start_period` de 30 s cobre isso) ou `.env` com credenciais de
banco erradas. `opc-worker`/`recorder` "unhealthy" com `api` saudável costuma ser
`OTTIMA_DATABASE_URL`/`OTTIMA_REDIS_URL` — só o `api` monta a URL a partir de
`POSTGRES_*`; os outros herdam a mesma via `environment:` do compose, não editar à mão.

**Troubleshooting — `flow-runtime` não inicia (fica com flows vazios):** o serviço sobe
mesmo se o motor falhar ao montar (o processo não morre, para não derrubar o `/health`
de propósito) — checar `docker compose logs flow-runtime` pela mensagem "falha ao
iniciar o runtime; o serviço sobe sem flows". `GET http://localhost:8002/health` (de
dentro da rede do compose) mostra `status: "degraded"` nesse caso; reiniciar o container
(`docker compose restart flow-runtime`) depois de corrigir a causa (tipicamente Redis
inacessível no boot) resolve.

## 2. Identidade e confiança

Governado por ADR-021 (segurança OPC-UA desde a v1) e RF-202.

**Certificado de aplicação:** é a identidade do `opc-worker` perante os servidores
OPC-UA, gerenciada pela chapa "Certificado da aplicação" em `/engenharia/conexoes`
(visível só a admin — RBAC). Sem certificado, a chapa mostra estado vazio + botão
**Gerar**; com certificado, oferece **Baixar .der** e **Regerar**. É autoassinado, par de
chaves em volume persistente (`certs`), e o Subject Alternative Name (URI) do
certificado já vem fixado em `urn:ottima:opc-worker` — o cliente asyncua usa o mesmo
valor como `ApplicationUri` no handshake; os dois precisam casar byte a byte ou o
servidor recusa a sessão com `BadCertificateUriInvalid`. Não é um passo manual (o
sistema não expõe campo para editar o URI), mas é o primeiro lugar a olhar se um
servidor recusa a conexão citando URI inválida — sinal de volume `certs` adulterado
fora do fluxo do sistema.

**Exportar para o servidor:** baixe o `.der` (botão **Baixar .der**) e cadastre-o na
trust list do servidor/gateway OPC-UA de destino, pelo mecanismo do próprio servidor.

**Confiar no certificado do servidor:** na tabela de Conexões, "Confiar certificado"
faz upload do certificado do servidor (PEM ou DER); o `fingerprint_sha256` devolvido
deve ser conferido contra o que o servidor informa, antes de seguir. "Deixar de
confiar" remove (idempotente).

**O que cada modo exige** (ADR-021, por conexão):

| `security_policy` / `security_mode` | Exige confiar no certificado do servidor | Exige certificado de aplicação |
|---|:-:|:-:|
| `none` | não | só se `auth_mode: certificate` |
| `basic256sha256` (Sign ou SignAndEncrypt) | sim | sim |

`auth_mode: user_password` exige senha armazenada (re-informada a cada import, §5);
`auth_mode: certificate` usa o certificado de aplicação do sistema como credencial —
exige-o mesmo com `security_policy: none`.

**Regenerar** (`force: true`) invalida a confiança anterior: a tela lista antes as
conexões afetadas (as com `security_policy != none` ou `auth_mode: certificate`) e, ao
concluir, mostra o aviso de que os servidores que confiavam no certificado antigo
precisam de **re-trust** manual — regerar sem coordenar com o time da planta derruba
essas conexões até o re-trust.

**Troubleshooting — conexão OPC que não sobe:** a coluna "Último estado" da tabela de
Conexões e o log de eventos (`/eventos`) trazem o motivo, um destes cinco
(`opc-worker/security.py`):

| Motivo | Causa típica |
|---|---|
| `cert_missing` | política diferente de `none` sem certificado de aplicação gerado |
| `cert_mismatch` | certificado do servidor mudou e não foi re-confiado, ou handshake sem resposta por chave pública divergente |
| `connect_failed` | endpoint/porta incorretos, rede indisponível, servidor fora |
| `session_lost` | sessão caiu depois de estabelecida (rede instável, servidor reiniciou) |
| `watchdog_timeout` | bit de watchdog parado por mais de 10 s — ver ADR-009 |

Nenhum desses é diagnosticado por texto solto: a UI sempre soma cor + ícone.

## 3. Pré-requisitos do PID por malha

Este é o núcleo do comissionamento (PRD §9 risco 5, ADR-010): o MPC assume e devolve
malhas que têm PID convencional no PLC, e a transferência **bumpless** depende de
configuração correta do lado do PLC, que o OttimaSystem não controla.

**Por modo-alvo da MV** (`target_mode`, um por MV com PID):

- **RCAS ou CAS** — o sistema escreve o **SP remoto** do PID; o PID, do seu lado,
  precisa ter **SP-tracking** habilitado para que, ao devolver a malha (REMOTO→LOCAL), o
  SP interno do PID assuma sem salto o valor que o MPC vinha escrevendo.
- **ROUT** — o sistema escreve a **saída (OUT)** diretamente; o PID precisa de
  **OUT-tracking** habilitado, pelo mesmo motivo.

Sem o tracking correspondente configurado no PID, a devolução de malha (REMOTO→LOCAL)
salta — exatamente o que o bumpless existe para evitar. Esta configuração é feita **no
PLC**, fora do OttimaSystem; o guia só documenta o pré-requisito.

**Tags por MV com PID** (`PidBinding`, spec §2.1-3/RF-604):

| Tag | Obrigatória | Função | Consequência se faltar |
|---|:-:|---|---|
| `write_tag_id` | sim | SP (RCAS/CAS) ou OUT (ROUT) que o sistema escreve | sem ela a MV não tem `pid`: vira MV "direta" (sem coordenação de modo com PID nenhum) |
| `mode_cmd_tag_id` | sim | comando de modo do PID (alterna AUTO ↔ o `target_mode` configurado) | sistema não consegue pedir ao PID que ceda/retome a malha |
| `readback_tag_id` | sim | leitura da MV real no PID — é o tracking que sustenta o bumpless em LOCAL | bloco fica em `cold_input`: **não arma** para REMOTO/AUTO até o valor chegar |
| `mode_read_tag_id` | opcional | leitura de confirmação de que o PID aceitou o modo pedido | sem ela, "sem mode_read, sem shed": o sistema não confirma a troca de modo nem faz shed automático de volta a LOCAL por mismatch — o comissionamento deve confirmar visualmente no PLC |

**Valores de `mode_values`** (`{auto, target}`): os códigos inteiros que o PLC usa para
os estados AUTO e RCAS/CAS/ROUT daquele PID específico — variam por fabricante/config de
PLC e são preenchidos na aba **Variáveis** do modal do bloco MPC, por MV.

**O que o sistema explicitamente não faz** (ADR-009, ADR-010, ADR-017):

- **Em LOCAL, não escreve MV nenhuma** — o PID do PLC está no comando; o sistema só lê
  (tracking pelo `readback_tag_id`).
- **No boot, não reassume malha nenhuma sozinho** — todo flow sobe **parado**,
  aguardando deploy manual (RF-104); mesmo depois de deploy, o MPC nasce em LOCAL.
- **Em falha de comunicação/OPC** (watchdog > 10 s parado, ou sessão caída), o sistema
  **cessa as escritas** naquela conexão e **para o flow** — o PLC, pelo watchdog dele,
  retoma o controle convencional sozinho.

## 4. Comissionamento passo a passo até AUTO

Checklist operacional; cada etapa é admin, exceto a transição de modos (LOCAL/REMOTO,
MAN/AUTO), que é operador ou admin (ADR-015).

1. **Projeto** (`/engenharia/projetos`) — criar (ou importar, §5) e **ativar**. Ativar
   é a ação de maior consequência da tela: para todos os flows do projeto anterior; a
   confirmação nomeia o projeto atual e quantos flows param.
2. **Conexão** (`/engenharia/conexoes`) — endpoint, `security_policy`/`security_mode`,
   `auth_mode`, watchdog (`watchdog_read_node_id`/`watchdog_write_node_id`, período —
   ADR-009 recomenda ciclo de 1-2 s). Resolver certificados/senha conforme §2 antes de
   seguir; a coluna **Pendências** sinaliza o que falta sem cor de severidade (é
   configuração, não falha de operação).
3. **Tags** (`/engenharia/tags`) — node_id manual por tag; inclui as tags de watchdog e
   todas as do §3 (write/mode_cmd/readback/mode_read por MV, mais as de leitura de
   processo).
4. **Flow** (`/engenharia/flows`) — criar, escolher **Ts** ({0.5, 1, 2, 5, 10, 30, 60 s},
   spec/ADR-007).
5. **Blocos** — montar o canvas: OPC-Read/OPC-Write para as tags, bloco MPC com as abas
   Geral/Variáveis/Modelos/Horizontes/Restrições & Limites/Pesos (RF-607). Conferir
   **`exec_order`**: leituras antes do MPC, MPC antes das escritas — o editor
   auto-numera na inserção e avisa (não bloqueia) inversão de aresta.
6. **TSS e horizontes** — TSS por CV/Restrição na aba Horizontes; `Ts_mpc`/`Np`/`Nc` são
   **derivados**, não editáveis (RF-603).
7. **Deploy** — botão de deploy no flow; estado desejado fica persistido, mas só entra em
   execução por ação explícita (RF-306).
8. **LOCAL (tracking observado)** — com o flow rodando, confirmar no faceplate que a MV
   segue o `readback_tag_id` (nenhum "cold_input" pendente). É o gate de armar: sem
   tracking válido, REMOTO/AUTO ficam bloqueados.
9. **REMOTO** — comandar a troca de LOCAL para REMOTO; verificar em `/eventos` que não
   há `mpc_arm_failed`, e no PLC (fora do sistema) que o modo mudou para o `target_mode`
   configurado.
10. **MAN** — sub-modo de REMOTO: operador escreve as MVs pela UI, dentro dos limites
    duros. Confirmar que as escritas chegam ao PLC (readback acompanha).
11. **AUTO** — o MPC passa a calcular; a transição MAN→AUTO é bumpless (parte das MVs
    atuais). Acompanhar na tela de operação: faceplate principal (status de
    watchdog/solver/overruns), faceplates de CV/MV/Restrição/DV, e a tendência central
    com a predição sobreposta. `/eventos` deve ficar livre de alarme novo depois da
    estabilização.

## 5. Transporte de engenharia entre plantas

Governado por ADR-012 (projeto exportável/importável) e ADR-021 (segredos nunca
exportados); a UI vive em `/engenharia/projetos`.

**Exportar:** botão por linha da tabela — baixa o arquivo de projeto (JSON) do projeto
escolhido (`GET /api/projects/{id}/export`).

**Importar:** três passos no cabeçalho da tela — escolher o arquivo; **prévia** antes de
criar (contagens de conexões/tags/flows, nome editável, e — quando o arquivo tiver
blocos Script — a lista deles com o código visível e confirmação explícita, ver
proveniência abaixo); enviar. O projeto nasce sempre **inativo**; sucesso mostra o
resumo de pendências, recusa lista os problemas um por linha.

**O que o arquivo de projeto não carrega, e por quê:**

| Campo | Motivo |
|---|---|
| Senhas de conexão (`auth_password`) | segredo — re-informado no destino |
| Certificado do servidor confiado | ambiente-específico: o endpoint muda entre plantas, e um certificado antigo confiado erroneamente falha em `cert_mismatch`, diagnóstico pior que `cert_missing` |
| `id`s internos (projeto/conexão/tag) | id da instalação de origem; substituídos por nome lógico no import |
| Dados históricos (amostras, eventos) | fora do escopo de "engenharia" |

**Procedimento de re-informar segredos:** depois de importar, a resposta lista as
pendências por conexão (mesmos três predicados de §2: senha, certificado do servidor,
certificado de aplicação). Resolver cada uma pelo caminho normal — modal de conexão
para a senha, "Confiar certificado" para o servidor, chapa de §2 para o certificado de
aplicação (que é da instalação, não do projeto: se a instalação de destino já tem um,
nada a fazer) — antes de ativar e comissionar o projeto importado.

**Proveniência (atenção obrigatória):** um arquivo de projeto de origem desconhecida
pode trazer blocos **Python-Script** com código que **executa no servidor** assim que o
flow correspondente é deployado (ADR-018 restringe o escopo do script a `math`/`numpy`,
mas não sandboxa o processo). A prévia de import lista todo bloco Script com o código
completo e exige confirmação explícita antes de criar o projeto — leia o código antes de
confirmar. Nunca importe um arquivo de projeto de origem que você não conhece sem essa
leitura.

## 6. Operação contínua e limites conhecidos

**Retenção (ADR-003):** um mês de histórico, sempre — `add_retention_policy(...,
INTERVAL '1 month')` sobre as hypertables `samples`, `events` e `mpc_samples` (mais os
continuous aggregates `samples_1m`/`mpc_samples_1m`), aplicada automaticamente pelo
TimescaleDB, sem código de manutenção. Não há como estender essa janela na v1 (PRD §1).

**Backup do Postgres — procedimento manual, sem automação embutida.** O sistema não
agenda nem promete backup; é responsabilidade operacional da planta. Exemplo de rotina
com `pg_dump` sobre o volume `pgdata` (ajuste ao ambiente):

```bash
cd deploy
docker compose exec timescaledb pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -F c \
  -f /tmp/ottima.dump
docker compose cp timescaledb:/tmp/ottima.dump ./backup-$(date +%Y%m%d).dump
```

Restauração é o inverso (`pg_restore` contra um `timescaledb` novo, banco vazio). O
volume `certs` (certificado de aplicação e certificados de servidor confiados) não entra
no `pg_dump` — se a intenção é restaurar a mesma instalação (não migrar engenharia para
outra planta, que é o caso do §5), inclua esse volume no plano de backup também.

**Não-objetivos da v1** (PRD §1, vale para toda a operação): sem versionamento de
flows, sem ACK de alarmes, sem ideal resting values, sem identificação de modelos
(step-test), sem AD/LDAP, sem HTTPS, sem i18n, um único projeto ativo por vez, histórico
limitado a 1 mês, sem app mobile, sem geração de relatórios. Nenhum desses é lacuna a
reportar como defeito — são escopo fechado da v1, com destino registrado em
`docs/specs/F6-portabilidade-hardening.md` §1.2 onde aplicável.

---

Referências normativas: `docs/PRD.md` (§9 riscos, §7.2 contrato de export/import) ·
`docs/adr/ADR-003, ADR-009, ADR-010, ADR-012, ADR-017, ADR-018, ADR-020, ADR-021,
ADR-023` · `docs/specs/F6-portabilidade-hardening.md` (§2.3 fronteira do arquivo de
projeto, §3.4 hardening, §6.1-6.3 telas) · `docs/GLOSSARY.md`.
