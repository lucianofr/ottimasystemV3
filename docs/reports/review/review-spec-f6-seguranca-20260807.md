# Revisão da spec F6 — superfície de segurança do export/import e dos certificados

**Spec:** docs/specs/F6-portabilidade-hardening.md @ da25cd6
**Veredito:** APPROVE WITH CHANGES
**Achados:** 0 Critical, 6 Important, 0 Minor

Modelo de ameaça usado: rede interna de planta industrial, HTTP sem TLS por decisão aceita (ADR-023, não relitigada), usuários admin/operador locais, atacante plausível = alguém com acesso à rede da planta ou um bundle malicioso entregue a um admin. Nenhum achado abaixo depende de TLS ausente.

## Achados

### SEC-01 — Import de bundle quebra a premissa de confiança do bloco Script (ADR-018) sem revisão nem aviso [Important]

**Seção:** §3.2 (camada 4, "Grafo") · eixo 4a da tarefa · ADR-018

**Problema:** ADR-018 aceita rodar `exec()` de código do usuário com sandbox fraco ("Bibliotecas disponíveis: math e numpy — mais nada no escopo... modelo de ameaça = admin autenticado, sem sandboxing pesado") porque, até a F6, quem ESCREVE o script e quem o IMPLANTA são a mesma pessoa autenticada. A F6 quebra essa premissa: o `code` de um bloco Python-Script viaja inteiro dentro de `flows[].graph` (§2.1-2, nenhuma exclusão em §2.3) e as 4 camadas de validação do import (§3.2-4) nunca inspecionam o CONTEÚDO do `code` — camada 2 (Pydantic) só valida que é uma string presente; camada 4 (`flowgraph/parse.py`/`validate.py`) só valida topologia/portas. Um bundle malicioso entregue a um admin (perfil de ataque explicitamente aceito no enunciado) pode carregar um flow com um script hostil que passa as 4 camadas ilesas, porque nenhuma delas lê o texto do script.

**Evidência:**
- `docs/adr/ADR-018-contrato-bloco-python-script.md`: "Execução via `exec()` em namespace controlado... modelo de ameaça = admin autenticado, sem sandboxing pesado."
- `services/flow-runtime/src/ottima_flow_runtime/script_pool.py:38-50` — `ALLOWED_BUILTINS` é lista fechada (sem `__import__`/`open`/`eval`), mas em `script_pool.py:75-81` o `scope` do `exec()` injeta os objetos MÓDULO completos `math`/`numpy` (`"math": math, "numpy": numpy, "np": numpy`). Builtins fechados não impedem as técnicas conhecidas de fuga por grafo de objetos (`__class__`/`__bases__`/`__subclasses__`/`__globals__`), alcançáveis a partir de qualquer objeto do escopo — inclusive dos próprios objetos numpy — sem precisar de `__import__`. [INFERENCE: não testei um exploit concreto contra esta versão exata do numpy; a categoria de vulnerabilidade é bem documentada em literatura de segurança Python para `exec()` com módulos completos em escopo.]
- `deploy/docker-compose.yml:89` (`flow-runtime: env_file: [.env]`) e ausência de bloco `volumes:` no serviço `flow-runtime` (confirmado por leitura completa do arquivo) — o processo que roda o script recebe TODO o `.env`, inclusive `OTTIMA_SECRET_KEY`/`OTTIMA_FERNET_KEY`/`POSTGRES_PASSWORD` (`deploy/.env.example:12,20`), mesmo sem o código Python do serviço os usar.
- `packages/ottima-core/src/ottima_core/config.py:48-51` confirma o valor desse segredo específico: vazar `OTTIMA_SECRET_KEY` permite forjar um JWT de admin; vazar `OTTIMA_FERNET_KEY` permite decifrar toda `auth_password_enc` do banco.
- O resumo de import (§3.2-7/§6.1-6) só expõe `pending_secrets`; não há nenhum campo ou tela que liste "este bundle contém N blocos Python-Script" para o admin decidir se revisa antes de importar/implantar.

