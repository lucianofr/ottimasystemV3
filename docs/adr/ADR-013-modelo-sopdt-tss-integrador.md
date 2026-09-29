# ADR-013 — Modelo do MPC: matriz SOPDT + processo integrador; horizontes derivados do TSS

**Status:** Aceito · 2026-08-03 (detalha o ADR-008)

> **Emenda:** o par integrador aceita **constante de tempo de 1ª ordem τ1 opcional** (IFOPDT)
> — ver "Emenda — lag de 1ª ordem no par integrador", 2026-09-13.

## Contexto
O formulário sem código (ADR-008) exige forma paramétrica fixa. Na prática dos usuários-alvo, modelos vêm de step-test; processos de nível/pressão em vaso fechado são integradores (PV não estabiliza).

## Decisão
- **Matriz de modelos por par** MV→CV e DV→CV.
- **Tipo de resposta definido por CV:** *autorregulável* → parâmetros **SOPDT (K, τ1, τ2, θ)** por par; *integrador* → **IOPDT/IFOPDT (Ki, τ1 opcional, θ)** por par — ganho de rampa `Ki` [un/(un·s)], constante de tempo de 1ª ordem `τ1` [s] (0 ou ausente = integrador puro) e tempo morto `θ` [s].
- **Np/Nc NÃO são editados pelo usuário:** derivados do **TSS (Time to Steady State)** informado por CV. Heurística default da implementação: `Ts_mpc = multiplicador × Ts_flow`; `Np = ceil(TSS / Ts_mpc)` (com teto de segurança); `Nc = max(2, ceil(Np/4))`.
- Formulário expõe ainda: **limites duros de MV (min/max)** e **rate limit (Δu máx/ciclo)**.

## Consequências
- (+) Menos botões, defaults seguros: TSS é um número que engenheiro de processo sabe estimar; horizontes errados deixam de ser um modo de falha.
- SOPDT/integrador → conversão interna para espaço de estados discreto do do-mpc; **tempo morto via aumento de estados**. Um par integrador com `τ1 > 0` custa **2 estados** (lag + acumulador), como o SOPDT.
- Integrador sem restrição de CV é malha aberta instável no ótimo → validação do formulário deve exigir limites/SP coerentes.
- Pendência (Rodada 3): tratamento das CVs — SP fixo apenas, ou zonas/restrições suaves e ideal resting values na v1?

## Emenda — lag de 1ª ordem no par integrador (IFOPDT) (2026-09-13)

**Contexto:** a Decisão fixou o par integrador em `(Ki, θ)` — integrador puro com tempo morto.
Linha integradora real raramente rampa na taxa plena no instante em que a coluna move: nível
cuja vazão de saída responde devagar à válvula, pressão em vaso com volume de transporte antes
do elemento final. Sem `τ1`, a única forma de representar esse atraso de subida era inflar o
tempo morto `θ` (atraso puro, que não tem a curvatura da subida) ou aceitar o erro de modelo e
deixar o bias absorvê-lo a cada ciclo — com predição errada no transiente, que é justamente
onde o move plan decide.

**Decisão:** o par de linha `kind="integrating"` aceita a chave **`tau1` OPCIONAL** (≥ 0, em
segundos), formando `G(s) = Ki·e^(−θs) / (s·(τ1·s + 1))` — integrador alimentado por um estágio
de 1ª ordem. `τ1 = 0` **ou chave ausente** reproduz o integrador puro bit a bit, então todo
`graph_json` gravado antes desta emenda continua válido sem migração. Nenhuma chave nova no
SOPDT, nenhum canal novo, nenhuma mudança de schema de banco (o config vive no `graph_json`).

Consequências de implementação que esta emenda fixa como normativas:

- **Discretização:** estágio de 1ª ordem exato no ZOH (`a₁ = e^(−Ts/τ1)`) em série com o
  integrador retangular, na MESMA composição "atualiza-e-emite" do SOPDT — o acumulador consome
  a saída JÁ atualizada do estágio. A **saída do par é sempre o acumulador** (último estado).
  Abaixo do limiar `Ts/DIRECT_PASS_RATIO` (o mesmo do SOPDT) o estágio degrada para passagem
  direta e o par volta a 1 estado.
- **Dimensão de estado:** `mpc_state_dimension` (e o espelho no frontend) conta **2 estados para
  qualquer par integrador com `τ1 > 0`**, mais o atraso `round(θ/Ts_mpc)`. Isso é um **teto
  conservador, não a contagem exata**: com `0 < τ1 < Ts_mpc/DIRECT_PASS_RATIO` o estágio degrada
  (bullet acima) e o modelo montado tem 1 estado, enquanto a contagem segue em 2 — exatamente a
  convenção que já vale para o SOPDT (conta 2 mesmo com `τ2 = 0`, que monta 1 estado). A
  contagem existe para o aviso de dimensão excessiva (RF-608), onde superestimar é o lado
  seguro. **Corolário para quem escreve teste:** `model.n_x == mpc_state_dimension(...)` só vale
  com todos os τ acima do limiar — igualar os dois lados "corrigindo" um deles é bug, não fix.
- **Arme bumpless (ADR-008/013 via spec F4 §3.6):** a medida da linha entra **só no
  acumulador**; o estágio de 1ª ordem assenta no `u` vigente em desvio do ponto de operação
  (ganho DC 1). Plantar a medida no estado do lag mistura coordenadas (nível da linha num
  estado do lado da entrada) e erra a primeira rampa — o bias em `t=0` não denuncia o erro.
- **SSTO (ADR-027 §3/§4):** a taxa de rampa da linha continua sendo `Ki` — o lag atrasa a
  rampa, não muda a taxa de regime. A leitura crua `(c·b)/Ts`, válida para o integrador de 1
  estado, devolve `Ki·(1−a₁)` com lag e **não pode** ser usada: o `G` do LP é o incremento do
  acumulador com o estágio já assentado. `G`/`Gd` continuam saindo do MESMO `PairSS` do
  controlador (§3, "não existe segundo modelo de ganho").

**Unidade do `Ki` (reafirmação, não mudança):** `%/(%·s)` — taxa da linha em % do span dela por
SEGUNDO, por 1% do span da coluna (RF-602/609). A UI rotula com a base completa.

**Explicitamente NÃO decidido nesta emenda:**

1. O bloco **TFS** (ADR-022, RF-521) continua com elementos SOPDT/IOPDT — simular planta
   IFOPDT em malha fechada exigiria mexer no `kind` da matriz do TFS, fora do escopo.
2. Nenhuma segunda constante de tempo (`τ2`) no integrador: a forma do par integrador segue
   FECHADA em `{Ki, tau1?, theta}` e qualquer outra chave reprova a validação de grafo.
