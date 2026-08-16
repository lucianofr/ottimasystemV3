# Auditoria de arquitetura — profundidade de módulos, seams e testabilidade

**Base:** branch `audit/arquitetura` @ `e38f528` (worktree `.worktrees/audit-arquitetura`)
**Método:** 7 explorações paralelas somente-leitura sobre os hot spots dos últimos 120 commits
**Achados:** 22 candidatos de aprofundamento — 12 Strong, 10 Worth exploring, 0 Speculative
**Recomendação de primeiro corte:** ARCH-07
**Débito registrado:** TD-015 a TD-024 (`_tech-debt.md`)

Auditoria de *aprofundamento*: onde um module é raso (interface quase tão complexa quanto a
implementation) e onde a complexidade está espalhada em vez de concentrada. O vocabulário de
arquitetura é fixo — module, interface, implementation, depth, seam, adapter, leverage, locality —
e o de domínio segue `docs/GLOSSARY.md` (Flow, Bloco, Scan cycle, Barramento, Watchdog, Faceplate,
Restrição, Predição, Tag calculada, Hot-swap).

Cada suspeita de module raso passou pelo **deletion test**: deletar esse module CONCENTRARIA a
complexidade (candidato) ou apenas a MOVERIA (não é candidato)? A regra de seam também vale:
um adapter é seam hipotético, dois adapters é seam real — nenhum candidato propõe seam com um só.

**Decisões não re-litigadas.** Os 28 ADRs de `docs/adr/` foram lidos por fatia. FastAPI-all-in
(ADR-001), Redis pub/sub (ADR-002), asyncio-sem-Celery (ADR-004), canvas React Flow com execução
no backend (ADR-005), separação opc-worker/flow-runtime (ADR-006) e hot-swap sem versionamento
(ADR-011) seguem de pé. **Nenhum dos 22 candidatos contradiz um ADR**; dois carregam ressalva
registrada no próprio achado (ARCH-04, ARCH-11).

**Limitação do método.** O MCP `code-review-graph` estava fora do ar (timeout de 30 s em duas
tentativas), então a exploração usou Read/Grep/ast-grep — a saída que `CLAUDE.md:193` prevê. Um
grafo vivo teria dado cobertura de chamadores mais barata; as contagens de callsite abaixo foram
obtidas por busca textual e estrutural, e as três alegações mais graves (ARCH-07, ARCH-11, ARCH-19)
foram verificadas manualmente, arquivo por arquivo.

Uma renderização HTML com diagramas antes/depois foi gerada em `/tmp` durante a auditoria. É
descartável: as descrições de estrutura abaixo (`Antes`/`Depois`) são o registro completo.

---

## Achados

### Fatia — Tendências e Tela de operação (frontend)

A fatia tem uma parte saudável e uma fricção real e concentrada. `escalas.ts`, `trendTheme.ts`, `JanelaTempo`/`useJanelaDeslizante` e `TrendChart` já são módulos compartilhados de fato — ADR-030 documenta explicitamente a decisão do trend fuzzy reusar `TrendChart` em vez de reimplementar ("mesma janela deslizante, mesmos controles"), e funciona: TrendPage e TrendFuzzy são hoje implementations finas do mesmo module. O trend de operação (`TrendOperacao.tsx`, 978 linhas) é a exceção histórica: nasceu antes de `TrendChart` amadurecer (ADR-016, predição do MPC) e nunca foi retrofitado — reimplementa a mesma casca de instância uPlot por conta própria, e o mesmo padrão de 'resolvido duas vezes' se repete no alinhamento de pena no eixo compartilhado (`montarMatriz`/`montarMatrizFuzzy`/`alinharNoEixo`, três variantes do mesmo algoritmo, citando-se mutuamente em comentário) e no merge de borda viva (`bordaViva.ts` generalizou o problema DEPOIS de `mesclarSeriesVivas` já ter resolvido, mas só para as outras duas telas). A queixa do usuário — 'todos os gráficos de tendência devem se comportar igual' — tem evidência concreta e localizada: a legenda de operação não mostra valor nem EU onde trend e fuzzy mostram. Os `*.check.ts` cobrem bem a lógica pura extraída; o risco real mora na integração de 978 linhas de refs/effects em `TrendOperacao.tsx`, sem teste unitário — só e2e.

#### ARCH-01 — Motor de instância uPlot: TrendChart existe, mas o trend de operação reimplementa a mesma casca por conta própria [Strong · in-process]

**Arquivos:**
- `frontend/src/features/trend/TrendChart.tsx:33-104`
- `frontend/src/features/operate/TrendOperacao.tsx:381-462 (construirOpcoesOperacao)`
- `frontend/src/features/operate/TrendOperacao.tsx:769-830 (segunda instanciação de uPlot)`
- `frontend/src/features/fuzzy/TrendFuzzy.tsx:190-192 (consumo de TrendChart)`
- `docs/adr/ADR-030-fuzzy-operate.md:67-70`

**Problema:** O trend de operação reconstrói do zero a mesma casca de instância uPlot (separação estrutura/dados vivos, ResizeObserver, `setData` sem recriar preservando zoom, reset) que `TrendChart` já resolve e que o próprio ADR-030 manda reusar — três telas de tendência, dois motores paralelos de fato.

**Evidência:**
- `frontend/src/features/trend/TrendChart.tsx:33-104 — casca completa: estrutura, ResizeObserver, setData preservando zoom`
- `frontend/src/features/operate/TrendOperacao.tsx:381-462 — construirOpcoesOperacao, opções paralelas às de trendTheme.ts::construirOpcoes`
- `frontend/src/features/operate/TrendOperacao.tsx:769-830 — segunda instanciação de uPlot, próprio ResizeObserver, próprio reset`
- `docs/adr/ADR-030-fuzzy-operate.md:67-70 — decisão explícita de reusar TrendChart para fuzzy, mesma janela e controles`
- `frontend/src/features/operate/TrendOperacao.tsx:50-53 — comentário do próprio autor: "uPlot re-vestido no molde de TrendChart.tsx" (reimplementação reconhecida, não acidental)`

**Antes (estrutura):** TrendPage -> TrendChart -> new uPlot() (estrutura/dados-vivos, ResizeObserver, reset). TrendFuzzy -> TrendChart -> new uPlot() (mesmo caminho, reuso real). TrendOperacao -> effect próprio (construirOpcoesOperacao, ResizeObserver próprio, reset próprio) -> new uPlot() — segundo call-site independente fazendo a MESMA separação estrutura/dados vivos, só que com bands, plugins de predição e range de eixo x dinâmico embutidos direto no motor.

**Depois (estrutura):** TrendPage, TrendFuzzy e TrendOperacao todos apontam para um module `MotorTrend` (dono do container ref, da instância uPlot, do ResizeObserver, do efeito de recriação por hash de estrutura, do efeito de `setData` preservando zoom, do reset) parametrizado por {optionsBuilder, plugins, bands, scaleXRange}. Um único `new uPlot()`. TrendOperacao fornece plugins de predição/linha-agora e o range de eixo x como CONFIGURAÇÃO passada ao motor, não como uma segunda implementation da casca.

**Deletion test:** Deletar a casca própria de TrendOperacao (efeitos de criação/resize/reset) e delegar ao MotorTrend não move a complexidade para outro lugar — CONCENTRA: hoje um bug de resize ou de preservação de zoom exige correção replicada nos dois motores (já aconteceu com a âncora do divisor "agora", ver candidato de borda viva/legenda); com um motor só, conserta-se uma vez.

**Superfície de teste:** Hoje: `TrendChart.tsx` sem teste unitário próprio (só e2e via TrendPage/TrendFuzzy); `TrendOperacao.tsx` sem teste unitário — 978 linhas, só e2e `operate-trend.spec.ts` com comparação de hash de canvas. Depois: o motor ganha um teste de contrato (estrutura recria a instância, dados vivos não recriam, resize atualiza, reset limpa zoom) rodável uma vez só; os e2e continuam por cima, provando cada superfície, não o motor.

**Correção sugerida:** Extrair a casca de instância uPlot (criação, resize, `setData` sem recriar, reset) para um module profundo parametrizado por opções/plugins/bands/range de eixo x, com `TrendChart` e `TrendOperacao` virando implementations finas dele.

**Ganhos:** Um seam de instância uPlot, dois adapters reais hoje · Locality: bug de resize ou de zoom conserta uma vez · Interface rasa: plugins/bands entram, instância sai · Deleta a casca duplicada de TrendOperacao.tsx · Teste de contrato único cobre as três superfícies

---

#### ARCH-02 — Alinhamento de pena no eixo compartilhado (carry-forward) implementado três vezes [Strong · in-process]

**Arquivos:**
- `frontend/src/features/trend/useHistory.ts:108-146 (montarMatriz)`
- `frontend/src/features/fuzzy/historicoFuzzy.ts:17-53 (montarMatrizFuzzy)`
- `frontend/src/features/operate/trendOperacao.ts:175-197 (alinharNoEixo)`

**Problema:** O mesmo algoritmo — unir carimbos de várias penas num eixo x e repetir o último valor conhecido até um teto de carry-forward — está codificado em três funções puras independentes, com dois estilos de implementation (cursor multi-série vs Map por coluna), e os comentários das três se referenciam mutuamente como "a mesma regra".

**Evidência:**
- `frontend/src/features/trend/useHistory.ts:108-146`
- `frontend/src/features/fuzzy/historicoFuzzy.ts:17-20 — comentário: "mesmo algoritmo de montarMatriz/resumirSeries"`
- `frontend/src/features/operate/trendOperacao.ts:175-197 — comentário: "Mesma regra do trend de engenharia (montarMatriz em useHistory.ts), aqui por coluna"`

**Antes (estrutura):** montarMatriz (useHistory.ts) e montarMatrizFuzzy (historicoFuzzy.ts) cada um caminha os vetores de carimbo de várias séries com um cursor por pena, comparando o próximo instante de cada uma. alinharNoEixo (trendOperacao.ts) resolve o mesmo conceito de carry-forward-com-teto, mas por Map em cima de um eixo x já pronto. Três implementations, nenhum primitivo compartilhado.

**Depois (estrutura):** Um primitivo `alinharSerieNoEixo(eixoX, t, valores, tetoS, limiteS?)` — hoje é alinharNoEixo — vira a fonte única; montarMatriz e montarMatrizFuzzy passam a montar o eixo união e chamar o primitivo por pena, perdendo o cursor duplicado.

**Deletion test:** Deletar montarMatrizFuzzy e apontar TrendFuzzy para uma função que monta o eixo e chama alinharNoEixo por porta CONCENTRA a lógica de carry-forward num lugar só — hoje ela está espalhada em três arquivos que se citam de memória em comentário, não por import.

**Superfície de teste:** Hoje: cada função tem sua própria suíte de `.check.ts` testando o MESMO invariante (silêncio além do teto vira gap) com fixtures diferentes. Depois: um `alinharNoEixo.check.ts` cobre o invariante uma vez; os testes de montarMatriz/montarMatrizFuzzy encolhem para provar só a construção do eixo união.

**Correção sugerida:** Extrair um único primitivo de alinhamento (uma série, um eixo x, um teto, um limite opcional) e recompor `montarMatriz`/`montarMatrizFuzzy` como N chamadas dele; `alinharNoEixo` já tem essa forma — vira a fonte, não mais uma terceira variante.

**Ganhos:** Uma implementation do carry-forward, não três · Teste de contrato único cobre trend, fuzzy e operação · Locality: mudar a regra de carência conserta as três telas · Reduz risco de divergência silenciosa entre telas

---

#### ARCH-03 — Merge da borda viva generalizado depois, mas a implementation original de operação ficou de fora [Worth exploring · in-process]

**Arquivos:**
- `frontend/src/features/trend/bordaViva.ts:1-17`
- `frontend/src/features/trend/bordaViva.ts:49-90`
- `frontend/src/features/trend/bordaViva.ts:144-147 (mesclarHistoricoVivo)`
- `frontend/src/features/operate/trendOperacao.ts:58-93 (mesclarSeriesVivas)`

**Problema:** `bordaViva.ts` foi escrito DEPOIS de `mesclarSeriesVivas` (operate) já resolver o mesmo problema — o próprio comentário do module admite isso — mas generalizou o merge histórico+ao-vivo só para trend e fuzzy; operate ficou com sua própria terceira implementation, não migrada para a generalização que ela mesma motivou.

**Evidência:**
- `frontend/src/features/trend/bordaViva.ts:1-17 — comentário admite: "O trend de operação MPC já fazia isso... Este módulo é a peça que faltava, compartilhada pelas duas" (trend+fuzzy, não operação)`
- `frontend/src/features/operate/trendOperacao.ts:58-93`

**Antes (estrutura):** bordaViva.ts é dono de acumularPontosVivos + mesclarHistoricoVivo, consumido por TrendPage e TrendFuzzy. trendOperacao.ts é dono de uma mesclarSeriesVivas paralela, codificada de forma independente (superconjunto de responsabilidades: sp/auto/taxa OPC), sem nenhuma ligação com bordaViva.ts.

**Depois (estrutura):** O primitivo de acumulação de bordaViva.ts generalizado com colunas extras opcionais; mesclarSeriesVivas vira um adapter fino que chama o acumulador compartilhado por variável e só acrescenta a derivação de sp/auto por cima, em vez de re-derivar o merge inteiro.