**Consequência:** um admin que importa um bundle malicioso e depois o implanta (ação separada, também `require_admin` — `services/api/src/ottima_api/routers/flows.py:262` — mas rotineira, é o próprio motivo de importar um flow) roda código de origem não confiável dentro do processo `flow-runtime`. Uma fuga bem-sucedida do sandbox herda um ambiente com os dois segredos centrais do sistema (assinatura JWT e cifragem de senha OPC) mesmo sem o serviço precisar deles — ampliando o raio de dano de qualquer fuga, por menor que seja a chance.

**Correção sugerida:** (1) no resumo de import (§6.1-6), listar a contagem de blocos Python-Script por flow (dado já disponível em `graph.nodes[].type == "script"`, sem parsing adicional), para o admin decidir se revisa o código antes de implantar; (2) em `docs/IMPLANTACAO.md` §8-5 (transporte de engenharia), documentar explicitamente que um bundle importado pode conter código Python executável e que o modelo de ameaça do ADR-018 pressupõe que quem implanta confia na origem do bundle — hoje a spec é silenciosa sobre isso; (3) hardening independente e de baixo custo, sem mudar arquitetura: trocar `env_file: [.env]` do `flow-runtime` (e `opc-worker`/`recorder`, mesmo padrão) por uma lista `environment:` explícita das variáveis que cada serviço de fato usa — reduz o raio de dano de qualquer fuga futura sem exigir sandboxing pesado algum.

---

### SEC-02 — Regra de exclusão do §2.1-1 é subconjunto de §2.3: implementador que reusa o schema existente vaza `server_cert_file` e mascara a pendência do §6.3 [Important]

**Seção:** §2.1-1 · §2.3 · §6.3 · eixo 2 da tarefa

**Problema:** §2.1-1 resume a regra de exclusão do bundle como "cada entidade... menos os segredos e menos os ids". `server_cert_file` NÃO é segredo (é só o nome de um arquivo, `conn-<id>.der`) nem é id — é excluído por um TERCEIRO motivo, só registrado em §2.3/decisão A-3 ("ambiente-específico... pinning errado é pior que ausente"). Um implementador que seguir a heurística literal de §2.1-1, ou que reusar por hábito o schema já existente no código (`_ConnectionFields`, base de `ConnectionCreate`/`ConnectionUpdate`/`ConnectionOut`, que inclui `server_cert_file: str | None`), produz um schema de bundle que inclui esse campo — contradizendo §2.3 sem violar a regra que §2.1-1 escreveu.

**Evidência:**
- `packages/ottima-core/src/ottima_core/schemas/connections.py:13-16` — `_ConnectionFields` inclui `server_cert_file` junto de `name`/`endpoint`/etc., os mesmos campos do exemplo normativo.
- §2.1-2 (JSON normativo) de fato NÃO lista `server_cert_file` no objeto `connections[0]` — o exemplo está certo, mas é só um exemplo, não substitui uma regra de exclusão completa no texto de §2.1-1.
- §2.3, tabela: `server_cert_file` está listado com motivo "decisão A-3: material público, mas ambiente-específico" — categoria distinta de "segredo" e de "id", que é exatamente o vocabulário que §2.1-1 usa para explicar a exclusão.
- §6.3-1: a pendência derivável usa `security_policy != "none" && !server_cert_file` — uma STRING não-nula (mesmo um nome de arquivo copiado do projeto de origem, que não existe no volume `certs/trusted/` da instalação de destino) faz esse predicado avaliar como "sem pendência", escondendo do admin uma conexão que na prática falhará com `cert_missing`/arquivo ausente no primeiro connect.

**Consequência:** se a ambiguidade se materializar no código, o bug atinge diretamente o mecanismo que o próprio aceite da fase cita como evidência de "re-informando segredos" (§11: "§6.3 (pendência derivável)"). Mitigante real: o cenário E2E-F6-02 explicitly verifica "`pending_secrets` lista as duas pendências" após um round-trip com conexão segura — então esse bug específico tem chance real de ser pego em teste antes de ir a produção. Isso reduz o risco de produção, mas não resolve a ambiguidade do texto da spec, que continua convidando o erro.

