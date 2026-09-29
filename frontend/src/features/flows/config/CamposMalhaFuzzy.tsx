import { useState } from "react";

import { Input } from "../../../components/ui/input";
import { Label } from "../../../components/ui/label";
import { Select } from "../../../components/ui/select";
import { fllDefaultMalha, MAX_FLL_LENGTH, MAX_LOOPS_FUZZY, type NoFuzzyLoop } from "../graph";
import { indentarComTab } from "./campos";

const OPCOES_CANAL = Array.from({ length: MAX_LOOPS_FUZZY }, (_, i) => i + 1);

/** Todas as bases default que o servidor gera (1..MAX) — trocar `n_loops` só reescreve o
 *  texto se ele AINDA é uma base default; base autoral é preservada (o save valida a
 *  contagem posicional e o 422 guia a correção). */
const BASES_DEFAULT: readonly string[] = OPCOES_CANAL.map((n) => fllDefaultMalha(n));

function CampoNumero({
  id,
  rotulo,
  valor,
  dica,
}: {
  id: string;
  rotulo: string;
  valor: number;
  dica?: string;
}) {
  return (
    <div className="space-y-1">
      <Label htmlFor={id}>{rotulo}</Label>
      <Input
        id={id}
        name={id}
        data-testid={`config-${id}`}
        inputMode="decimal"
        className="process-value"
        defaultValue={String(valor)}
      />
      {dica !== undefined && <p className="text-[10px] text-fg-muted">{dica}</p>}
    </div>
  );
}

/**
 * Fuzzy Malha v2 (SPEC_FUZZY v2 MIMO): canais, ganhos do kernel, limites e a base de
 * regras FLL. `n_loops` e `fll` são ESTRUTURAIS (ADR-039 D11): mudá-los re-instancia o
 * bloco no próximo deploy e a malha aterrissa em MAN — o aviso mora no rodapé do FLL.
 */
export function CamposMalhaFuzzy({ dados }: { dados: NoFuzzyLoop["data"] }) {
  const [nLoops, setNLoops] = useState(dados.n_loops);
  const [fll, setFll] = useState(dados.fll);

  function aoMudarCanais(novo: number): void {
    setNLoops(novo);
    if (BASES_DEFAULT.includes(fll)) setFll(fllDefaultMalha(novo));
  }

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 gap-3">
        <div className="space-y-1">
          <Label htmlFor="n_loops">Canais de controle (malhas)</Label>
          <Select
            id="n_loops"
            name="n_loops"
            data-testid="config-n-loops"
            value={nLoops}
            onChange={(evento) => aoMudarCanais(Number(evento.target.value))}
          >
            {OPCOES_CANAL.map((quantidade) => (
              <option key={quantidade} value={quantidade}>
                {quantidade}
              </option>
            ))}
          </Select>
          <p className="text-[10px] text-fg-muted">
            Portas pv_1..pv_n / out_1..out_n; SP e OUT por canal na página MALHA.
          </p>
        </div>
        <div className="space-y-1">
          <Label htmlFor="direct_acting">Ação</Label>
          <Select
            id="direct_acting"
            name="direct_acting"
            data-testid="config-direct-acting"
            defaultValue={String(dados.direct_acting)}
          >
            <option value="false">Reversa (erro = SP − PV)</option>
            <option value="true">Direta (erro = PV − SP)</option>
          </Select>
        </div>
      </div>

      <div className="grid grid-cols-4 gap-3">
        <CampoNumero id="ke" rotulo="KE (1/EU)" valor={dados.ke} dica="1/KE = faixa de erro coberta" />
        <CampoNumero id="kde" rotulo="KDE (s/EU)" valor={dados.kde} dica="0 desliga a derivada" />
        <CampoNumero id="ku" rotulo="KU (%span/s)" valor={dados.ku} dica="ganho de saída" />
        <CampoNumero id="tf_de" rotulo="TF_DE (s)" valor={dados.tf_de} dica="filtro da derivada" />
      </div>

      <div className="grid grid-cols-4 gap-3">
        <CampoNumero id="sp_lo_lim" rotulo="SP mín (EU)" valor={dados.sp_lo_lim} />
        <CampoNumero id="sp_hi_lim" rotulo="SP máx (EU)" valor={dados.sp_hi_lim} />
        <CampoNumero id="out_scale_lo" rotulo="OUT escala mín (EU)" valor={dados.out_scale_lo} />
        <CampoNumero id="out_scale_hi" rotulo="OUT escala máx (EU)" valor={dados.out_scale_hi} />
      </div>

      <div className="space-y-1">
        <Label htmlFor="fll">FLL (FuzzyLite Language) — base de regras</Label>
        <textarea
          id="fll"
          name="fll"
          data-testid="config-fll-malha"
          rows={14}
          spellCheck={false}
          maxLength={MAX_FLL_LENGTH}
          value={fll}
          onChange={(evento) => setFll(evento.target.value)}
          onKeyDown={indentarComTab}
          className="w-full rounded-sm border border-border bg-well p-2 font-mono text-xs leading-relaxed text-fg focus-visible:outline-2 focus-visible:outline-accent"
        />
        <p className="text-[10px] text-fg-muted">
          Contrato posicional (v2): exatamente 2×N InputVariable na ordem e_1, de_1, …, e_N,
          de_N e N OutputVariable (du_1..du_N); nomes livres. Todas as variáveis em range
          -1.000 1.000 com lock-range: true; saídas com default: nan e lock-previous: false;
          um único RuleBlock. Regras podem cruzar canais (desacoplamento MIMO). Tab insere
          quatro espaços.
        </p>
        <p className="text-[10px] text-fg-muted">
          Atenção: FLL e número de canais são ESTRUTURAIS — a troca re-instancia o bloco no
          próximo deploy e a malha aterrissa em MAN com a saída mantida (bumpless).
        </p>
      </div>
    </div>
  );
}