**Deletion test:** Deletar mesclarSeriesVivas hoje MOVERIA a complexidade de volta para dentro de TrendOperacao.tsx (já é chamada de um único lugar) — não é ainda candidato óbvio de deleção pura; o candidato real é a generalização de bordaViva.ts absorver o caso que ficou de fora, não apagar operate.

**Superfície de teste:** Hoje: mesclarSeriesVivas tem cobertura própria em trendOperacao.check.ts, bordaViva.ts tem a sua em bordaViva.check.ts — dois contratos para o mesmo conceito de merge. Depois: um teste de contrato de acumulação, mais um teste pequeno só da derivação de sp/auto que somente operate precisa.

**Correção sugerida:** Avaliar se o formato genérico de bordaViva.ts (Map<string, PontoVivo[]> por id) comporta os campos extras que o MPC precisa (sp, auto, taxa OPC) como colunas opcionais, e migrar mesclarSeriesVivas para consumir o mesmo primitivo de acumulação.

**Ganhos:** Um dono do merge histórico+ao-vivo, não dois · Locality: bug de dedupe por carimbo conserta as três telas · Documenta a genealogia da duplicação em vez de perpetuá-la

---

#### ARCH-04 — Legenda de pena: três blocos quase idênticos, comportamento não uniforme entre superfícies [Worth exploring · in-process]

**Arquivos:**
- `frontend/src/features/trend/TrendPage.tsx:281-317`
- `frontend/src/features/fuzzy/TrendFuzzy.tsx:218-251`
- `frontend/src/features/operate/LegendaOperacao.tsx:61-146`

**Problema:** As três legendas de tendência renderizam inline a mesma forma (swatch de cor + nome + badges + editor de escala), mas com conjuntos de informação diferentes: trend e fuzzy mostram valor atual formatado e EU na linha da pena; a legenda de operação não mostra valor nem EU em lugar nenhum da linha — é exatamente o sintoma que o usuário reportou.

**Evidência:**
- `frontend/src/features/trend/TrendPage.tsx:311-316 — valor formatado + EU + EditorEscala na linha`
- `frontend/src/features/fuzzy/TrendFuzzy.tsx:248-250 — valor formatado + EU na linha, sem EditorEscala`
- `frontend/src/features/operate/LegendaOperacao.tsx:75-140 — linha sem valor nem EU, com indicador "Eixo Y" e badge "Acima do teto" que as outras duas não têm`

**Antes (estrutura):** Três blocos JSX inline — <Card data-testid="trend-legend"> em TrendPage, <Card data-testid="fuzzy-trend-legend"> em TrendFuzzy, LegendaOperacao.tsx — cada um re-derivando a mesma forma de linha a partir de um resumo/pena de domínio diferente, com campos presentes/ausentes divergentes (valor, EU, badge de qualidade, editor de escala).

**Depois (estrutura):** Um module `PainelLegendaTrend` recebendo `readonly LinhaLegenda[]` (cor, rótulo, badges, valor+eu opcional, filho de editor de escala) — TrendPage, TrendFuzzy e LegendaOperacao mapeiam seu domínio para essa forma e delegam a renderização da linha.

**Deletion test:** Deletar o bloco de legenda de qualquer uma das três telas hoje MOVE a lógica de renderização de linha para outro arquivo (LegendaOperacao já é essa extração parcial) sem concentrar nada — cada superfície ainda decide sozinha o que mostrar. Um module de apresentação comum CONCENTRARIA a decisão.

**Superfície de teste:** Hoje: nenhuma superfície verifica via teste unitário que valor/EU aparecem — só e2e olhando texto renderizado. Depois: um teste de contrato do module de apresentação garante que valor+EU aparecem quando fornecidos e desaparecem quando omitidos; as três telas testam só o mapeamento pena→LinhaLegenda.

**Correção sugerida:** Extrair um module de apresentação único para a linha de legenda (swatch, rótulo, badges de qualidade, valor+EU opcional, slot de editor de escala) e decidir DELIBERADAMENTE — não por omissão de três reescritas — se a legenda de operação deve ganhar valor+EU.

**Ganhos:** Um module de legenda, três consumidores fornecendo view-model · Decisão de UX vira explícita, não acidente de reescrita · Reduz JSX quase-idêntico repetido em cada superfície · Testável uma vez: cor distinta, badge de qualidade, EU

> **Atenção ADR** — ADR-016: nenhuma menção a paridade de legenda entre telas — não há decisão registrada que justifique a lacuna de valor/EU na legenda de operação; vale confirmar com o autor se é intencional (os faceplates acima já mostram PV+EU em mono grande) antes de tratar como bug.

---

### Fatia — Barramento e Canal ao vivo

Fatia saudável no núcleo: o Barramento (bus.py + pubsub.py) tem UM adapter real (Redis via testcontainers em api/recorder/calc-worker/ottima-core/flow-runtime, mais o Redis do compose no e2e) — não há fake/mock in-memory em lugar nenhum, então NÃO se propõe seam novo (um único adapter = seam hipotético). O hub de WebSocket (ws.py/FlowStatusHub) e o CanalAoVivoProvider do frontend são modules profundos de verdade: cada hop no caminho de um valor (opc-worker → Redis → PatternListener resiliente → FlowStatusHub._dispatch_opc_values → WebSocket → CanalAoVivo.tsx::lerOpcValues → buffer 250ms → tagValues → Faceplate/Trend) faz trabalho real (filtro por assinante, backoff/reconexão, backpressure com fila 8 drop-oldest, coalescência) — nenhum module do caminho é um repasse puro ("só reempacota"), então não há candidato de módulo-fino para colapsar aqui. Também não há vazamento pelo seam do Barramento: o filtro por tag_id mora só em ws.py (um lugar), o dumb-pipe do recorder grava tudo verbatim de propósito (spec F1 §3.4-2), e a convenção quality 0/1/2 é definida uma vez em bus.py e só consumida, nunca reimplementada. O problema real da fatia é outro: `contracts_export.py` se declara fonte única dos payloads do `/ws` (comentário 'Débito 2+4... três espelhos TS mantidos à mão'), mas `_WS_MODELS` cobre só 4 dos 6 formatos que de fato trafegam no canal ao vivo — `OpcValue` (opc.values.*/calc.values) e `EventMessage` (events) ficam de fora, forçando duplicação manual de schema em pontos específicos do frontend (e, no caso de `EventMessage`, também no lado Python). São achados pontuais, não sistêmicos.

#### ARCH-05 — OpcValue (opc.values.*/calc.values) é o único payload do /ws sem contrato gerado — LeituraTag/lerOpcValues duplicam o schema à mão [Worth exploring · in-process]

**Arquivos:**
- `packages/ottima-core/src/ottima_core/bus.py:210-213 (class EventMessage)`
- `packages/ottima-core/src/ottima_core/schemas/events.py:9-13 (class EventOut, campos idênticos)`
- `packages/ottima-core/src/ottima_core/models/timeseries.py:33-40 (events_table — só os mesmos 5 campos, sem coluna extra que justifique EventOut à parte)`
- `services/api/src/ottima_api/routers/events.py:27-35 (GET /api/events usa EventOut)`
- `frontend/src/lib/api.ts:20 (EventOut = components["schemas"]["EventOut"], gerado do OpenAPI)`
- `frontend/src/app/CanalAoVivo.tsx:74-75 (export type EventMessage = EventOut — alias por comentário, não por tipo compartilhado)`
- `frontend/src/app/CanalAoVivo.tsx:294-301 (lerEvento valida os 5 campos à mão de novo)`

**Problema:** bus.py::EventMessage (payload do canal `events`) e schemas/events.py::EventOut (resposta REST de /api/events) declaram os mesmos 5 campos duas vezes em Python, e o frontend assume que são idênticos só por um comentário ("mesmo formato... bus §1.1"), sem nenhuma checagem mecânica dos dois lados.

**Evidência:**
- `packages/ottima-core/src/ottima_core/bus.py:210-213`
- `packages/ottima-core/src/ottima_core/schemas/events.py:9-13`
- `packages/ottima-core/src/ottima_core/models/timeseries.py:33-40`
- `services/api/src/ottima_api/routers/events.py:27-35`
- `frontend/src/app/CanalAoVivo.tsx:74-75,294-301`

**Antes (estrutura):** bus.py::EventMessage{ts,severity,origin,message,payload} --publish_event()--> Redis `events` --ChannelListener--> ws.py::_dispatch_events [envelope wrap] --WS--> CanalAoVivo.tsx. Em paralelo: schemas/events.py::EventOut{ts,severity,origin,message,payload} (classe Python INDEPENDENTE, mesmos 5 campos) --GET /api/events--> openapi.json --openapi-typescript--> api-types.ts::components.schemas.EventOut --api.ts::EventOut--> CanalAoVivo.tsx:75 `type EventMessage = EventOut` (comentário, não tipo compartilhado) --lerEvento() valida de novo--> eventos[] --> AnnunciatorBar.tsx/EventsPage.tsx. Dois nós Python (EventMessage, EventOut) descrevem o mesmo formato sem aresta de código entre si — só doc.

**Depois (estrutura):** schemas/events.py deixa de declarar campos: `from ottima_core.bus import EventMessage as EventOut` (ou EventOut(EventMessage) sem novos campos). Um nó Python só; a aresta bus.py::EventMessage → schemas/events.py::EventOut → openapi.json → api-types.ts → CanalAoVivo.tsx::EventMessage fica explícita de ponta a ponta — o alias do frontend continua igual, mas agora aponta para uma cadeia de tipos real, não para uma promessa em comentário.

**Deletion test:** Apagar EventOut e apontar o endpoint REST direto para EventMessage concentra a definição do formato num module só, sem mover complexidade para nenhum outro lugar — events_table (models/timeseries.py:33-40) não tem coluna extra (nem id) que justificasse EventOut como uma view mais estreita da tabela; é duplicação genuína, não Postel's law.

**Superfície de teste:** Hoje: nada garante que EventOut e EventMessage tenham os mesmos campos — só o comentário em CanalAoVivo.tsx:74 e o docstring de schemas/events.py ("as mesmas 5 chaves do canal events"). Depois: um teste de igualdade de schema (`EventOut.model_json_schema() == EventMessage.model_json_schema()`, ou simplesmente a ausência de EventOut como classe própria) torna a divergência estruturalmente impossível em vez de depender de disciplina humana.

**Correção sugerida:** Fazer EventOut reusar EventMessage (import direto ou `EventOut = EventMessage`) em vez de redeclarar os 5 campos; o alias do frontend passa a depender de um único Pydantic model tanto para a leitura REST quanto para o payload do canal `events`.

**Ganhos:** locality: um module Python é dono do formato do evento, não dois · leverage: remove uma classe que existe só para espelhar cinco nomes de campo · elimina o risco de EventOut divergir de EventMessage numa mudança futura em qualquer um dos dois REST/WS sem o outro perceber · o alias EventMessage=EventOut no frontend deixa de depender do pipeline OpenAPI (que pode evoluir por motivos alheios ao canal WS) para descrever um formato que na verdade nasce no barramento

---

### Fatia — Contrato graph_json (TS ↔ Python)

O seam `graph_json` tem uma parte disciplinada e três pontos de risco real. Disciplinada: `validate.py` é o module profundo único da semântica (tags, exec_order, ciclo, MPC completo), e o espelho do editor (`motivoRecusa`/`avisosInversao` em graph.ts) é uma cópia PEQUENA e deliberadamente documentada ("aqui só vivem as três regras que o usuário sente na ponta do mouse... o servidor é a fonte da verdade") — não é um candidato, é validação otimista de UI feita corretamente, com o servidor sempre como árbitro final. O ponto fraco é a FORMA do contrato: `PORT_CONTRACTS`/`ws_payloads` já provam (2 adapters reais) que gerar TS a partir de `model_json_schema()` funciona, mas a forma dos campos de config por bloco (MvVar/CvVar/DvVar/MpcConfig etc.) continua reescrita à mão em `graph.ts`, e os DEFAULTS de compatibilidade retroativa desses mesmos campos são reescritos à mão de novo em `graphMpc.ts` — com uma divergência já provada (fixture stale com `du_max` em vez de `max_rate`, sem asserção sobre o valor resultante). O único caminho de escrita em `graph_json` fora do save da API (a migração de dados 0009) reescreve o contrato por chave de dicionário sem nunca validar contra `parse_graph`/`MpcConfig`, e não tem nenhum teste no repositório.

#### ARCH-06 — Node/config shape do graph_json gerado do Pydantic (fecha o mirror que PORT_CONTRACTS deixou de fora) [Strong · ports & adapters]

**Arquivos:**
- `packages/ottima-core/src/ottima_core/contracts_export.py:210-218`
- `packages/ottima-core/src/ottima_core/flowgraph/mpc_config.py:89-148`
- `frontend/src/lib/contracts.gen.ts:1-4`
- `frontend/src/features/flows/graph.ts:235-333`
- `frontend/scripts/generate-contracts.mjs:58-66,124-130`

**Problema:** A forma dos campos de config de cada bloco (MvVar/CvVar/ConstraintVar/DvVar/MpcConfig, ScriptConfig, FuzzyConfig, TfsConfig, PidConfig) é declarada uma vez em Pydantic e reescrita à mão como interface TypeScript em graph.ts, sem nenhum mecanismo automatizado ligando as duas, apesar de o pipeline de geração (contracts_export.py -> generate-contracts.mjs) já existir e já cobrir PORT_CONTRACTS e ws_payloads com o mesmo model_json_schema().