**Correção sugerida:** em §2.1-1, trocar a heurística de duas categorias ("menos os segredos e menos os ids") por uma frase que remeta explicitamente à lista completa de §2.3 (três categorias: segredo, ambiente-específico, id/metadado-de-instalação), e acrescentar em §2.3 uma nota decisiva: "o schema de bundle de conexão NÃO é `_ConnectionFields`; é um schema novo com os mesmos campos MENOS `server_cert_file`" — nomeando o campo armadilha explicitamente, já que ele sobrevive ao filtro léxico da regra atual.

---

### SEC-03 — `graph_json`/código do bloco Script viaja verbatim no bundle sem qualquer aviso sobre credencial embutida em script [Important]

**Seção:** §2.3 · §8 (IMPLANTACAO.md) · eixo 1 da tarefa

**Problema:** o bundle é feito para atravessar fronteiras organizacionais — ADR-012: "levar a engenharia de uma planta para outra"; §1.2 do PRD/spec trata isso como caso de uso central (backup, replicação, transporte entre plantas de cliente). `flows[].graph` inclui o `code` (texto livre) de cada bloco Python-Script, sem qualquer exclusão ou aviso. Se um engenheiro digitou um valor sensível diretamente no script (constante de comparação, "senha" de intertravamento manual, string colada de outro lugar com um segredo dentro), o export carrega esse texto byte a byte para fora da instalação de origem — e nada na spec, nem no guia de implantação (§8, item 5 "Transporte de engenharia entre plantas"), menciona esse risco.

**Evidência:**
- `packages/ottima-core/src/ottima_core/flowgraph/parse.py:54` (`class ScriptConfig`, campo `code: str`) é o ÚNICO campo de texto livre arbitrário em todo o `graph_json` — os demais blocos (`TagConfig`, `TfsConfig`, `MpcRawConfig`) só carregam referências/números.
- §2.3 (tabela "o que não atravessa a fronteira") não cita `graph_json`/`code` em nenhuma linha.
- §8-5 ("Transporte de engenharia entre plantas... o que o bundle não carrega e por quê") remete só a §2.3, que por sua vez não cobre este caso.

**Consequência:** o risco é real mas estreito — o sandbox do bloco Script (`script_pool.py:38-50`) não dá acesso a rede nem a sistema de arquivos, então um segredo hardcoded ali não pode ser "usado" para autenticar em nada externo pelo próprio script; o dano é a EXPOSIÇÃO do valor em texto claro dentro de um arquivo que agora circula fora da instalação (e-mail, pendrive, repositório do integrador), não uma exploração ativa pelo motor. Ainda assim é um vazamento de segredo real se o valor existir, e a spec não trata, não avisa, nem documenta.

**Correção sugerida:** acrescentar uma linha em §2.3 e em §8-5: "o bundle exporta o código-fonte de todo bloco Python-Script verbatim; não digite senhas, tokens ou strings de conexão dentro do bloco Script — elas viajarão com o arquivo." Custo zero de implementação (é só documentação), mas fecha a lacuna que hoje não existe em lugar nenhum do material normativo desta fase.

---

### SEC-04 — Import não tem teto de contagem (flows/conexões/tags), e a validação síncrona da camada 4 roda no único worker uvicorn que também serve o `/ws` de operação [Important]

**Seção:** §3.2-1 · §3.2-4 · eixo 7 da tarefa

