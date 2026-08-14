# ADR-029 — Bloco Fuzzy (FuzzyLite/pyfuzzylite)

**Status:** Aceito · 2026-08-14

## Contexto
Controle fuzzy é uma ferramenta clássica de campo (lógica difusa Mamdani/Tsukamoto/TSK) que
engenheiros de processo já trazem prontas de outras plataformas no formato **FLL** (FuzzyLite
Language) — o mesmo texto que exportam do QtFuzzyLite ou escrevem à mão. Reimplementar um editor
visual de conjuntos fuzzy no canvas seria trabalho grande para reproduzir o que o engenheiro já
tem pronto; o caminho direto é aceitar o FLL como está e rodá-lo.

`pyfuzzylite` (a porta Python do FuzzyLite, v8) é o motor: parser de FLL completo
(`FllImporter`), engine com `input_variables`/`output_variables` na ordem de declaração,
avaliação por `process()`.

## Decisão

### Config e portas
Bloco `fuzzy` com config `{fll: str, n_inputs: int (1..8), n_outputs: int (1..8),
output_eu: dict[str, str]}` — teto de 8 portas por lado, o mesmo `MAX_SCRIPT_PORTS` do bloco
Script (ADR-018), por consistência de limite entre blocos dinâmicos. Portas `IN1..INn` /
`OUT1..OUTn`, numéricas, mapeadas **posicionalmente** à ordem de declaração de
`input_variables`/`output_variables` no FLL — **não** por nome. Portas nomeadas exigiriam um
parser de FLL no frontend só para popular um seletor de nomes, o que o ADR-005 já veta (o
frontend não interpreta contrato de bloco além do que o backend expõe em `PORT_CONTRACTS`); o
mapeamento posicional mantém o frontend cego ao conteúdo do FLL, como os demais blocos
dinâmicos (Script, ADR-018).

`output_eu` dá paridade com Script/TFS: uma EU textual por saída, só para exibição no
canvas/faceplate — não entra na avaliação do engine.

`FUZZY_DEFAULT_FLL` (conteúdo do `default.fll` da raiz do repo, colado verbatim) é constante
única em `contracts_export.py`, fonte de verdade para o FLL pré-preenchido no modal do bloco
novo — evita duplicar o texto num espelho TypeScript, que divergiria em silêncio a cada edição
futura do default.

### Validação em duas camadas
1. **Save/import** (`validate_graph`, estágio de conteúdo — mesmo ponto de `MpcConfig`,
   `parse.py:164-168`): import lazy de `fuzzylite` dentro da função de validação (mantém o
   import pesado fora do cold-start do módulo); `FllImporter().from_string(fll)` — exceção do
   parser vira erro 422 em pt-BR; `len(engine.input_variables) == n_inputs` e
   `len(engine.output_variables) == n_outputs` — mismatch é erro explícito, não truncamento
   silencioso; `engine.is_ready(errors)` — falha anexa os erros da própria lib (variável sem
   termo, regra referenciando variável inexistente etc.), traduzidos para a lista de erros do
   `ValidationResult`.
2. **Deploy** (construção do engine no flow-runtime): a mesma validação roda de novo ao montar
   o bloco para execução — um FLL válido no save de um dia pode não bastar se a versão de
   `pyfuzzylite` mudou entre save e deploy (upgrade de dependência, por exemplo); falha aqui é
   erro de deploy, não de save.

### Tetos de custo (FUZZY-SEC)
O texto FLL é input do usuário e roda em dois event loops compartilhados: o da API (save) e o
do flow-runtime (deploy + varreduras). Três tetos fecham o vetor de DoS:
- **Tamanho do FLL** — `MAX_FUZZY_FLL_LENGTH` (200.000 caracteres, `parse.py`): exports reais
  do QtFuzzyLite ficam na casa dos KB; o teto limita indiretamente o número de regras/termos
  que `is_ready` e o warmup processam.
- **Resolution dos defuzzificadores integrais** — teto 10.000 em `_valida_fuzzy`
  (`validate.py`): `Centroid <N>` aloca um array de `N` pontos a **cada** `engine.process()`,
  então um `N` sem limite travaria o processo inteiro por varredura.
- **Contagem de portas** — 1..8 (já existente, `MAX_SCRIPT_PORTS`).

Assimetria operacional: a camada de save roda fora do event loop da API (`asyncio.to_thread`
em `routers/flows.py`, mesmo padrão no import de `projects.py`); já a construção do bloco no
deploy (`build_definition`) e o
`step()` por varredura rodam **inline** no event loop do flow-runtime (ADR-004). Isso só é
seguro por causa dos tetos acima — sem eles, um FLL com `resolution` ou texto arbitrário
seria DoS de todos os flows do processo. O `step()` inline se mantém por performance
(sub-ms em engine típico) e porque o scheduler já detecta overrun (`flow_overrun`).