**Evidência:**
- `packages/ottima-core/src/ottima_core/contracts_export.py:210-218 (_WS_MODELS/build_contracts já geram via model_json_schema())`
- `packages/ottima-core/src/ottima_core/flowgraph/mpc_config.py:89-148 (MvVar completo, canônico)`
- `frontend/src/features/flows/graph.ts:235-333 (VariavelMv..DadosMpc hand-typed, comentário 'espelho de MpcConfig')`
- `frontend/scripts/generate-contracts.mjs:58-66 (interfaceDe já genérico, pronto para reuso)`
- `frontend/src/lib/contracts.gen.ts:1-4 ('GERADO — não editar' mas escopo limitado a PORT_CONTRACTS/ws_payloads)`

**Antes (estrutura):** MpcConfig/ScriptConfig/FuzzyConfig/TfsConfig/PidConfig (mpc_config.py, parse.py — canônico) --[cópia manual, sem checagem]--> VariavelMv/VariavelCv/VariavelRestricao/VariavelDv/DadosMpc/DadosScript/... (graph.ts, TS hand-typed) E, em paralelo, --[segunda cópia manual]--> lista de chaves esperadas hardcoded no teste 'data sai com exatamente as chaves do contrato' (graph.check.ts). PORT_CONTRACTS/ws_payloads (contracts_export.py) já usam model_json_schema()+generate-contracts.mjs (2 adapters provados), mas o escopo gerado para em portas e mensagens do WS — a forma do `data`/`config` de cada nó nunca entra no gerador.

**Depois (estrutura):** MpcConfig/ScriptConfig/FuzzyConfig/TfsConfig/PidConfig --[model_json_schema(), mesmo mecanismo de _WS_MODELS]--> contracts_export.py::build_contracts() ganha uma chave 'node_configs' --[generate-contracts.mjs::interfaceDe, reusado sem mudança]--> contracts.gen.ts ganha VariavelMv/DadosMpc/... como interfaces geradas; graph.ts importa esses tipos em vez de declará-los; `npm run generate:contracts` (ou o build) falha quando Python muda forma sem o consumidor acompanhar.

**Deletion test:** Apagar os tipos manuais de graph.ts sem gerar substitutos quebra o build (o nó mpc perde toda tipagem) — mas mantê-los manuais também não concentra nada: é só uma segunda cópia da mesma forma, paga a cada mudança em mpc_config.py. Só GERAR a partir do Pydantic concentra a forma numa única declaração; a versão manual apenas MOVE a mesma informação para um segundo arquivo, sem ganho.

**Superfície de teste:** Hoje graph.check.ts testa o comportamento dos tipos hand-typed de graph.ts contra si mesmos — nenhum teste falha se DadosMpc divergir estruturalmente de MpcConfig, só se o TypeScript parar de compilar por outro motivo local. Depois, `npm run generate:contracts` passa a ser o teste de forma: ele falha (diff no repositório ou erro de tipo) sempre que mpc_config.py/parse.py mudar campo sem o gerador acompanhar, com um único `uv run python -m ottima_core.contracts_export` como fonte que os dois lados verificam.

**Correção sugerida:** Estender contracts_export.py::build_contracts() para incluir a JSON Schema de MvVar/CvVar/ConstraintVar/DvVar/MpcConfig/ScriptConfig/FuzzyConfig/TfsConfig/PidConfig (mesmo padrão de _WS_MODELS) e deixar o gerador (generate-contracts.mjs::interfaceDe, já genérico) materializar essas interfaces em contracts.gen.ts, substituindo os tipos manuais de graph.ts por imports do arquivo gerado.

**Ganhos:** Uma interface gerada, zero mirrors manuais · Pydantic vira profundidade real, TS raso · Teste: geração falha se forma diverge · Leverage: reusa pipeline já provado 2x · Locality: forma do nó em Python

---

#### ARCH-07 — Defaults de compatibilidade retroativa duplicados à mão entre Pydantic e os 12 leitores de graphMpc.ts — já com divergência provada [Strong · ports & adapters]

**Arquivos:**
- `frontend/src/features/flows/mpc/graphMpc.ts:140-200`
- `frontend/src/features/flows/graph.check.ts:591-628`
- `packages/ottima-core/src/ottima_core/flowgraph/mpc_config.py:144-148`

**Problema:** Cada Field(default=...) de MvVar/CvVar/ConstraintVar/DvVar em mpc_config.py tem um espelho hand-typed em graphMpc.ts (lerVariavelMv e as demais ler*), justificado só por comentário pt-BR ('mesmos defaults do servidor'), e a prova de que isso já divergiu é o próprio fixture de retrocompat do MPC em graph.check.ts:611, que ainda usa a chave pré-rename `du_max` em vez de `max_rate` e nunca assere o valor de `max_rate` resultante — hoje um regresso que zera `max_rate` (uma MV perdendo taxa máxima de variação, campo com peso de segurança) passaria pelo test_surface inteiro sem ser notado, porque `lerVariavelMv` (graphMpc.ts:157) não tem fallback para `du_max` e só sabe defaultar `max_rate` para 0.

**Evidência:**
- `frontend/src/features/flows/mpc/graphMpc.ts:156-160 (max_rate sem fallback para du_max, comentário citando 'defaults do servidor' sem checagem)`
- `frontend/src/features/flows/graph.check.ts:591-628 (fixture de retrocompat do MPC, linha 611 com du_max stale, sem asserção de max_rate)`
- `packages/ottima-core/src/ottima_core/flowgraph/mpc_config.py:144-148 (max_rate obrigatório, du_min/move_weight com Field(default=...) canônico)`

**Antes (estrutura):** mpc_config.py Field(default=...) por campo (canônico) --[lido uma vez, virou comentário pt-BR, nunca checado]--> graphMpc.ts: 12 funções ler*() (lerVariavelMv, lerVariavelCv, lerVariavelRestricao, lerVariavelDv) cada uma reescrevendo o mesmo literal por conta própria. Em paralelo, graph.check.ts:591-628 mantém UMA TERCEIRA cópia da forma pré-feature como fixture de teste — e essa cópia já ficou desatualizada (`du_max` sobrevive na linha 611 embora o campo real seja `max_rate` desde a migração 0009); a asserção do teste nunca olha para `max_rate`, então a terceira cópia diverge da segunda sem que nada acuse.

**Depois (estrutura):** mpc_config.py Field(default=...) --[model_json_schema() emite 'default' por propriedade, mesmo gerador do ARCH-06]--> uma tabela de defaults gerada em contracts.gen.ts; graphMpc.ts::ler*() lê dessa tabela em vez de literal hand-typed; graph.check.ts monta seus fixtures de retrocompat a partir da MESMA tabela (defaults esperados), então um Field(default=...) alterado em Python força a atualização do fixture e da asserção juntos — divergência vira falha de teste, não silêncio.

**Deletion test:** Apagar as funções ler*() de retrocompat só MOVE a decisão de default para o chamador (algum componente React reimplementaria 'se ausente, use X') — não concentra nada, porque a origem da verdade (Field(default=...) do Pydantic) continua fora do alcance do TypeScript. Só GERAR os defaults a partir de mpc_config.py concentra: mudar um Field(default=...) no Python passa a ser a única edição necessária para os dois lados concordarem.

**Superfície de teste:** Hoje as 12 funções ler*() são testadas indiretamente por ida-e-volta em graph.check.ts, mas os defaults nunca são comparados contra nada — o teste de retrocompat do MPC (graph.check.ts:592-628) nem contém a chave `max_rate` no fixture nem na asserção. Depois, os defaults vêm de uma tabela gerada e o mesmo teste passa a afirmar o valor resultante de `max_rate` (ou qualquer outro campo) contra essa tabela, fechando o buraco que hoje deixa um regresso silencioso passar.

**Correção sugerida:** Gerar uma tabela de defaults a partir do campo 'default' que model_json_schema() já emite por propriedade (mesmo pipeline do ARCH-06) e trocar os literais hand-typed de graphMpc.ts por leituras dessa tabela, corrigindo de quebra o fixture stale de graph.check.ts:611 e adicionando a asserção de `max_rate` que falta hoje.

**Ganhos:** Defaults concentrados: um Field, uma origem · Teste fixa max_rate, não só chaves · Locality: retrocompat sai de 12 funções · Interface gerada elimina comentário não verificado

---

#### ARCH-08 — Migração de dados sobre graph_json (0009) reescreve o contrato sem nunca validá-lo via parse_graph — único caminho de escrita não testado [Worth exploring · in-process]

**Arquivos:**
- `packages/ottima-core/alembic/versions/0009_mpc_max_rate.py:10-56`
- `packages/ottima-core/src/ottima_core/flowgraph/__init__.py:69-76`

**Problema:** 0009_mpc_max_rate.py::_migrar lê, muta (`du_max` -> `max_rate`, spread por multiplicador e ts_seconds) e regrava `graph_json` direto por chave de dicionário, sem nunca chamar `parse_graph`/`MpcConfig` (os únicos módulos que hoje conhecem a forma válida do contrato) e sem nenhum teste no repositório — é o único caminho de escrita em `graph_json` que existe fora da validação de save da API, e uma migração futura com o mesmo padrão herdaria o mesmo ponto cego.

**Evidência:**
- `packages/ottima-core/alembic/versions/0009_mpc_max_rate.py:10-14 (imports: sem flowgraph, sem parse_graph/MpcConfig)`
- `packages/ottima-core/alembic/versions/0009_mpc_max_rate.py:29-56 (_migrar: surgery por chave, _regravar sem validação)`
- `packages/ottima-core/src/ottima_core/flowgraph/__init__.py:69-76 (parse_graph/validate_graph exportados publicamente, disponíveis mas não importados pela migração)`

**Antes (estrutura):** flows.graph_json (JSONB) <--[write path 1: PUT /flows, validado]-- parse_graph()+MpcConfig (flowgraph/parse.py, mpc_config.py); flows.graph_json (JSONB) <--[write path 2: alembic upgrade, NÃO validado]-- 0009_mpc_max_rate.py::_migrar (surgery direta por chave: mv['max_rate']=mv.pop('du_max')/(ts*mult)), sem chamar parse_graph nem MpcConfig, sem teste algum no repositório.

**Depois (estrutura):** flows.graph_json (JSONB) <--[write path 1: PUT /flows]-- parse_graph()+MpcConfig; flows.graph_json (JSONB) <--[write path 2: alembic upgrade]-- _migrar muta E então chama parse_graph(graph) (mesma função do write path 1) antes de _regravar — as duas escritas convergem na mesma checagem de forma, e um fixture de teste prova isso para o caso já ocorrido (du_max->max_rate).

**Deletion test:** Não há o que deletar hoje — o ponto é o oposto: a AUSÊNCIA de validação na migração já é o estado atual. Rodar `_migrar` sem validação MOVE o risco de corrupção de `graph_json` para 'descoberto em produção pelo flow-runtime ou pelo próximo save', em vez de CONCENTRAR a checagem no único ponto em que o dado muda de forma (a própria migração).

**Superfície de teste:** Hoje nenhum teste cobre `_migrar` (busca por '0009'/'mpc_max_rate' em packages/ottima-core/tests/ não retorna nada); a única garantia é revisão humana no momento do merge. Depois, um teste de migração alimenta um fixture de `graph_json` pré-rename, roda `_migrar`, e afirma que `parse_graph(resultado)` não levanta — cobrindo o único caminho de escrita em `graph_json` que hoje escapa de toda validação automatizada.

**Correção sugerida:** Chamar `parse_graph(graph)` (ou, por nó `mpc`, `MpcConfig.model_validate`) depois da mutação e antes de `_regravar`, e acrescentar um teste de migração com um fixture pré-rename que prova que o resultado parseia limpo — a mesma disciplina que toda escrita via API já segue hoje.

**Ganhos:** Migração ganha profundidade: valida ao escrever · Locality: única checagem de forma reutilizada · Teste cobre o caminho hoje cego · Leverage: reusa parse_graph já existente

---

### Fatia — Execução de Flows e contrato de Bloco

A fatia de execução de Flows é estruturalmente saudável no eixo que mais importa: Block é uma interface fina e deep — 8 dos 9 tipos de Bloco (OPC-Read, OPC-Write, Python-Script, TFS, PID, Kalman, Filtro 1ª ordem, Fuzzy) passam pelo mesmo step()/reset() sem tratamento especial fora de blocks/; o único if/match por tipo fora de blocks/ é o switch de instanciação em definition.py (_instantiate), que é o ponto único e legítimo de fábrica, não sprawl. O seam entre 'Bloco MPC' e o solver MPC (mpc/builder.py, mpc/worker.py, target_calculation/ssto.py) está exatamente onde a documentação do módulo diz que deveria estar — nenhuma matemática do MPC vazou para blocks/mpc.py. Os pontos de fricção reais são conhecidos e em parte já documentados pelo próprio time: (1) o MPC, por exigir ciclo de vida próprio (host, arme, transplante de estado), se expressa hoje como isinstance(MpcBlock) espalhado por 4 arquivos do supervisor em vez de uma interface nomeada; (2) o isolamento intra-partição entre Flows do mesmo event loop depende de disciplina de implementação de bloco — um defeito aberto e ADMITIDO via teste xfail(strict=True) permanente, não uma lacuna escondida; (3) blocks/mpc.py cresceu para 1133 linhas concentrando seis preocupações de bloco (não de solver) que hoje mudam juntas; e (4) o custo de 37 min da suíte tem uma causa de interface concreta: build_mpc() funde montagem estrutural barata com compilação IPOPT cara numa função só.