**Problema:** o único teto explícito do import é de BYTES (4 MiB, §3.2-1). RNF-01 ("≥10 flows... ~100 tags") é um PISO de dimensionamento-alvo, não um teto validado em código — e §3.1-4 só usa "~10 flows" como justificativa para export não paginar, nunca como limite de import. Um bundle dentro de 4 MiB pode conter centenas a milhares de flows minúsculos (um flow com 1-2 nós cabe em poucas centenas de bytes de JSON). A camada 4 (`flowgraph/parse.py` + `flowgraph/validate.py`, "por flow", "toda ela antes do commit", §3.2-4) é código Python síncrono e puramente CPU-bound — `validate_graph` (`packages/ottima-core/src/ottima_core/flowgraph/validate.py:57`) não é `async def` e não tem nenhum `await` interno. Se o handler da rota `import` chamar essa cadeia diretamente (sem `asyncio.to_thread`, que já é o padrão usado em outro lugar do próprio serviço — `services/api/src/ottima_api/routers/health.py:37-40`), o processamento bloqueia o event loop inteiro do serviço `api`.

**Evidência:**
- `deploy/entrypoint-api.sh` — `exec uvicorn ottima_api.main:app --host 0.0.0.0 --port 8000` sem `--workers`: um único worker, um único event loop, para todo o serviço `api`.
- `frontend/nginx.conf:14-18,21-27` — tanto `/api/` quanto `/ws` fazem proxy para o MESMO `api:8000`; o `/ws` é o canal ao vivo de status de flow que alimenta os faceplates de operação (spec F3 §5.3).
- `packages/ottima-core/src/ottima_core/flowgraph/validate.py:57-59` (`def validate_graph(...)`, sem `async`) e `packages/ottima-core/src/ottima_core/flowgraph/mpc_config.py` (`class MpcRawConfig`, `extra="allow"`, sem teto de chaves) — a validação completa de um nó `mpc` com matriz cheia é materializada em memória antes de `_check_mpc_caps` rejeitar por contagem.
- §3.2-1 só define 413 por tamanho de corpo; nenhuma linha de §3.2 define 422/413 por CONTAGEM de flows, conexões ou tags no bundle.

**Consequência:** um bundle tecnicamente válido mas deliberadamente grande (ou apenas um export real de uma instalação com muito mais engenharia do que a dimensão-alvo, entregue de outra fonte) mantém a transação de import aberta — e o event loop do único worker bloqueado — pelo tempo total de validar todos os flows. Durante essa janela, TODO o tráfego de `/api/` e `/ws` do serviço `api` fica parado: operadores perdem a atualização ao vivo dos faceplates e o polling de `/api/operate/mpcs`, mesmo sem nenhuma escrita indevida em planta (o caminho de escrita física fica em `opc-worker`/`flow-runtime`, processos separados). É um risco de disponibilidade da IHM de operação, não de segurança de processo.

**Correção sugerida:** (1) somar um teto explícito de CONTAGEM no §3.2 (ex.: máximo de flows/conexões/tags no bundle, coerente com o "~10 flows, ≤5 conexões, ~100 tags" que a própria spec já usa como dimensionamento-alvo em §3.1-4 — reaproveitar o mesmo número, não inventar um novo), rejeitado com 422 antes de qualquer parsing de grafo; (2) rodar a camada 4 (ou a validação+escrita inteira) via `asyncio.to_thread`, reaproveitando o padrão já usado em `health.py:37-40` deste mesmo serviço — sem mudar arquitetura nem adicionar dependência.

---

### SEC-05 — Export não gera evento de auditoria, embora a própria spec justifique o RBAC citando a sensibilidade do que é exportado [Important]

**Seção:** §3.1-1 · §3.2-8 · eixo 6 da tarefa

**Problema:** §3.1-1 justifica `require_admin` no export dizendo: "Mesmo sem segredos, o bundle revela a topologia OPC completa da planta." Essa é exatamente a razão pela qual TODA outra ação sensível do sistema é auditada (padrão `_publicar`/`publish_event`, presente em toda mutação de `connections.py`/`projects.py`/`tags.py`). O import ganha um evento novo (`project_imported`, §3.2-8), mas o export — que é a ação que a própria spec descreve como reveladora da topologia completa — não gera nenhum evento em nenhum lugar de §3.1.