### Dependência e licenciamento
`pyfuzzylite>=8.0,<9`. FuzzyLite é **dual-licenciado**: GPLv3 (uso livre) ou licença comercial
paga (distribuição fechada a terceiros). **Flag explícito para o usuário:** o OttimaSystem é
software on-premise interno — rodar o bloco Fuzzy na própria instalação está coberto pela
GPLv3. Se o OttimaSystem (ou um fork dele) vier a ser **distribuído a terceiros como produto
fechado**, a distribuição do módulo Fuzzy exige licença comercial da FuzzyLite; isso é uma
decisão comercial fora do escopo desta ADR, não uma limitação técnica.

`pyfuzzylite` entra também no **ottima-core** (não só no flow-runtime), porque a validação de
save roda na API. Como o ottima-core é dependência dos quatro serviços (api, flow-runtime,
opc-worker, recorder), a resolução instala `pyfuzzylite` + `numpy` nas quatro imagens — o
custo é disco e import: o uso no core é lazy (dentro da função de validação), e os serviços
que não validam grafo nunca importam o módulo. Tradeoff aceito pelo usuário no Gate.

**numpy:** a pyfuzzylite 8.x declara `numpy<2.0` (poetry `^1.20`), mas o próprio repo mantém
a regra `NPY201` ativa e usa só APIs estáveis — compatível com numpy 2. O workspace exige
`numpy>=2.5`, então o pin foi substituído por `override-dependencies = ["numpy>=2.5"]` no
`pyproject.toml` raiz (`[tool.uv]`), com verificação em runtime (parse, `is_ready`,
`process`, `restart` do FLL default).

### Semântica de execução (RF-542)
A cada varredura: `engine.input_variables[i].value = <valor da porta IN(i+1)>`
(posicional), depois `engine.process()`. Por porta de saída:
- valor **finito** ⇒ `(float(v), ok_entradas)`, onde `ok_entradas = all(s.ok and
  math.isfinite(float(s.v)) for s in entradas)` — a saída finita do engine ainda carrega a
  invalidez de qualquer entrada não-finita ou com `ok=False` a montante.
- valor **não-finito** (`nan` ou `inf` — comum quando nenhuma regra ativa e `default: nan`,
  como no FLL padrão) ⇒ mantém o **último valor bom daquela porta específica** + `ok=False`;
  antes da primeira saída boa, `(None, False)`.
- exceção em `engine.process()` (FLL malformado que passou na validação de outra forma, erro
  de runtime da lib) ⇒ mantém **todas** as saídas do bloco + `ok=False` no bloco inteiro.

Motivação: o bloco `opc_write` só suprime escrita quando `v is None` ou `ok is False`
(RF-502). Um `nan` marcado `ok=True` chegaria ao PLC como escrita válida — silenciosamente
corrompendo a malha. `math.isfinite` cobre `nan` e `±inf` na mesma checagem.

Extração de escalar do `pyfuzzylite`: `OutputVariable.value` pode ser `float` ou array numpy
de shape `(1,)` depois do `defuzzify` — normalizado com
`float(np.asarray(v).reshape(-1)[-1])` antes de qualquer checagem de finitude.

### Reset e hot-swap (RF-543)
`reset()` do bloco ⇒ `engine.restart()` (reseta as entradas para `nan`, recarrega as regras,
limpa as saídas **inclusive `previous_value`**). Isso significa que `lock-previous` do FLL (se
o engenheiro configurou uma saída para reter o valor anterior entre inferências, feature do
próprio FuzzyLite) vale **entre varreduras normais** — mas morre no `stop`/`deploy` do flow,
igual a qualquer outro estado de bloco. Hot-swap (RF-304) preserva o estado do bloco quando a
config não mudou, incluindo o `previous_value` interno do engine — mesma regra dos demais
blocos com estado (Script, TFS, filtros).

## Consequências
- (+) Engenheiro cola um FLL pronto (de outra ferramenta ou escrito à mão) sem o OttimaSystem
  precisar de editor visual de fuzzy sets.
- (+) Validação em duas camadas pega tanto erro de digitação no save quanto incompatibilidade
  de dependência no deploy.
- (+) `nan`/`inf` nunca vazam para o PLC como escrita "válida" — mesma garantia de segurança
  dos demais blocos numéricos.
- (-) `pyfuzzylite` GPLv3/comercial declarado em ottima-core e flow-runtime; via ottima-core,
  a resolução instala a lib nas imagens dos quatro serviços — tradeoff aceito no Gate;
  distribuição fechada a terceiros do produto exigiria licença comercial da FuzzyLite
  (decisão de negócio, não bloqueio técnico da v1).
- Portas posicionais tornam a ordem de declaração das variáveis no FLL **parte do contrato**:
  reordenar `InputVariable`/`OutputVariable` no texto colado muda o mapeamento de portas — o
  mesmo risco que scripts Python já têm com `IN1..INn`/`OUT1..OUTn` (ADR-018), documentado, não
  novo.
- Paleta da v1 cresce de 7 para **8 blocos** (RF-301).