#### ARCH-09 — Nomear o seam de 'Bloco com ciclo de vida próprio' em vez de checar MpcBlock por isinstance [Worth exploring · in-process]

**Arquivos:**
- `services/flow-runtime/src/ottima_flow_runtime/definition.py:47,125,133-134,157,336,341`
- `services/flow-runtime/src/ottima_flow_runtime/supervisor.py:57,609-610`
- `services/flow-runtime/src/ottima_flow_runtime/supervisor_mpc.py:30,72,93,466`
- `services/flow-runtime/src/ottima_flow_runtime/supervisor_resume.py:33,132,550`
- `services/flow-runtime/src/ottima_flow_runtime/mpc_arming.py:32-47`

**Problema:** O supervisor descobre que um Bloco precisa de ciclo de vida próprio (host de processo, arme/confirmação, transplante de estado no hot-swap) checando isinstance(block, MpcBlock) em pelo menos 8 pontos de 4 arquivos diferentes, em vez de consultar uma interface nomeada para essa capacidade.

**Evidência:**
- `services/flow-runtime/src/ottima_flow_runtime/definition.py:125`
- `services/flow-runtime/src/ottima_flow_runtime/supervisor.py:609-610`
- `services/flow-runtime/src/ottima_flow_runtime/supervisor_mpc.py:72,93`
- `services/flow-runtime/src/ottima_flow_runtime/supervisor_resume.py:132,550`
- `services/flow-runtime/src/ottima_flow_runtime/definition.py:336,341`

**Antes (estrutura):** definition.py, supervisor.py, supervisor_mpc.py, supervisor_resume.py e mpc_arming.py cada um importa MpcBlock e testa isinstance(block, MpcBlock) — ou node.type == "mpc" em definition.py — antes de acessar host/local_remote/pid_bindings/auto_arm_blocked_reason: 8 pontos de acoplamento ao tipo concreto espalhados por 5 arquivos, cada um decidindo de novo 'este Bloco tem ciclo de vida próprio?'.

**Depois (estrutura):** Uma interface nomeada (o conjunto host/local_remote/pid_bindings/auto_arm_blocked_reason que MpcBlock já implementa, só sem nome formal) substitui os 8 isinstance — supervisor.py, definition.py, supervisor_mpc.py, supervisor_resume.py e mpc_arming.py passam a perguntar 'este Bloco satisfaz a interface de ciclo de vida?' via o mapa StagedDefinition.hosts (que definition.py já constrói no único ponto de fábrica) em vez de isinstance repetido em cada consumidor.

**Deletion test:** Substituir os isinstance espalhados por uma interface nomeada não elimina a complexidade — ela se CONCENTRA num único ponto (a definição da interface + o filtro que a fábrica já faz uma vez), que é o sinal de bom candidato: hoje a mesma pergunta ('isto é MPC?') está duplicada 8 vezes; depois está numa definição só, consumida por referência.

**Superfície de teste:** Hoje: testar supervisor_mpc.py exige um MpcBlock real ou um objeto que passe em isinstance (impossível de dublar sem herdar a classe concreta) — o construtor de MpcBlock exige host/snapshot/publish/write_opc/emit_event (blocks/mpc.py:117-131). Depois: um duplo que só implementa a interface nomeada, sem herdar MpcBlock e sem host real, basta para exercitar mpc_command/_transition_local_remote — reduz o acoplamento dos testes de orquestração ao construtor pesado do Bloco.

**Correção sugerida:** Extrair um protocolo estrutural explícito (as properties que MpcBlock já expõe — host, local_remote, ts_mpc, mv_status, pid_bindings, auto_arm_blocked_reason() — já SÃO essa interface, só falta nomeá-la) e trocar os isinstance por checagem de capacidade ou por um mapa que definition.py já monta (StagedDefinition.hosts) em vez de reperguntar o tipo em cada consumidor.

**Ganhos:** Locality: 8 isinstance viram 1 interface · Depth: MPC especial some do supervisor · Leverage: 2º bloco com host se encaixa · Teste: duplo sem herdar MpcBlock real · Interface nomeada, não classe concreta

---

#### ARCH-10 — Dividir blocks/mpc.py por responsabilidade interna — o seam com o solver MPC já está certo, não mexer nele [Worth exploring · in-process]

**Arquivos:**
- `services/flow-runtime/src/ottima_flow_runtime/blocks/mpc.py:112-390 (construção/reset/transplante)`
- `services/flow-runtime/src/ottima_flow_runtime/blocks/mpc.py:396-745 (varredura/dispatch/fail-action)`
- `services/flow-runtime/src/ottima_flow_runtime/blocks/mpc.py:750-883 (saída por modo/bumpless)`
- `services/flow-runtime/src/ottima_flow_runtime/blocks/mpc.py:888-955 (eventos)`
- `services/flow-runtime/src/ottima_flow_runtime/blocks/mpc.py:960-1133 (comandos/estado publicado)`

**Problema:** blocks/mpc.py tem 1133 linhas e mistura, numa única implementation, seis preocupações de Bloco (não de solver): cadência+dispatch, máquina de dois eixos de modo, resolução de saída/bumpless por disponibilidade de MV, debounce de fail-action (RF-613), auditoria de eventos e construção do estado publicado — é o arquivo mais quente do backend (9 commits) porque qualquer uma dessas seis muda ali, no mesmo objeto.

**Evidência:**
- `services/flow-runtime/src/ottima_flow_runtime/blocks/mpc.py:1-33 (docstring 'Bloco fino')`
- `services/flow-runtime/src/ottima_flow_runtime/blocks/mpc.py:112`
- `services/flow-runtime/src/ottima_flow_runtime/blocks/mpc.py:392-394,746-748,884-886,956-958,1057-1059 (marcadores de seção)`
- `services/flow-runtime/tests/test_mpc_block.py:1-13 (docstring: TDD estrito, host/snapshot falsos)`

**Antes (estrutura):** blocks/mpc.py:112-1133 — uma classe MpcBlock com seis regiões marcadas por comentário (Varredura, Saída por modo, Eventos, Comandos, Estado publicado) mais construção/transplante. Todas leem/escrevem o mesmo conjunto de atributos privados (_plan, _mv_last, _mv_manual, _sp, _mv_status, _fail_streak/_fail_pending), então uma mudança em qualquer região arrisca as outras cinco só por estarem no mesmo objeto.

**Depois (estrutura):** MpcBlock.step() continua sendo o único ponto que FlowTask._scan() chama (Block, deep) e orquestra a sequência, mas delega a sub-módulos: resolução de saída/bumpless e debounce de fail-action (RF-613) viram objetos pequenos com o estado que JÁ é auto-contido (_fail_streak/_fail_pending/_fail_fired/_simulacao_desde não tocam _plan/_mv_last hoje) — cada um testável com samples+mv_status sintéticos, sem host/snapshot/publish.

**Deletion test:** Extrair o debounce de fail-action (RF-613) para um module próprio CONCENTRA a complexidade num objeto pequeno e testável — hoje ela está espalhada entre _avaliar_fail_actions/fail_pending/pop_fail_pending, misturada com o resto do step(); não a move para outro lugar igualmente confuso, porque o consumidor (MpcOrchestrator._start_watchdog) já consome via pop_fail_pending() e essa fronteira de consumo não muda.

**Superfície de teste:** Hoje: test_mpc_block.py já usa host/snapshot falsos (não paga do-mpc real, ver docstring do arquivo), mas testar SÓ o debounce de fail-action ainda exige montar um MpcBlock inteiro com todas as demais dependências injetadas. Depois: o debounce testável isoladamente, sem MpcBlock nenhum — reduz o que cada cenário de teste precisa montar.

**Correção sugerida:** Extrair sub-módulos coesos (ex.: resolução de saída/bumpless, debounce de fail-action) que MpcBlock passa a compor, preservando intocados a interface Block e o seam já correto com mpc/worker.py, mpc/builder.py e target_calculation/ssto.py — a matemática do MPC continua fora do Bloco, exatamente como a docstring do módulo já promete.

**Ganhos:** Depth: MpcBlock fica fino de verdade · Locality: fail-action testável sem step() · Leverage: 9 commits se distribuem · Menos motivos de mudar 1 arquivo · Resolução de saída testável isolada

---

#### ARCH-11 — Isolamento entre Flows do mesmo event loop depende de disciplina de Bloco, não de estrutura [Strong · in-process]

**Arquivos:**
- `services/flow-runtime/src/ottima_flow_runtime/scheduler.py (FlowTask._scan, _run)`
- `services/flow-runtime/src/ottima_flow_runtime/blocks/base.py (contrato 'nenhum bloco bloqueia o loop')`
- `services/flow-runtime/src/ottima_flow_runtime/blocks/fuzzy.py (engine.process() inline)`
- `services/flow-runtime/tests/test_isolamento_temporal.py`
- `docs/adr/ADR-004-loops-vivos-asyncio-sem-celery.md`

**Problema:** Dentro de uma partição, todo Flow roda como task asyncio no mesmo event loop; nada estrutural impede um Bloco (Fuzzy grande, PID, TFS, Filtro) de gastar tempo síncrono inline e furar a fronteira de varredura de outro Flow — o próprio time já documentou isso como defeito aberto, com um teste xfail(strict=True) permanente em vez de uma resolução estrutural.

**Evidência:**
- docs/adr/ADR-004-loops-vivos-asyncio-sem-celery.md (seção 'Implementação da partição', 'Flows da MESMA partição continuam dividindo um event loop')
- services/flow-runtime/src/ottima_flow_runtime/blocks/fuzzy.py ('# ponytail: process() inline (sub-ms em engine típico); mover a executor se overrun aparecer')
- services/flow-runtime/tests/test_isolamento_temporal.py (docstring + xfail(strict=True))
- services/flow-runtime/src/ottima_flow_runtime/blocks/base.py (docstring: 'nenhum bloco pode bloquear o event loop (ADR-004)')

**Antes (estrutura):** FlowTask._scan() (scheduler.py) chama await block.step(...) sequencialmente para cada bloco da tupla; se um Bloco (ex.: FuzzyBlock.engine.process(), blocks/fuzzy.py, comentário 'ponytail: process() inline... mover a executor se overrun aparecer') gasta 1s de CPU síncrona dentro do await, TODO o event loop do processo fica preso — os demais Flows da MESMA partição perdem fronteiras (medido: 5 de 15 varreduras em test_isolamento_temporal.py, hoje xfail permanente).

**Depois (estrutura):** _scan() mede o tempo de CADA block.step() individualmente (hoje só mede scan_ms agregado da varredura inteira) e compara contra um orçamento por bloco; o bloco que estoura emite um evento nomeado (ex.: block_overrun com block_id) — o operador e o CI enxergam QUAL bloco furou a fronteira, e test_isolamento_temporal.py deixa de ser xfail e vira teste de regressão do orçamento por bloco.

**Deletion test:** Não há module a deletar aqui — é a ausência de um mecanismo que concentra risco. Inversamente: remover o teste xfail sem adicionar a medição estrutural não faz o defeito desaparecer, só apaga a única prova viva de que ele existe.

**Superfície de teste:** Hoje: test_isolamento_temporal.py PROVA o defeito com xfail(strict=True) — falharia (travando a suíte) se alguém 'consertasse' sem querer, em vez de simplesmente avisar. Depois: o mesmo teste vira verde, e um teste novo (bloco que gasta 200ms sozinho) confirma que o orçamento por bloco emite o evento certo — sem precisar de dois processos para provar isolamento intra-partição, ao contrário de test_isolamento_particao.py, que continua sendo o teste certo para o isolamento ENTRE partições.

**Correção sugerida:** Sem reabrir asyncio-sem-Celery nem a partição por processo (ADR-004, decididos): fechar a lacuna intra-partição dando ao scheduler uma forma estrutural de medir o tempo síncrono de cada block.step() individualmente e emitir um evento nomeando o Bloco culpado quando ele estoura um orçamento — hoje o contrato 'nenhum bloco bloqueia' vive só na docstring de blocks/base.py e num comentário ponytail em fuzzy.py.

**Ganhos:** Fecha xfail(strict=True) permanente · Estrutura substitui convenção de review · Locality: overrun aponta o bloco culpado · Reusa time.monotonic() já medido em scan_ms · Sem 2ª stack: mesma partição, novo evento

> **Atenção ADR** — ADR-004: não reabre 'asyncio sem Celery' nem a decisão de particionar por processo — as duas seguem de pé. A proposta fecha a lacuna que a própria revisão de 2026-08-15 do ADR-004 já documenta como aberta ('blocks/base.py proíbe bloquear o loop por contrato, mas nada o impede por construção') dentro de uma partição, sem trocar o modelo de concorrência.

---

#### ARCH-12 — build_mpc() funde montagem estrutural com compilação do solver — testes estruturais pagam IPOPT sem precisar [Strong · ports & adapters]

**Arquivos:**
- `services/flow-runtime/src/ottima_flow_runtime/mpc/builder.py:123-386`
- `services/flow-runtime/src/ottima_flow_runtime/mpc/host.py (worker_target injetável)`
- `services/flow-runtime/tests/test_mpc_builder.py (16 chamadas de build_mpc)`
- `services/flow-runtime/tests/test_mpc_worker.py (spawn real por teste)`
- `docs/adr/ADR-022-bloco-tfs-simulacao.md`