**Evidência:**
- `packages/ottima-core/src/ottima_core/bus.py` (lista completa de `KIND_*`) não tem nenhum kind de exportação; o vocabulário cobre create/update/delete de conexão, tag, flow, e agora (por §3.2-8) importação de projeto — mas não exportação.
- `services/api/src/ottima_api/routers/certificates.py:71-80` (`export_app_cert`) já é precedente de uma rota GET sensível sem auditoria neste mesmo código-base — mas exportar uma chave PÚBLICA de certificado não é comparável a exportar a topologia OPC inteira de tags/conexões/endpoints que §3.1-1 chama de sensível.
- §3.1 (itens 1-4) não menciona evento em nenhuma linha; §11 (tabela de aderência ao aceite) também não cita auditoria de export.

**Consequência:** um admin (credencial própria ou comprometida) pode extrair a topologia OPC completa da planta — endpoints, node_ids, estrutura de flows — sem deixar rastro algum em `/eventos`, ao contrário de qualquer outra ação administrativa do sistema. Isso não amplia quem PODE fazer isso (RBAC já restringe a admin), mas remove a única camada de detecção/forense que o resto do sistema tem para esse tipo de ação.

**Correção sugerida:** em §3.1, acrescentar um item análogo a §3.2-8: emitir `project_exported` (severity `info`, origin `user:<id>`, payload com `project_id` e as mesmas contagens de conexões/tags/flows já usadas no de `project_imported`) depois de servir a resposta — mesmo padrão de "sempre depois do commit/sucesso, nunca antes" já usado em `connections.py`.

---

### SEC-06 — Aviso de re-trust do certificado de aplicação é genérico e sua única superfície de UI é escopada ao projeto ativo, embora o certificado seja da instalação inteira [Important]

**Seção:** §6.2-1 · eixo 5 da tarefa

**Problema:** o certificado de aplicação é ÚNICO por instalação, não por projeto — a própria spec o rotula assim ("Certificado da aplicação (**instalação**)", §6.2-1). Regenerá-lo com `force=true` invalida o trust em TODOS os servidores OPC-UA que confiavam no certificado anterior, através de TODOS os projetos da instalação (ativo ou não), porque `ottima_core/certs.py` guarda um único par de arquivos em `<certs_dir>/app/`, sem escopo de projeto. Mas a única superfície de UI para essa ação (a chapa de §6.2-1) fica no topo de `/engenharia/conexoes`, que é escopada ao projeto ATIVO (`useConnections(projectId)` recebe o id do projeto ativo, nunca lista todos). O aviso devolvido pelo backend (`_MSG_RE_TRUST`) é um texto fixo genérico, sem listar quais conexões (de qual projeto) precisam de re-trust.

**Evidência:**
- `packages/ottima-core/src/ottima_core/certs.py:75-83` (`app_cert_paths`) — um único diretório `app/` por `certs_dir`, sem parametrização por projeto ou conexão.
- `frontend/src/features/connections/ConnectionsPage.tsx:92-94` — `const projeto = useActiveProject(); const projectId = projeto.data?.id ?? null; const conexoes = useConnections(projectId);` — a tabela de conexões (e a chapa de certificado no topo da mesma página, por §6.2-1) só enxerga o projeto ativo.
- `services/api/src/ottima_api/routers/certificates.py:28-31,52` — `_MSG_RE_TRUST` é uma string fixa, sem lista de conexões; `AppCertificateGenerateOut` (`schemas/certificates.py`) só tem `warning: str | None`, nenhum campo estruturado de conexões impactadas.
- Nenhum outro endpoint no material lido cruza "conexões com `security_policy != 'none'`" através de TODOS os projetos (só existe `GET /api/connections?project_id=X`, sempre filtrado).

**Consequência:** um admin que regenera o certificado a partir da página de Conexões do projeto A não tem, em lugar nenhum do sistema, uma lista das conexões seguras de projetos B, C (inativos no momento) que também pararam de confiar no novo certificado. Essas conexões falharão em `cert_mismatch`/re-trust pendente só quando esses projetos forem ativados de novo — um modo de falha atrasado e silencioso, sem sinal algum na tela onde a ação foi tomada. O sistema falha para o lado seguro (a malha simplesmente não conecta, sem escrita indevida), então o risco é operacional/de descoberta tardia, não de segurança de processo.

