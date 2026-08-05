import { useState } from "react";

import { Input } from "../../../components/ui/input";
import { Label } from "../../../components/ui/label";
import { numeroDoCampo } from "../config/campos";
import type { ParModeloMpc, VariaveisMpc } from "../graph";
import { formatarNumero } from "../useFlowStatus";
import { derivarHorizontes, dimensaoEstado, nomeCampoVar } from "./mpcLogic";

interface LinhaTss {
  id: string;
  categoria: "CV" | "Restrição";
  rotulo: string;
  tss: number;
}

interface Props {
  variaveis: VariaveisMpc;
  aoMudarVariaveis: (variaveis: VariaveisMpc) => void;
  modelos: Record<string, Record<string, ParModeloMpc>>;
  multiplier: number;
  tsFlowSegundos: number;
}

/** TSS de uma linha (spec F4 §7.3): campo controlado — ao contrário do resto do modal
 *  (valores folha não-controlados, lidos só no Aplicar), este precisa refletir Ts_mpc/Np/Nc
 *  ao vivo a cada dígito. O texto digitado fica em estado local (`texto`) para não corromper
 *  vírgula/ponto em digitação parcial (ex.: "6," viraria "6" se o valor fosse formatado de
 *  volta a cada tecla); só o número interpretado sobe para `variaveis`. */
function CampoTss({
  id,
  rotulo,
  valorAtual,
  aoMudar,
}: {
  id: string;
  rotulo: string;
  valorAtual: number;
  aoMudar: (valor: number) => void;
}) {
  const [texto, setTexto] = useState(String(valorAtual));
  return (
    <div className="grid grid-cols-[1fr_auto] items-center gap-3 rounded-panel border border-hairline bg-well p-2">
      <Label htmlFor={`tss-${id}`} className="text-xs">
        {rotulo}
      </Label>
      <Input
        id={`tss-${id}`}
        name={nomeCampoVar(id, "tss")}
        data-testid={`mpc-tss-${id}`}
        type="text"
        inputMode="decimal"
        className="process-value w-28"
        value={texto}
        onChange={(evento) => {
          setTexto(evento.target.value);
          aoMudar(numeroDoCampo(evento.target.value, valorAtual));
        }}
      />
    </div>
  );
}

function CampoDerivado({ rotulo, valor, testid }: { rotulo: string; valor: string; testid?: string }) {
  return (
    <div className="space-y-1">
      <Label>{rotulo}</Label>
      <Input
        readOnly
        disabled
        data-testid={testid}
        className="process-value"
        value={valor}
      />
    </div>
  );
}

/**
 * Aba Horizontes (spec F4 §7.3, RF-603, RF-608): TSS por linha (CV/Restrição) editável ao
 * vivo — precisa ser estado controlado para `Ts_mpc`/`Np`/`Nc` e os avisos §2.2-7
 * acompanharem cada dígito. Por isso o campo mora só aqui (não duplica o `tss` que a aba
 * Variáveis mostrava na 4.2 — removido de lá na 4.3 para não ter dois campos não-sincronizados
 * editando o mesmo valor).
 */
export function TabHorizons({
  variaveis,
  aoMudarVariaveis,
  modelos,
  multiplier,
  tsFlowSegundos,
}: Props) {
  const linhas: LinhaTss[] = [
    ...variaveis.cvs.map((cv) => ({
      id: cv.id,
      categoria: "CV" as const,
      rotulo: `CV — ${cv.name.trim() !== "" ? cv.name : cv.id}`,
      tss: cv.tss,
    })),
    ...variaveis.constraints.map((co) => ({
      id: co.id,
      categoria: "Restrição" as const,
      rotulo: `Restrição — ${co.name.trim() !== "" ? co.name : co.id}`,
      tss: co.tss,
    })),
  ];

  function mudarTss(id: string, categoria: "CV" | "Restrição", valor: number): void {
    if (categoria === "CV") {
      aoMudarVariaveis({
        ...variaveis,
        cvs: variaveis.cvs.map((cv) => (cv.id === id ? { ...cv, tss: valor } : cv)),
      });
    } else {
      aoMudarVariaveis({
        ...variaveis,
        constraints: variaveis.constraints.map((co) =>
          co.id === id ? { ...co, tss: valor } : co,
        ),
      });
    }
  }

  const horizontes = derivarHorizontes(
    multiplier,
    tsFlowSegundos,
    linhas.map((linha) => linha.tss),
  );
  const np60 = horizontes !== null && horizontes.np > 60;
  const dimensao = horizontes === null ? null : dimensaoEstado(variaveis, modelos, horizontes.tsMpc);
  const dim120 = dimensao !== null && dimensao > 120;

  return (
    <div data-testid="mpc-tab-horizontes" className="space-y-4">
      {linhas.length === 0 ? (
        <p className="text-xs text-fg-muted">
          Adicione ao menos uma CV ou Restrição na aba Variáveis para derivar os horizontes.
        </p>
      ) : (
        <div className="space-y-2">
          <h3 className="plaqueta text-xs text-fg-muted">TSS por linha (tempo de assentamento, s)</h3>
          {linhas.map((linha) => (
            <CampoTss
              key={linha.id}
              id={linha.id}
              rotulo={linha.rotulo}
              valorAtual={linha.tss}
              aoMudar={(valor) => {
                mudarTss(linha.id, linha.categoria, valor);
              }}
            />
          ))}
        </div>
      )}

      <div className="grid grid-cols-3 gap-3 border-t border-hairline pt-3">
        <CampoDerivado
          rotulo="Ts_mpc (derivado)"
          testid="mpc-horizontes-ts-mpc"
          valor={horizontes === null ? "—" : `${formatarNumero(horizontes.tsMpc)} s`}
        />
        <CampoDerivado
          rotulo="Np (derivado)"
          testid="mpc-horizontes-np"
          valor={horizontes === null ? "—" : String(horizontes.np)}
        />
        <CampoDerivado
          rotulo="Nc (derivado)"
          testid="mpc-horizontes-nc"
          valor={horizontes === null ? "—" : String(horizontes.nc)}
        />
      </div>
      <p className="text-[10px] text-fg-muted">
        Np = ceil(max(TSS)/Ts_mpc); Nc = max(2, ceil(Np/4)) — nunca editados diretamente (RF-603).
      </p>

      {np60 && (
        <p data-testid="mpc-aviso-np60" className="text-xs text-warn">
          <span className="plaqueta mr-2 text-[10px]">Aviso</span>
          Np = {horizontes?.np} acima de 60 — referência de carga do solver (RNF-02): o solve
          pode não caber no orçamento de execução.
        </p>
      )}
      {dim120 && (
        <p data-testid="mpc-aviso-dimensao" className="text-xs text-warn">
          <span className="plaqueta mr-2 text-[10px]">Aviso</span>
          Dimensão de estados agregada ({dimensao}) acima de 120 — reduza TSS/tempo morto ou o
          número de pares habilitados na matriz (RF-608).
        </p>
      )}
    </div>
  );
}