**Problema:** build_mpc() (mpc/builder.py) monta os metadados estruturais do Bloco MPC (nomes de tvp, ordem de MVs, contagem de estados) E chama mpc.setup() — compilação IPOPT/CasADi — na MESMA função; 4 dos 16 build_mpc() em test_mpc_builder.py (linhas 136, 161, 327, 507) só leem built.mpc.model.n_x ou built.utarget_tvp_name, nunca resolvem, mas pagam o custo do solver inteiro porque não há seam entre 'montar' e 'compilar'.

**Evidência:**
- `services/flow-runtime/src/ottima_flow_runtime/mpc/builder.py:123-124`
- `services/flow-runtime/src/ottima_flow_runtime/mpc/builder.py:267,361`
- `services/flow-runtime/tests/test_mpc_builder.py:136,161,327,507`
- `services/flow-runtime/tests/test_mpc_worker.py:1-20`
- docs/adr/ADR-022-bloco-tfs-simulacao.md

**Antes (estrutura):** build_mpc(config, ts_flow) -> BuiltMpc monta o Model simbólico (barato) e chama mpc = MPC(model); mpc.setup() (IPOPT/CasADi nlpsol, caro) numa função só (builder.py:123-386, setup em 361). test_mpc_builder.py chama build_mpc() 16 vezes; 4 delas só leem metadados e nunca resolvem, mas pagam o setup() de qualquer forma. test_mpc_worker.py faz spawn() de processo real por teste só para exercitar o protocolo do Pipe (ready/SolveRequest/SolveResult).

**Depois (estrutura):** build_mpc() vira _assemble_model(config, ts_flow) -> metadados [sem IPOPT] seguido de _compile_solver(model, metadados) -> BuiltMpc [com IPOPT]. Testes de metadados chamam só _assemble_model; testes de comportamento de solve continuam chamando build_mpc() completo, sem mudança. worker_target leve (protocolo puro, sem do-mpc real) cobre os testes que hoje só provam 'responde a um 2º pedido depois de erro', sem pagar import a frio de casadi/do-mpc a cada spawn.

**Deletion test:** Separar montagem/compilação CONCENTRA: hoje a pergunta 'este teste verifica estrutura ou verifica solve?' é respondida implicitamente por qual asserção o teste faz DEPOIS de pagar o mesmo custo fixo; separando, o custo de cada teste passa a corresponder ao que ele realmente verifica — não move a complexidade do solver para outro lugar, do-mpc/IPOPT continua um bloco só, intocado dentro de _compile_solver.

**Superfície de teste:** Hoje: build_mpc() é a ÚNICA porta de entrada — nenhum teste de metadados escapa do mpc.setup(). TFS (blocks/tfs.py) e OPC-Read/OPC-Write (blocks/opc_read.py, opc_write.py) já são dois adapters reais atrás da MESMA interface Block, deliberadamente, para fechar a malha MPC↔planta sem hardware (ADR-022: 'Malha fechada MPC↔TFS 100% dentro do sistema') — esse seam já é bom e deve ser preservado, não reinventado. Depois: metadados testáveis sem pagar setup(); a malha fechada MPC↔TFS continua sendo o caminho de teste de integração real, sem Timescale/Redis.

**Correção sugerida:** Separar a montagem do Model/metadados (pura, barata, symbolic CasADi sem nlpsol) da chamada mpc.setup() (compilação do solver) em duas funções costuradas por build_mpc(); testes puramente estruturais chamam só a primeira. mpc/host.py já tem um seam equivalente pronto (worker_target injetável, usado por harness_factory) que os testes de protocolo puro do worker (test_mpc_worker.py) hoje não aproveitam — cada teste paga um spawn real reimportando casadi/do-mpc.

**Ganhos:** Testes estruturais sem pagar IPOPT · Seam já existe em MpcHost, falta no builder · Preserva TFS-vs-OPC como adapter real · Não toca a matemática do solver · 37 min tem causa de interface, não só infra

---

### Fatia — API e ciclo de vida do Projeto

A fatia de API é razoavelmente saudável: routers finos por recurso, JWT/RBAC isolados em duas funções de ~10 linhas (deps.py), e o export de Projeto delega corretamente a montagem do Arquivo de projeto para `montar_bundle` (puro, em ottima_core.portability). Os dois pontos fracos recorrentes ficam em `projects.py`: a cascata de ativação (ADR-017) e a aplicação do bundle no import (ADR-012, camada 5 não-nomeada) vivem inteiras dentro do handler HTTP, sem par testável em ottima_core — ao contrário do export, que já tem essa simetria. A regra 'um projeto ativo' (ADR-017) é de fato profunda no banco (índice parcial Postgres), mas a orquestração da transação (quem desativa, quais flows param, quando emitir evento) é raso e só alcançável via HTTP. Não existe nenhum seam de persistência (nenhuma classe Repository/Protocol em todo `ottima_core`/`ottima_api`) — toda a suíte de testes, incluindo esta fatia, depende de Timescale real via testcontainers (root `conftest.py`); isso é defensável para o índice parcial `postgresql_where`, mas torna ainda mais valioso extrair as DECISÕES de negócio (não a persistência) para funções puras testáveis sem container. RBAC (ADR-015) está bem decidido (uma única checagem em `deps.py:53-60`), mas a FIAÇÃO de qual papel cada rota exige está repetida em ~50 pontos de declaração espalhados por 11 routers, sem um manifesto único auditável — leverage baixo na declaração, não na lógica.

#### ARCH-13 — Cascata de ativação de Projeto (ADR-017) sem par puro em ottima_core [Strong · in-process]

**Arquivos:**
- `services/api/src/ottima_api/routers/projects.py:143-190`
- `packages/ottima-core/src/ottima_core/models/project.py:9-24`
- `services/api/tests/test_projects.py:20-25,63-90,110-146`
- `conftest.py:1-33`

**Problema:** A decisão de negócio do ADR-017 (quem desativa, quais flows param, quando publicar o evento) vive inteira dentro de `activate_project`, misturada com SQL e I/O do FastAPI, sem função em ottima_core que a isole.

**Evidência:**
- `services/api/src/ottima_api/routers/projects.py:143-190`
- `packages/ottima-core/src/ottima_core/models/project.py:17-24`
- `services/api/tests/test_projects.py:20-25`
- `conftest.py:24-32`

**Antes (estrutura):** projects.py:activate_project() concentra, numa única função de handler: leitura do projeto, guarda de `ja_era_o_ativo`, UPDATE Project(is_active=False) em massa, set is_active=True, UPDATE Flow(desired_state) condicional, commit, e publish_event condicional — tudo em ~45 linhas inline; nenhum node em ottima_core participa da decisão; os únicos testes chegam via `client.post('/activate')` contra Timescale real.

**Depois (estrutura):** ottima_core ganha uma função pura tipo `decidir_ativacao(projeto_atual_ativo: bool) -> DecisaoAtivacao{parar_flows: bool, emitir_evento: bool}`; o router chama essa função, depois executa só os 2 UPDATEs e o publish_event que ela indicar. Teste unitário cobre a decisão sem sessão de banco; o teste HTTP existente vira teste fino de transporte/serialização.

**Deletion test:** Deletar hoje o bloco de decisão dentro de activate_project apaga a ÚNICA implementação da regra ADR-017 — não move para lugar nenhum, porque não existe outro lugar. Extrair para ottima_core CONCENTRA a decisão numa função nomeada e reusável, em vez de mantê-la dissolvida em SQL condicional dentro do handler.

**Superfície de teste:** Hoje: só via HTTP (`client.post(f'/api/projects/{id}/activate')`) + Timescale real via testcontainers (test_projects.py, conftest.py raiz) — nenhum teste unitário da regra isolada. Depois: a função de decisão é testável com um booleano de entrada, sem sessão nem container; o teste HTTP passa a cobrir só orquestração/transporte.

**Correção sugerida:** Extrair a decisão pura (dado o projeto atual e o alvo, decidir os updates e se emite evento) para uma função em ottima_core (ex.: `ottima_core.projects`), deixando o router só executar os UPDATEs e o publish_event conforme o resultado.

**Ganhos:** Locality: regra sai do shell HTTP · Depth: função pura, interface mínima · Leverage: reuso futuro por CLI/seed · Testes: sem Timescale, sem client HTTP · Interface: contrato explícito da decisão

---

#### ARCH-14 — Import de bundle sem par de `montar_bundle`: assembly ORM preso no router [Strong · in-process]

**Arquivos:**
- `services/api/src/ottima_api/routers/projects.py:385-483`
- `services/api/src/ottima_api/routers/projects.py:494-531`
- `packages/ottima-core/src/ottima_core/portability/bundle.py:56-141`
- `packages/ottima-core/src/ottima_core/portability/bundle.py:144-206`

**Problema:** Export delega a montagem do Arquivo de projeto para `montar_bundle` (puro, testável sem banco); import não tem função simétrica — a tradução ProjectBundle→ORM (Project, OpcConnection, Tag OPC, Tag calculada, CalculatedTag, CalculatedTagInput, id-mapping) é ~100 linhas inline em `import_project`, intercaladas com `db.flush()` e captura de `IntegrityError`.

**Evidência:**
- `services/api/src/ottima_api/routers/projects.py:385-421`
- `services/api/src/ottima_api/routers/projects.py:494-531`
- `packages/ottima-core/src/ottima_core/portability/bundle.py:56-64`
- `packages/ottima-core/src/ottima_core/portability/bundle.py:144-155`

**Antes (estrutura):** export_project chama `montar_bundle(project, connections, tags, ...) -> ProjectBundle`, puro e testável isolado (bundle.py:56). import_project, que deveria ser o espelho, monta manualmente `Project`/`OpcConnection`/`Tag`/`CalculatedTag`/`CalculatedTagInput` linha a linha dentro do handler (projects.py:385-483), intercalado com `await db.flush()` para obter ids — tradução de dados e I/O de persistência fundidas na mesma função de 200+ linhas junto com a camada 4 (parse/validate de grafo).

**Depois (estrutura):** `ottima_core.portability.aplicar_bundle(bundle, nome_final)` devolve a árvore de objetos ORM não-persistidos (ou um plano de inserção com as mesmas relações name→id que `ref_por_id` já resolve no sentido inverso) na forma simétrica a `montar_bundle`; `import_project` vira uma casca fina de HTTP+DB que chama `aplicar_bundle`, depois `db.add_all`/`flush` na ordem indicada, exatamente como `export_project` já é uma casca fina em torno de `montar_bundle`.

**Deletion test:** Deletar hoje o bloco de montagem ORM do import_project apaga a ÚNICA forma de aplicar um Arquivo de projeto ao banco — não move para lugar nenhum, porque não existe outro lugar; isso mostra que a lógica nunca foi extraída, não que seja dispensável. Extrair para ottima_core CONCENTRARIA a tradução bundle→ORM num módulo testável sem HTTP, restaurando a simetria que o export já tem.

**Superfície de teste:** Hoje: só testável via `POST /api/projects/import` com corpo JSON completo + Timescale real (test_projects_import.py) — nenhum teste unitário de 'esta BundleTag calculada vira esta CalculatedTag+CalculatedTagInput'. Depois: `aplicar_bundle` testável com um `ProjectBundle` de fixture, assertando os objetos ORM resultantes sem sessão nem flush; o teste HTTP passa a cobrir só a orquestração de camadas + persistência real.

**Correção sugerida:** Extrair em `ottima_core.portability` uma função simétrica a `montar_bundle` (ex.: `aplicar_bundle`) que receba o `ProjectBundle` já validado (camadas 1-3) e devolva a árvore de objetos ORM a inserir; o router só chama `db.add`/`flush` na sequência indicada e trata as exceções HTTP.

**Ganhos:** Simetria: import ganha seu montar_bundle · Depth: mapeamento sai do handler HTTP · Leverage: reuso por import via CLI futura · Testes: mapeamento sem flush nem sessão · Interface: router encolhe ~100 linhas

---

#### ARCH-15 — RBAC (ADR-015): decisão profunda em deps.py, fiação rasa repetida ~50x [Worth exploring · in-process]

**Arquivos:**
- `services/api/src/ottima_api/deps.py:53-60`
- `services/api/src/ottima_api/routers/projects.py:91,96,110,115,133,147,196,331`
- `services/api/src/ottima_api/routers/operate.py:264,286,314,457,526,546`
- `services/api/src/ottima_api/routers/certificates.py:24-25`
- `services/api/src/ottima_api/routers/users.py:14`

**Problema:** A checagem de papel (`user.role != 'admin'`) mora só em `require_admin`/`require_operator` (deps.py, 8 linhas) — profunda e correta — mas a DECLARAÇÃO de qual papel cada rota exige está repetida em ~50 pontos por 11 routers, sem nenhum lugar único onde auditar 'quem pode fazer o quê' do ADR-015.

**Evidência:**
- `services/api/src/ottima_api/deps.py:53-60`
- `services/api/src/ottima_api/routers/projects.py:91`
- `services/api/src/ottima_api/routers/projects.py:96`
- `services/api/src/ottima_api/routers/operate.py:264`
- `services/api/src/ottima_api/routers/certificates.py:25`

**Antes (estrutura):** 11 routers importam `require_admin`/`require_operator` de deps.py e anotam cada rota individualmente (`dependencies=[Depends(require_operator)]` em GETs, `user: User = Depends(require_admin)` em writes que precisam do ator) — ~50 pontos de declaração espalhados. 2 routers (certificates.py, users.py) já usam guard a nível de router porque toda rota deles tem o mesmo papel; `projects.py` documenta explicitamente que não pode fazer isso porque o papel varia rota a rota.