**Correção sugerida:** (1) trocar o texto fixo `_MSG_RE_TRUST` por um aviso que enumere as conexões impactadas — o backend já tem tudo que precisa numa query `SELECT` em `opc_connections WHERE security_policy != 'none'` sem filtro de projeto, dentro do próprio handler de `generate_app_cert`; devolver essa lista (nome da conexão + nome do projeto) no corpo de `AppCertificateGenerateOut`; (2) no frontend, renderizar essa lista explicitamente ao lado do aviso verbatim do backend, agrupada por projeto — não só o texto solto.

## Verificações positivas

- **Teto de 64 KiB do upload de certificado de servidor é real, não decorativo.** `_excede_o_declarado`/`_ler_certificado` (`services/api/src/ottima_api/routers/connections.py:42,95-127`) checam `Content-Length` como otimização barata e, independentemente dele, abortam em streaming assim que o total lido cruza o teto — nunca bufferizam o corpo inteiro antes de comparar. Tratamento de digit-string malformado (`"²".isdigit()` vs `int()`) também está coberto.
- **Parsing de X.509 não confiável tem tratamento de erro completo.** `_load_certificate` (`packages/ottima-core/src/ottima_core/certs.py:222-235`) tenta DER, cai para PEM, e qualquer formato inválido vira `ValueError` com mensagem pt-BR — nunca uma exceção crua sobe até o cliente. O router mapeia isso para 422 (`connections.py`, `set_server_certificate`).
- **`pending_secrets` cobre corretamente os três `auth_mode`.** Verificado que `auth_mode == "certificate"` reusa o certificado de aplicação da instalação (`services/opc-worker/src/ottima_opc_worker/security.py:167-173`, `_configure_identity`), não exige segredo por conexão — o predicado `needs_password := auth_mode == "user_password"` de §3.2-7/§6.3-1 não tem lacuna para esse terceiro modo.
- **Disciplina de projeção manual campo-a-campo já é o padrão real do código, não só da spec.** `_to_out` (`services/api/src/ottima_api/routers/connections.py:47-66`) nunca usa `model_validate(orm_obj, from_attributes=True)` para saída sensível — é um precedente forte a favor de replicar o mesmo padrão no serializador do bundle, mesmo que o texto da spec (§2.1-1) não obrigue isso explicitamente (ver SEC-02).
- **`GET /api/projects/{id}/export` de qualquer projeto por id não é IDOR.** Não há fronteira de tenant nesta instalação single-plant: `User` é global à instalação (§2.3), e `GET /api/projects/{id}` já é legível por qualquer operador autenticado hoje (`services/api/src/ottima_api/routers/projects.py`, `dependencies=[Depends(require_operator)]`). Restringir o export a admin (§3.1-1) é reforço, não a única barreira contra acesso indevido.
- **`GET /api/health` público expondo `redis_ok`/`db_ok` não é achado sob este modelo de ameaça.** A rota já era pública antes da F6 (`services/api/src/ottima_api/routers/health.py:17-19`); os dois booleanos novos não revelam versão, credencial, topologia ou qualquer dado acionável a mais do que um atacante com acesso à rede da planta já poderia inferir sondando portas — e ADR-023 já aceita a rede interna como perímetro de confiança para HTTP sem TLS.
- **`node_id` malicioso em tag importada não é uma superfície nova.** `Tag.node_id` já é texto livre aceito de qualquer admin autenticado hoje via criação manual (`packages/ottima-core/src/ottima_core/schemas/tags.py`, sem `max_length`); o import não abre um caminho de confiança diferente do que já existe — o consumidor (opc-worker) trata `node_id` como string opaca vinda de um admin de qualquer forma.
- **Filename do export evita injeção de header.** O slug do nome do projeto (§3.1-2, reduzido a `[a-z0-9-]`) elimina risco de quebra de `Content-Disposition` via nome de projeto malicioso.