**Depois (estrutura):** Um mapeamento legível ao lado de cada router (ex.: lista de tuplas `(método, path, papel)`) usado para montar as `dependencies=[...]` ao registrar as rotas — a mesma checagem de `deps.py`, mas agora auditável num só lugar por arquivo em vez de decorators espalhados.

**Deletion test:** Deletar uma declaração isolada (ex.: um `Depends(require_operator)` esquecido) hoje só MOVE o buraco para 'nenhuma checagem nessa rota' silenciosamente — não há nada que concentre e valide a cobertura. Um manifesto único não elimina a checagem (que já é profunda), mas concentra a SUPERFÍCIE de auditoria, tornando uma rota sem guard um diff visível em vez de uma ausência silenciosa entre 50 decorators.

**Superfície de teste:** Hoje: RBAC é testado indiretamente, rota a rota, via requests HTTP com `admin_headers`/`operator_headers` (conftest.py) espalhados pelos testes de cada router — nenhum teste único que confirme 'toda rota tem o papel documentado no ADR-015'. Depois: um teste único poderia iterar o manifesto e comparar contra as rotas registradas no app, pegando esquecimentos que hoje só um 403 em produção revelaria.

**Correção sugerida:** Um manifesto único por router (tabela ou dict {método,path}->papel), lido para gerar as `dependencies=[...]` na hora de registrar as rotas, mantendo `require_admin`/`require_operator` como a única implementação da checagem — não muda a decisão, só concentra onde ela é declarada.

**Ganhos:** Leverage baixo: repetição sem tabela única · Interface: nenhum manifesto rota→papel · Locality: auditar ADR-015 exige grep manual · Depth: decisão já é profunda em deps.py · Testes: hoje cobertos rota a rota

---

### Fatia — opc-worker e adapters OPC-UA

O seam com asyncua está bem isolado da flow-runtime/API/frontend inteira — `ConnectionConfig`/`TagConfig` só carregam `node_id: str` puro, nunca um tipo de asyncua — mas dentro do próprio opc-worker o detalhe de asyncua (VariantType, DataValue/Variant, NodeId) vaza do module de sessão (`connection.py`) para o module de pipeline de escrita (`writes.py`), que constrói `ua.DataValue(ua.Variant(...))` e chama `client.get_node(...)` diretamente em vez de pedir uma escrita ao module de sessão; a interface entre os dois não é profunda. Existem dois adapters reais e simétricos — servidor de campo real e `tests/opcsim` (que também roda como container com certificado próprio nos cenários E2E) — e nenhum branch `if opcsim` mora em código de produção; a única pista de acoplamento é um comentário em `security.py` admitindo que a heurística de classificação de exceção (`TimeoutError` sob pinning ⇒ `cert_mismatch`) foi generalizada a partir da observação de um só adapter — especulativo, não concessão de fato. O estado do handshake do Watchdog por Flow (ADR-009) está corretamente isolado por `flow_id`, mas o handshake em si mora espalhado em três estruturas paralelas mantidas à mão — `ConnectionSnapshot.flow_watchdog_alive` (`state.py`) e `_flow_failure_pending`/`_flow_gate_generation` (`connection.py`) — sincronizadas em pelo menos seis pontos de mutação diferentes; o próprio código, em `writes.py`, admite em comentário que depender da sincronia entre elas seria uma 'invariante implícita entre dois módulos'. Em contraste, a máquina de estados da CONEXÃO (`ConnectionState` + `_session_open`/`_failure_pending`/`_generation`) é explícita e mora inteira dentro de um module só — saudável; LOCAL/REMOTO fica corretamente fora do opc-worker (ADR-006 respeitado, sem vazamento); e a Pendência tem lugar único no Python (`ottima_core.portability.pendencias.pendencias_da_conexao`), espelhada deliberadamente no frontend — fora desta fatia, então não é candidato aqui.

#### ARCH-16 — Interface de escrita não esconde asyncua: VariantType e DataValue vazam do module de sessão para o pipeline de gate [Strong · ports & adapters]

**Arquivos:**
- `services/opc-worker/src/ottima_opc_worker/writes.py:82-89 (coerce_value recebe ua.VariantType)`
- `services/opc-worker/src/ottima_opc_worker/writes.py:254-272 (_execute constrói ua.DataValue(ua.Variant(...)) e chama client.get_node diretamente)`
- `services/opc-worker/src/ottima_opc_worker/connection.py:157-160 (property client devolve o Client asyncua bruto)`
- `services/opc-worker/src/ottima_opc_worker/connection.py:283-300 (variant_type_for devolve ua.VariantType)`
- `services/opc-worker/tests/test_writes.py:20-21 (teste do pipeline de escrita precisa importar asyncua.ua só para exercitar coerce_value)`

**Problema:** O module que deveria ser dono da sessão OPC-UA (`connection.py`) expõe seu Client bruto e o VariantType interno em vez de oferecer uma escrita completa, então o module de gate/auditoria (`writes.py`) precisa conhecer e montar DataValue/Variant/VariantType do asyncua para fazer a última milha até o PLC.

**Evidência:**
- `services/opc-worker/src/ottima_opc_worker/writes.py:270-272`
- `services/opc-worker/src/ottima_opc_worker/writes.py:82-89`
- `services/opc-worker/src/ottima_opc_worker/connection.py:157-160`
- `services/opc-worker/src/ottima_opc_worker/connection.py:283-284`
- `services/opc-worker/tests/test_writes.py:20-21`

**Antes (estrutura):** Nós: ConnectionRuntime (dono do Client asyncua e do cache de VariantType) — WriteConsumer (gate, rejeição, auditoria) — vocabulário do asyncua (ua.VariantType, ua.DataValue, ua.Variant, Node). Arestas: WriteConsumer._execute lê runtime.client (Client bruto) e chama client.get_node(tag.node_id) diretamente; WriteConsumer chama runtime.variant_type_for(tag_id) e recebe um ua.VariantType; WriteConsumer.coerce_value recebe esse ua.VariantType como parâmetro e faz a conversão float→bool/int/float; WriteConsumer monta ua.DataValue(ua.Variant(valor, variant_type)) e chama node.write_value(...) — três pontos onde o pipeline de gate atravessa a sessão e fala asyncua puro.

**Depois (estrutura):** Nós: ConnectionRuntime expõe uma única operação de escrita por tag (recebe tag_id + valor float, devolve sucesso/erro), que internamente resolve o node, o VariantType cacheado e monta o DataValue/Variant — tudo dentro do mesmo module que já importa asyncua para a sessão. WriteConsumer não importa asyncua: só chama essa operação e trata o resultado para decidir o evento de auditoria (ok/erro). Arestas: WriteConsumer → operação de escrita do runtime (tag_id, valor) → runtime faz o round-trip com o Client interno; nenhuma aresta atravessa vocabulário de asyncua para fora de connection.py.

**Deletion test:** Apagar a property que devolve o Client bruto e o método que devolve o VariantType cru força quem escreve a pedir a escrita ao module de sessão — a complexidade de DataValue/Variant/VariantType CONCENTRA-SE de volta em connection.py (que já importa asyncua para tudo o mais), não se move para lugar novo nenhum: sinal de que hoje ela está no lugar errado.

**Superfície de teste:** Hoje, testar a conversão pura de valor (coerce_value) exige `from asyncua import ua` em test_writes.py só para montar o VariantType do parâmetro, mesmo sendo lógica de conversão sem I/O. Depois, essa conversão viveria ao lado de variant_type_for e seria exercitada pelos mesmos testes de connection.py que já falam com o opcsim; test_writes.py passaria a testar só gate/rejeição/auditoria com valores float, sem nunca importar asyncua.

**Correção sugerida:** Mover a construção do valor de escrita (coerção + DataValue/Variant) para dentro do module de sessão, ao lado do cache de VariantType que ele já mantém, e devolver ao pipeline de gate só o resultado da tentativa de escrita, nunca os tipos do asyncua.

**Ganhos:** Interface de escrita ganha profundidade real · Asyncua nunca cruza para o module de gate · coerce_value testável sem importar asyncua · Locality: cache de tipos fica só na sessão · Leverage: um lugar cobre toda codificação

---

#### ARCH-17 — Handshake do Watchdog por Flow não mora num module profundo: três estruturas paralelas sincronizadas à mão em dois arquivos [Strong · in-process]

**Arquivos:**
- `services/opc-worker/src/ottima_opc_worker/state.py:104-108 (ConnectionSnapshot.flow_watchdog_alive, dict público)`
- `services/opc-worker/src/ottima_opc_worker/connection.py:114-116 (_flow_failure_pending, _flow_gate_generation, dicts privados)`
- `services/opc-worker/src/ottima_opc_worker/connection.py:340-350 (_stop_flow_watchdog apaga as 3 chaves em 3 linhas separadas)`
- `services/opc-worker/src/ottima_opc_worker/connection.py:352-392 (_flow_watchdog_freeze e _flow_watchdog_alive tocam 2 dicts cada, em ordens diferentes)`
- `services/opc-worker/src/ottima_opc_worker/writes.py:226-258 (WriteConsumer lê o dict público direto e chama flow_gate_generation() separadamente; comentário próprio admite 'invariante implícita entre dois módulos')`

**Problema:** A regra do ADR-009 (watchdog por flow, congelamento >10s derruba só as escritas daquele flow) está corretamente isolada por flow_id, mas o estado desse handshake — vivo, falha-pendente, geração do gate — está espalhado em três dicts paralelos guardados em dois arquivos, e cada transição (start, freeze, alive, session down, fail, stop) precisa lembrar de tocar o subconjunto certo deles.

**Evidência:**
- `services/opc-worker/src/ottima_opc_worker/connection.py:340-350`
- `services/opc-worker/src/ottima_opc_worker/connection.py:359-360`
- `services/opc-worker/src/ottima_opc_worker/connection.py:389-392`
- `services/opc-worker/src/ottima_opc_worker/writes.py:255-258`
- `services/opc-worker/src/ottima_opc_worker/state.py:104-108`

**Antes (estrutura):** Nós: WatchdogTask (mede o bit) — ConnectionSnapshot.flow_watchdog_alive (dict público, em state.py, lido por WriteConsumer e pelo /health) — ConnectionRuntime._flow_failure_pending (dict privado, dedupe de comm_restored) — ConnectionRuntime._flow_gate_generation (dict privado, contador de reabertura do gate, exposto via método a WriteConsumer). Arestas: WatchdogTask.on_freeze → _flow_watchdog_freeze escreve em 2 dicts; WatchdogTask.on_alive → _flow_watchdog_alive escreve/incrementa em 2 dicts; _stop_flow_watchdog apaga chave em 3 dicts, um de cada vez; on_session_down zera só 1 dos 3, preservando as chaves dos outros 2 por design; fail() zera só 1 dos 3 para todos os flow_ids; WriteConsumer lê o dict público direto e chama um método separado para o terceiro — quatro consumidores diferentes, cada um tocando um subconjunto distinto dos três dicts.

**Depois (estrutura):** Nós: WatchdogTask (inalterado) — um único mapa flow_id → registro de estado do watchdog, dono de connection.py, com duas leituras públicas (vivo? / gate reabriu desde quando?) e uma família de transições internas (armar, congelar, revivificar, desarmar) que sempre tocam o registro inteiro. Arestas: WatchdogTask → transição única no registro; WriteConsumer → as duas leituras públicas, nunca o dict cru; a projeção para /health (`to_health()`) lê o mesmo registro sem expor os campos internos de dedupe/geração.

**Deletion test:** Apagar os três dicts paralelos e substituir por um único mapa por flow_id CONCENTRA a invariante 'os três nascem, mudam e morrem juntos' num único ponto de escrita, em vez de depender de lembrar de tocar o subconjunto certo em cada um dos seis lugares que hoje mutam pelo menos um deles — sinal de module raso, não de complexidade essencial.

**Superfície de teste:** Hoje, provar uma borda do handshake (ex.: freeze isola só o flow certo, ou stop() de verdade libera para no_watchdog) exige orquestrar o opcsim de ponta a ponta e inspecionar snapshot.flow_watchdog_alive num teste e o efeito indireto em _BlockedPeriod.generation em outro arquivo de teste. Depois, as transições do registro único seriam testáveis isoladamente (sem opcsim) para as bordas de contabilidade, e os testes de integração existentes contra o opcsim continuariam provando o handshake real ponta a ponta.

**Correção sugerida:** Substituir os três dicts paralelos por um único registro por flow_id, dono de connection.py, que responde às duas perguntas que os chamadores realmente fazem hoje — o watchdog deste flow está vivo, e o gate deste flow reabriu desde a última checagem — sem expor os campos internos crus.

**Ganhos:** Um seam por flow, não três dicts · Locality: handshake mora num lugar · Depth: interface esconde o estado interno · Leverage: uma escrita cobre create/stop/freeze · Menos invariante implícita entre módulos

---

### Fatia — Editor de Flows no canvas

Os módulos genéricos do canvas (FlowEditorPage.tsx, nodes/BlocoChapa.tsx, nodes/contexto.ts) já são deep: não conhecem tipos específicos de Bloco e despacham por `TIPOS_BLOCO`/`TIPOS_DE_NO` sem switch próprio (confirmado por grep: nenhum `case`/`.type ===` fora dos pontos já mapeados). O problema não é esse núcleo — é que 'poucos pontos nomeados' ainda somam 6 arquivos e ~17 edições manuais por Bloco novo (ARCH-18), e a extração FormData→data de cada tipo mora inline num switch de componente React (ModalConfigBloco.tsx) em vez de função pura, deixando o PID (10 campos) sem nenhum teste — nem `*.check.ts` nem e2e (ARCH-19). Em `mpc/`, TabVariables.tsx quase não tem estado local próprio (só um ref de cache do `pid`); a real duplicação mecânica está em `mpcLogic.ts`, onde quatro funções `variavel*DoFormulario` reimplementam byte a byte o mesmo padrão ausente/vazio/valor (ARCH-20). O padrão 'espelhar regra de negócio do backend em TS para feedback instantâneo' está bem resolvido no MPC via golden JSON cross-language (ADR-019), mas o mesmo padrão em `connections/pendencias.ts` (item 4) não tem essa trava — cada lado transcreve a fórmula 'da spec' independentemente (ARCH-22). No nível de widget, 3 implementações concorrentes do mesmo campo numérico decimal pt-BR (ARCH-21) são o único sinal de duplicação puramente superficial.

#### ARCH-18 — Registro de Bloco: 6 arquivos, ~17 pontos de edição mecânica por tipo novo [Strong · in-process]

**Arquivos:**
- `frontend/src/features/flows/graph.ts:32 (TIPOS_BLOCO)`
- `frontend/src/features/flows/graph.ts:77 (ROTULO_BLOCO)`
- `frontend/src/features/flows/graph.ts:573,777,997 (switches atualizarNo/criarBloco/lerNo — 3 case por tipo dentro do mesmo arquivo)`
- `frontend/src/features/flows/nodes/index.tsx:209-233,322 (NoFiltroKalman + entrada em TIPOS_DE_NO)`
- `frontend/src/features/flows/FlowPalette.tsx:11-19 (DESCRICAO)`
- `frontend/src/features/flows/config/ModalConfigBloco.tsx:26,369-388,475 (import + case no switch aplicar() + dispatch de render)`
- `frontend/src/features/flows/pid.check.ts:14-17`

**Problema:** Adicionar um tipo de Bloco exige tocar 6 arquivos frontend — dentro de só graph.ts já são 9 pontos distintos (array, record de rótulo, defaults, tipo Dados*, alias No*, união BlocoNode, switch de sinal, switch de atualização, switch de criação, switch de leitura) — e nenhum deles referencia os outros, então a checagem de completude é manual.

**Evidência:**
- `frontend/src/features/flows/graph.ts:573,777,997 (mesmo tipo 'kalman'/'pid' aparece em 3 switches distintos do mesmo arquivo)`
- `frontend/src/features/flows/nodes/index.tsx:320-326 (TIPOS_DE_NO precisa da mesma chave que TIPOS_BLOCO)`
- `frontend/src/features/flows/FlowEditorPage.tsx:444-448 (confirma que FlowEditorPage.tsx e BlocoChapa.tsx NÃO precisam de edição — o dispatch genérico já existe, só falta consolidar os 6 pontos restantes)`
- `frontend/src/features/flows/pid.check.ts:14-17 ('Arquivo próprio, mesmo precedente de filtros.check.ts: um *.check.ts por bloco novo em vez de inchar graph.check.ts')`

**Antes (estrutura):** TIPOS_BLOCO (graph.ts) é a lista mestra; a partir dela, 6 arquivos independentes precisam, cada um, adicionar manualmente uma entrada para o novo tipo: graph.ts (9 pontos internos: array, record, defaults, tipos, uniões, 3 switches), nodes/index.tsx (componente + mapa), FlowPalette.tsx (record de descrição), ModalConfigBloco.tsx (2 mecanismos de despacho: switch de aplicar + condicional de render), um Campos*.tsx novo, um *.check.ts novo. Nenhuma aresta liga esses pontos entre si — só Records tipados (ROTULO_BLOCO, DESCRICAO) são pegos pelo compilador se faltar uma chave; os switches e o mapa de nós não.

**Depois (estrutura):** Um módulo `blocos/registro.ts` define `REGISTRO_BLOCO: Record<TipoBloco, DefinicaoBloco>` com rotulo/descricao/defaults/portas/Node/Campos/montarDados. graph.ts, nodes/index.tsx, FlowPalette.tsx e ModalConfigBloco.tsx importam e iteram sobre `REGISTRO_BLOCO` — a aresta única é o próprio registro, e falta de uma entrada quebra o build (Record completo) em vez de aparecer só em runtime/E2E.

**Deletion test:** Hoje, remover o suporte a um tipo de bloco exige tocar os mesmos 6 arquivos porque nenhum 'sabe' dos outros — a complexidade está espalhada, não concentrada. Um registro central faria essa remoção virar 1 edição: deletar a entrada do registro é o teste de que a complexidade foi de fato concentrada, não apenas deslocada.

**Superfície de teste:** Hoje: cada bloco tem seu *.check.ts cobrindo criarBloco/serialização (padrão pid.check.ts/filtros.check.ts); nada garante que os 6 pontos de registro foram todos tocados — um esquecimento em nodes/index.tsx ou Campos*.tsx só aparece em runtime/E2E, nunca em compilação. Depois: um teste único table-driven (`for (const tipo of TIPOS_BLOCO) expect(REGISTRO_BLOCO[tipo]).toBeDefined()`) cobre completude de todos os campos do registro de uma vez.

**Correção sugerida:** Um registro único `REGISTRO_BLOCO: Record<TipoBloco, {rotulo, descricao, defaults, Node, Campos, montarDados}>` centraliza os dados por tipo; graph.ts, nodes/index.tsx, FlowPalette.tsx e ModalConfigBloco.tsx passam a iterar sobre esse registro em vez de repetir um `case` por arquivo.

**Ganhos:** Leverage: 1 registro, não 6 arquivos · Locality: dados do tipo ficam juntos · Depth: interface simples, complexidade concentrada · Compilador barra registro incompleto · Testes: 1 suite valida completude de todos os tipos

---

#### ARCH-19 — Extração de campos por tipo só é alcançável renderizando o modal inteiro (PID sem nenhum teste) [Strong · in-process]

**Arquivos:**
- `frontend/src/features/flows/config/ModalConfigBloco.tsx:369-407 (switch aplicar())`
- `frontend/src/features/flows/pid.check.ts (cobre graph.ts, não o modal)`
- `frontend/src/features/flows/config/campos.ts:47-77 (matrizDoFormulario — único precedente de extração pura fora do switch)`

**Problema:** A lógica que transforma FormData em `data` do node (10 campos do PID com checkboxes e null explícito, output_eu do Script/Fuzzy) mora inline no switch de `aplicar()`, dentro do componente que também monta o `<dialog>`; para testar a extração é preciso renderizar o modal inteiro, e não existe e2e/pid.spec.ts nem cobertura em pid.check.ts para essa extração — 0% de cobertura na prática.

**Evidência:**
- `frontend/src/features/flows/config/ModalConfigBloco.tsx:390-407 (case 'pid': 10 campos lidos inline, incluindo `campos.get('auto_mode') === 'on'`)`
- `frontend/src/features/flows/pid.check.ts:1-146 (cobre defaults/serialização via graph.ts; nenhuma chamada a ModalConfigBloco ou a uma função de extração de formulário)`
- frontend/e2e/ (glob: filtros.spec.ts, flows-editor.spec.ts, mpc-variables-fields.spec.ts, mpc-objective.spec.ts — nenhum pid.spec.ts)
- `frontend/src/features/flows/config/campos.ts:47-77 (matrizDoFormulario é o único precedente de extração pura fora do switch, e só existe para o TFS)`

**Antes (estrutura):** ModalConfigBloco.tsx.aplicar() é uma função de ~140 linhas com switch(no.type) que lê FormData inline e constrói `data` para cada tipo, dentro do mesmo componente que efetua `dialogo.current?.showModal()`. Para verificar que o checkbox 'auto_mode' e o campo nulável 'output_min' do PID chegam certos em `data`, é preciso montar o DOM inteiro — só Playwright alcança, e nenhum e2e cobre PID hoje.

**Depois (estrutura):** Cada tipo ganha `montarDados<Tipo>(atual, campos): Dados<Tipo>` pura (sem DOM, sem dialog) importada por ModalConfigBloco.tsx. `aplicar()` vira `data = montarDados(no.type, no.data, campos)`; pid.check.ts testa `montarDadosPid` diretamente com um `FormData` construído em memória, sem browser.

**Deletion test:** Deletar mentalmente o switch atual tira a ÚNICA definição de como o PID lê seus 10 campos — não há backup dessa lógica em nenhum outro lugar (diferente do widget do ARCH-21, que é redundante entre si). É complexidade genuína e não testada; extrair para uma função pura concentra essa complexidade num module com teste próprio, em vez de deixá-la implícita dentro de um componente com efeito colateral de dialog.

**Superfície de teste:** Hoje: só e2e (Playwright) alcançaria a extração FormData→data de cada tipo, e PID (10 campos, incluindo 2 nuláveis e 3 booleanos) não tem NENHUM e2e cobrindo isso. Depois: pid.check.ts ganha testes diretos de `montarDadosPid(atual, formulario({...}))` sem precisar de browser, no mesmo padrão de campos.check.ts para o TFS.

**Correção sugerida:** Extrair uma função pura `montarDadosPid(atual, campos): DadosPid` (e equivalente por tipo) ao lado de cada Campos*.tsx, no mesmo padrão que `matrizDoFormulario` já usa para o TFS em config/campos.ts; `aplicar()` vira um dispatch de uma linha por tipo chamando a função pura.

**Ganhos:** Depth: montarDados pura, sem dialog · Interface testável sem Playwright · Leverage: repete padrão já usado no TFS · Fecha lacuna total de cobertura do PID · Locality: extração ao lado do Campos* do tipo

---

#### ARCH-20 — Quatro funções quase idênticas de reconstrução de variável MPC a partir do FormData [Worth exploring · in-process]

**Arquivos:**
- `frontend/src/features/flows/mpc/mpcLogic.ts:62-84 (variavelDvDoFormulario)`
- `frontend/src/features/flows/mpc/mpcLogic.ts:86-178 (variavelMvDoFormulario)`
- `frontend/src/features/flows/mpc/mpcLogic.ts:189-231 (variavelCvDoFormulario)`
- `frontend/src/features/flows/mpc/mpcLogic.ts:232-260 (variavelRestricaoDoFormulario)`

**Problema:** TabVariables.tsx em si tem pouquíssimo estado local (só um `ultimosPid` ref de cache); a duplicação real é estrutural em mpcLogic.ts — 4 funções reimplementam byte a byte o mesmo IIFE 'ausente preserva valor anterior, vazio vira null, valor numérico converte' para readback_tag_id, remote_sp_tag_id, local_shed_mode e range_low/high.

**Evidência:**
- `frontend/src/features/flows/mpc/mpcLogic.ts:114-121 (readback_tag_id, MV)`
- `frontend/src/features/flows/mpc/mpcLogic.ts:132-138 (local_shed_mode, MV)`
- `frontend/src/features/flows/mpc/mpcLogic.ts:222-228 (remote_sp_tag_id, CV)`
- `frontend/src/features/flows/mpc/mpcLogic.ts:65-72 (range_low/range_high, DV — mesmo padrão, comentário reconhece 'copiado da Restrição')`

**Antes (estrutura):** variavelDvDoFormulario, variavelMvDoFormulario, variavelCvDoFormulario e variavelRestricaoDoFormulario cada uma define localmente uma IIFE de 5-6 linhas para 'ausente preserva, vazio vira null, valor converte' — mvComPar. A regra existe em pelo menos 4 lugares copiados, cada um lendo `dados.get(c(campo))` e repetindo o mesmo `if (bruto === null) ... if (bruto === '') ...`.

**Depois (estrutura):** config/campos.ts ganha `campoOpcional(dados: FormData, nome: string, atual: T | null, converter): T | null`; as 4 funções `variavel*DoFormulario` chamam `campoOpcional(dados, c('readback_tag_id'), atual.readback_tag_id, paraInteiroPositivo)` — a regra ausente/vazio/valor vive uma vez só.

**Deletion test:** Deletar uma das 4 IIFEs hoje quebra só a variável correspondente (MV, CV, Restrição ou DV) — elas não compartilham código, então tecnicamente não são redundantes entre si, mas SÃO a mesma ideia copiada 4x. Convergir para 1 combinator concentra sem perder nenhum comportamento: as 4 chamadas continuam existindo, só a regra interna passa a ter 1 dono.

**Superfície de teste:** Hoje: a regra ausente/vazio/valor é testada indiretamente, uma vez por variável, dentro dos testes e2e que preenchem cada formulário (mpc-variables-fields.spec.ts). Depois: `campoOpcional` ganha um `*.check.ts` próprio e curto (3-4 casos: ausente/vazio/válido/inválido) que cobre a regra para as 4 variáveis de uma vez, sem depender de e2e para verificar a lógica de conversão.

**Correção sugerida:** Extrair um combinator `campoOpcional(dados, campo, atual): number | null` (ausente→atual, vazio→null, valor→número) para config/campos.ts, reusado pelas 4 funções `variavel*DoFormulario` no lugar das IIFEs repetidas.

**Ganhos:** Leverage: 1 combinator, 4 chamadas · Depth: regra ausente/vazio/valor num só lugar · Locality: mesma regra, mesmo nome em todo lugar · Menos superfície para o padrão divergir por engano

---

#### ARCH-21 — Três implementações concorrentes do campo numérico decimal pt-BR [Worth exploring · in-process]

**Arquivos:**
- `frontend/src/features/flows/config/CamposComuns.tsx:21-45 (Campo)`
- `frontend/src/features/flows/mpc/TabVariables.tsx:132-152 (CampoNumero)`
- `frontend/src/features/flows/config/CamposTfs.tsx:118-129 (Input cru dentro do map de parâmetros)`

**Problema:** O mesmo conceito (`<input type='text' inputMode='decimal' className='process-value'>` aceitando vírgula pt-BR) tem 3 implementações independentes — `Campo` (Filtros+PID), `CampoNumero` (só MPC) e um `<Input>` cru no TFS — com convenções diferentes de testid e sem texto de ajuda fora de `Campo`.

**Evidência:**
- `frontend/src/features/flows/config/CamposComuns.tsx:6-9 ('a terceira cópia byte a byte foi a que pagou a extração' — mas uma quarta cópia, em mpc/, ficou de fora dessa extração)`
- `frontend/src/features/flows/mpc/TabVariables.tsx:132-152 (CampoNumero reimplementa o mesmo <Input> com prop 'campo' em vez de 'nome')`
- `frontend/src/features/flows/config/CamposTfs.tsx:118-129 (Input cru, sem data-testid nem texto de ajuda)`

**Antes (estrutura):** config/CamposComuns.tsx define `Campo` (usado por CamposFiltros.tsx e CamposBlocoPid.tsx — 8 usos). mpc/TabVariables.tsx define `CampoNumero` (uso exclusivo do MPC, ~15 chamadas). config/CamposTfs.tsx usa `<Input>` cru diretamente no `.map()` dos parâmetros da matriz. As 3 renderizam o mesmo HTML/CSS mas com testid, nomeação de campo e suporte a `ajuda`/`placeholder` divergentes.

**Depois (estrutura):** `Campo` em CamposComuns.tsx aceita `{id, nome?, rotulo, valor, ajuda?, placeholder?, testid?}`; CampoNumero (mpc/TabVariables.tsx) e o Input cru de CamposTfs.tsx são removidos e substituídos por chamadas a `Campo` — a convenção de testid/ajuda passa a valer nos 3 lugares automaticamente.

**Deletion test:** Deletar qualquer uma das 3 hoje quebra o único formulário que a usa (Filtros+PID dependem de Campo; MPC depende de CampoNumero; TFS depende do Input cru) — nenhuma é redundante em isolamento. O candidato é o inverso: convergir as 3 concentra a mesma ideia num module, sem remover nenhum comportamento observável.

**Superfície de teste:** Hoje: cada formulário é testado via e2e preenchendo pelo seu testid específico (config-kc, mpc-mv-max-rate) — os testes não quebram com a triplicação, mas qualquer ajuste de acessibilidade (ex.: ligar `ajuda` via aria-describedby) precisa ser replicado em até 3 lugares manualmente. Depois: mudar o comportamento do campo numérico decimal é 1 edição, testada 1 vez.

**Correção sugerida:** `Campo` de CamposComuns.tsx ganha um prop `nome` opcional (para desacoplar do `id` HTML usado pela convenção `nomeCampoVar` do MPC); `CampoNumero` e o Input cru do TFS passam a delegar para `Campo`.

**Ganhos:** Leverage: 1 campo, 3 formulários usam · Locality: testid/ajuda convergem · Depth: Campo vira module realmente profundo · TFS ganha texto de ajuda de graça

---

#### ARCH-22 — Padrão golden cross-language existe só no MPC; Pendências duplica sem trava de drift [Worth exploring · mock]

**Arquivos:**
- `frontend/src/features/flows/mpc/mpcLogic.golden.check.ts:1-24`
- `frontend/src/features/flows/mpc/mpcLogic.ts:94-104 (comentário 'espelho client-side')`
- `frontend/src/features/connections/pendencias.ts:1-9`
- `frontend/src/features/connections/pendencias.check.ts:9-13`

**Problema:** A regra de negócio do MPC (ADR-019: tetos por categoria MV/CV/Restrição/DV, horizontes) é espelhada do backend para TS com um golden JSON gerado do Python e comparado nos dois lados (drift vira teste vermelho); a Pendência de conexão (item 4) também é 'espelhada byte a byte' do backend, mas cada lado reescreve a fórmula 'da spec' de forma independente, sem golden compartilhado — nada compara as duas implementações reais entre si.

**Evidência:**
- `frontend/src/features/flows/mpc/mpcLogic.golden.check.ts:1-24 (comentário descreve o mecanismo bidirecional de drift)`
- `frontend/src/features/flows/mpc/mpcLogic.ts:94-104 ('Espelho client-side de _check_mpc_caps/_matrix/_numbers/_horizons + mpc_state_dimension')`
- `frontend/src/features/connections/pendencias.ts:1-9 ('Espelha ottima_core.portability.pendencias.pendencias_da_conexao ... byte a byte')`
- `frontend/src/features/connections/pendencias.check.ts:9-13 ('as fórmulas abaixo são transcritas da spec, não do módulo sob teste')`

**Antes (estrutura):** mpc/mpcLogic.golden.json é gerado por ottima_core.mpc_golden_export (Python) e consumido pelos dois lados (teste Python + mpcLogic.golden.check.ts): mudar uma fórmula em só um lado fica vermelho. connections/pendencias.ts não tem golden: `pendenciasDaConexao` (TS) e `pendencias_da_conexao` (Python) são escritas cada uma 'da spec' de forma independente; pendencias.check.ts compara contra uma função `formula()` reescrita DENTRO do próprio arquivo de teste TS, nunca contra o Python real.

**Depois (estrutura):** Um exportador `pendencias_golden_export` (Python, mesmo padrão de mpc_golden_export) grava `pendencias.golden.json` com a tabela-verdade real do backend. pendencias.check.ts passa a comparar `pendenciasDaConexao` contra esse golden — a mesma trava bidirecional que o MPC já tem passa a cobrir Pendências também.

**Deletion test:** Deletar pendencias.check.ts hoje perde a tabela-verdade de 72 casos, mas NÃO perde nenhuma trava contra o Python divergir — o teste já é autossuficiente, comparando a função contra uma fórmula transcrita no PRÓPRIO teste, não contra o backend real. Isso mostra que o teste atual valida a MATEMÁTICA da função, não a CONCORDÂNCIA com o backend; adicionar o golden fecha esse buraco sem duplicar o que já existe (mesmo mecanismo, reusado).

**Superfície de teste:** Hoje: pendencias.check.ts tem uma tabela-verdade de 72 casos comparada contra uma fórmula reescrita no próprio arquivo de teste TS — drift entre as duas linguagens só apareceria por revisão humana lendo os dois arquivos lado a lado. Depois: pendencias.check.ts compara contra pendencias.golden.json gerado do Python, igual a mpcLogic.golden.check.ts — mesma garantia que o MPC já tem, sem inventar mecanismo novo.

**Correção sugerida:** Estender o mecanismo já existente (`ottima_core.mpc_golden_export` → mpcLogic.golden.json) para as 3 fórmulas de connections/pendencias.ts: um exportador Python equivalente grava `pendencias.golden.json` a partir da implementação real do backend, e pendencias.check.ts passa a comparar `pendenciasDaConexao` contra esse golden.

**Ganhos:** Leverage: reusa mecanismo golden do MPC · Interface: fonte única gera os 2 lados · Depth: elimina 2ª transcrição manual da spec · Testes: drift vira vermelho automático

---
## Saúde confirmada

Registrado para que a auditoria não seja lida como veredito de sistema doente. O que foi
verificado e está estruturalmente certo:

- **Contrato de Bloco no runtime é fino e deep.** 8 dos 9 tipos de Bloco passam pelo mesmo
  `step()`/`reset()` sem tratamento especial fora de `blocks/`; o único switch por tipo é a fábrica
  `definition.py::_instantiate`, ponto único e legítimo. Nenhuma matemática do MPC vazou para
  `blocks/mpc.py` — o seam com `mpc/builder.py`, `mpc/worker.py` e `target_calculation/ssto.py`
  está onde a docstring do módulo promete.
- **Nenhum hop do Canal ao vivo é repasse puro.** opc-worker → Redis → `PatternListener` →
  `FlowStatusHub._dispatch_opc_values` → WebSocket → `CanalAoVivo.tsx` → Faceplate: cada module faz
  trabalho real (filtro por assinante, backoff, backpressure com fila 8 drop-oldest, coalescência de
  250 ms). Não há module fino para colapsar. O filtro por `tag_id` mora só em `ws.py`; a convenção
  `quality` 0/1/2 é definida uma vez em `bus.py` e apenas consumida; o `recorder` grava verbatim de
  propósito (spec F1 §3.4-2).
- **O Barramento tem um único adapter (Redis real).** Por isso a auditoria NÃO propõe seam novo ali:
  um adapter é seam hipotético.
- **`validate.py` é o module profundo único da semântica do Flow.** O espelho no editor
  (`motivoRecusa`/`avisosInversao`) é pequeno, documentado e deliberado — validação otimista de UI
  com o servidor sempre como árbitro final. Não é duplicação a corrigir.
- **O seam com asyncua não vaza para fora do opc-worker.** `ConnectionConfig`/`TagConfig` carregam
  `node_id: str` puro; nada de asyncua alcança flow-runtime, API ou frontend. Existem dois adapters
  reais e simétricos (servidor de campo e `tests/opcsim`) sem nenhum `if opcsim` em código de
  produção. A máquina de estados da CONEXÃO é explícita e mora num module só.
- **LOCAL/REMOTO fica fora do opc-worker**, como o ADR-006 manda.
- **RBAC decidido num lugar só.** `require_admin`/`require_operator` em `deps.py:53-60`, 8 linhas — a
  decisão é profunda (o problema, ARCH-15, é só a fiação repetida).
- **Export de Projeto já tem par puro.** `montar_bundle` é testável sem banco; a assimetria está no
  import (ARCH-14).
- **Projeto ativo único é garantido pelo banco**, por índice parcial `postgresql_where`, não por
  disciplina de código.
- **O canvas genérico não conhece tipos de Bloco.** `FlowEditorPage.tsx`, `nodes/BlocoChapa.tsx` e
  `nodes/contexto.ts` despacham por `TIPOS_BLOCO`/`TIPOS_DE_NO` sem switch próprio.
- **`TrendChart` já é reuso real** entre `TrendPage` e `TrendFuzzy`, exatamente como o ADR-030
  decidiu; `escalas.ts`, `trendTheme.ts` e `useJanelaDeslizante` são compartilhados de fato.
- **O padrão golden cross-language funciona.** `ottima_core.mpc_golden_export` →
  `mpcLogic.golden.json` trava drift Python↔TS no MPC e vira teste vermelho quando um lado muda.
  ARCH-22 propõe estender o mecanismo, não inventá-lo.

---

## Recomendação de primeiro corte — ARCH-07

É o único achado onde a auditoria confirmou **defeito latente**, não apenas fricção. Verificado
arquivo por arquivo:

- `frontend/src/features/flows/graph.check.ts:611` alimenta o fixture de retrocompatibilidade do MPC
  com a chave `du_max`.
- Essa chave não tem leitor: `grep du_max frontend/src/features/flows/mpc/graphMpc.ts` → nenhuma
  ocorrência. O campo real é `max_rate` desde a migração `0009_mpc_max_rate.py`.
- As asserções do teste (`graph.check.ts:648-651`) olham só `objective` e `psv`.

**Consequência:** um regresso que zere `max_rate` — o limite de taxa de variação de uma MV, campo com
peso de segurança — atravessa o teste de retrocompatibilidade verde. A cobertura desse caminho está
silenciosamente vazia.

**Corte mínimo (não depende de refactor nenhum):** trocar `du_max` por `max_rate` no fixture e
acrescentar a asserção do valor resultante. Depois, o aprofundamento do ARCH-07/ARCH-06: gerar a
tabela de defaults do `model_json_schema()` e apagar os literais das 12 funções `ler*()`.

### Sequência sugerida

| Ordem | Achado | Por quê |
|---|---|---|
| 1 | ARCH-07 | risco verificado em campo de segurança; corte mínimo é pequeno e isolado |
| 2 | ARCH-01 | maior retorno em fricção e a divergência de comportamento já reportada entre as telas de tendência; ADR-030 já manda reusar, não há decisão a reabrir |
| 3 | ARCH-18 | ~17 edições mecânicas em 6 arquivos por Bloco novo, no eixo de extensibilidade central do produto |
| 4 | ARCH-11 | defeito aberto e admitido via `xfail(strict=True)`; fecha a lacuna intra-partição sem reabrir o ADR-004 |
| 5 | ARCH-12 | ataca os 37 min de suíte pela interface (`build_mpc` funde montagem e compilação IPOPT), não por infraestrutura |

---

## Nota de processo — gate sem enforcement

Achado fora do eixo de aprofundamento, registrado aqui porque apareceu na preparação da worktree:
`uv run ruff format --check .` (gate do `CLAUDE.md`) falhava em 18 arquivos desde antes deste branch,
com o mesmo resultado no checkout principal. A causa não é drift de configuração — `line-length = 100`
está no `pyproject.toml` desde `059c786`, o primeiro commit do workspace uv. É que nada mecaniza o
gate: `.github/workflows/` não existe e `grep -rn ruff .github/` não retorna nada.

Corrigido em `70ce9e9` (formatação apenas; AST idêntica em 18/18 arquivos comparados contra o `HEAD`
anterior via `ast.dump(ast.parse(...))`). O enforcement em si não foi criado: adicionar CI é decisão
de arquitetura, com ADR, não conserto mecânico. Registrado como TD-023.
