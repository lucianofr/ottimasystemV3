import { useRef, useState, type ReactNode } from "react";

import { Button } from "../../../components/ui/button";
import { Input } from "../../../components/ui/input";
import { Label } from "../../../components/ui/label";
import { Select } from "../../../components/ui/select";
import type { TagOut } from "../../../lib/api";
import type {
  TipoLinhaMpc,
  VariaveisMpc,
  VariavelCv,
  VariavelDv,
  VariavelMv,
  VariavelRestricao,
} from "../graph";
import { CamposPid } from "./CamposPid";
import { gerarIdVariavel, nomeCampoVar, pidAoAlternar, variavelMvDoFormulario } from "./mpcLogic";

interface Props {
  variaveis: VariaveisMpc;
  aoMudar: (variaveis: VariaveisMpc) => void;
  tags: readonly TagOut[];
}

function CampoNomeEu({ id, nome, eu }: { id: string; nome: string; eu: string }) {
  return (
    <div className="grid grid-cols-2 gap-3">
      <div className="space-y-1">
        <Label htmlFor={`${id}-name`}>Nome</Label>
        <Input id={`${id}-name`} name={nomeCampoVar(id, "name")} defaultValue={nome} />
      </div>
      <div className="space-y-1">
        <Label htmlFor={`${id}-eu`}>EU</Label>
        <Input id={`${id}-eu`} name={nomeCampoVar(id, "eu")} defaultValue={eu} />
      </div>
    </div>
  );
}

function CampoNumero({
  id,
  campo,
  rotulo,
  valor,
  testid,
}: {
  id: string;
  campo: string;
  rotulo: string;
  /** `null` renderiza o campo VAZIO — é o que mantém `range: null` alcançável na DV: um "0"
   *  impresso aqui volta como texto não-vazio no Aplicar e vira a faixa degenerada `{0, 0}`,
   *  que o servidor recusa (`range.low < range.high`) e deixa o flow insalvável. */
  valor: number | null;
  testid?: string;
}) {
  return (
    <div className="space-y-1">
      <Label htmlFor={`${id}-${campo}`}>{rotulo}</Label>
      <Input
        id={`${id}-${campo}`}
        name={nomeCampoVar(id, campo)}
        type="text"
        inputMode="decimal"
        className="process-value"
        defaultValue={valor === null ? "" : String(valor)}
        data-testid={testid}
      />
    </div>
  );
}

function LinhaVariavel({
  varId,
  testid,
  aoRemover,
  children,
}: {
  varId: string;
  testid: string;
  aoRemover: () => void;
  children: ReactNode;
}) {
  return (
    <fieldset
      data-testid={testid}
      data-var-id={varId}
      title={varId}
      className="space-y-2 rounded-sm border border-border bg-well p-3"
    >
      <legend className="plaqueta flex w-full items-center justify-between px-1 text-[10px] text-fg-muted">
        <span className="process-value">{varId}</span>
        <Button type="button" variant="outline" size="sm" onClick={aoRemover}>
          Remover
        </Button>
      </legend>
      {children}
    </fieldset>
  );
}

function ListaMv({
  mvs,
  tags,
  aoMudar,
}: {
  mvs: VariavelMv[];
  tags: readonly TagOut[];
  aoMudar: (mvs: VariavelMv[]) => void;
}) {
  // Fix final (Important): cache FORA do estado controlado do último `pid` capturado do
  // DOM antes de um uncheck — `pidAoAlternar` usa isto para não reconstruir do zero (e
  // descartar o digitado) num recheck sem troca de aba (mesma classe de bug da revisão 4.3).
  const ultimosPid = useRef<Record<string, VariavelMv["pid"]>>({});
  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="plaqueta text-xs text-fg-muted">MVs (saídas manipuladas)</h3>
        <Button
          type="button"
          size="sm"
          data-testid="mpc-add-mv"
          onClick={() => {
            const id = gerarIdVariavel("mv");
            aoMudar([
              ...mvs,
              {
                id,
                name: "",
                eu: "",
                limits: { min: 0, max: 100 },
                du_max: 1,
                du_min: 0,
                move_weight: 1,
                initial_value: 0,
                // TD-003: ponto de linearização 0 e sem readback preservam o comportamento
                // anterior à tarefa (porta já nascia na coordenada absoluta da planta).
                operating_point: 0,
                readback_tag_id: null,
                pid: null,
              },
            ]);
          }}
        >
          Adicionar MV
        </Button>
      </div>
      {mvs.map((mv) => (
        <LinhaVariavel
          key={mv.id}
          varId={mv.id}
          testid={`mpc-var-row-${mv.id}`}
          aoRemover={() => aoMudar(mvs.filter((item) => item.id !== mv.id))}
        >
          <CampoNomeEu id={mv.id} nome={mv.name} eu={mv.eu} />
          <div className="grid grid-cols-3 gap-3">
            <CampoNumero id={mv.id} campo="limits_min" rotulo="Limite mín." valor={mv.limits.min} />
            <CampoNumero id={mv.id} campo="limits_max" rotulo="Limite máx." valor={mv.limits.max} />
            <CampoNumero id={mv.id} campo="du_max" rotulo="Δu máx." valor={mv.du_max} />
            <CampoNumero
              id={mv.id}
              campo="du_min"
              rotulo="Δu mínimo"
              valor={mv.du_min}
              testid="mpc-mv-du-min"
            />
            <CampoNumero
              id={mv.id}
              campo="move_weight"
              rotulo="Peso de movimento"
              valor={mv.move_weight}
              testid="mpc-mv-move-weight"
            />
            <CampoNumero
              id={mv.id}
              campo="initial_value"
              rotulo="Valor inicial"
              valor={mv.initial_value}
            />
            <CampoNumero
              id={mv.id}
              campo="operating_point"
              rotulo="Ponto de operação"
              valor={mv.operating_point}
            />
            <CampoNumero
              id={mv.id}
              campo="readback_tag_id"
              rotulo="Tag de posição (readback)"
              valor={mv.readback_tag_id}
            />
          </div>
          <label className="flex items-center gap-2 text-xs text-fg">
            <input
              type="checkbox"
              data-testid={`mpc-pid-toggle-${mv.id}`}
              checked={mv.pid !== null}
              onChange={(evento) => {
                const comPid = evento.target.checked;
                const formulario = evento.target.form;
                if (!comPid && mv.pid !== null && formulario !== null) {
                  // Captura os campos do pid ainda montados no DOM neste instante — antes
                  // do React desmontar `CamposPid` — para o recheck poder restaurá-los.
                  ultimosPid.current[mv.id] = variavelMvDoFormulario(
                    mv,
                    new FormData(formulario),
                    true,
                  ).pid;
                }
                aoMudar(
                  mvs.map((item) =>
                    item.id !== mv.id
                      ? item
                      : { ...item, pid: pidAoAlternar(comPid, ultimosPid.current[mv.id] ?? null) },
                  ),
                );
              }}
              className="h-3.5 w-3.5 accent-[var(--color-accent)]"
            />
            MV com PID (RF-604) — ausente ⇒ MV direta (decisão A-8)
          </label>
          {mv.pid !== null && <CamposPid varId={mv.id} pid={mv.pid} tags={tags} />}
        </LinhaVariavel>
      ))}
    </div>
  );
}

function ListaCv({
  cvs,
  aoMudar,
}: {
  cvs: VariavelCv[];
  aoMudar: (cvs: VariavelCv[]) => void;
}) {
  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="plaqueta text-xs text-fg-muted">CVs (variáveis controladas)</h3>
        <Button
          type="button"
          size="sm"
          data-testid="mpc-add-cv"
          onClick={() => {
            const id = gerarIdVariavel("cv");
            aoMudar([
              ...cvs,
              {
                id,
                name: "",
                eu: "",
                kind: "selfreg",
                tss: 600,
                weight: 1,
                sp_limits: { min: 0, max: 100 },
              },
            ]);
          }}
        >
          Adicionar CV
        </Button>
      </div>
      {cvs.map((cv) => (
        <LinhaVariavel
          key={cv.id}
          varId={cv.id}
          testid={`mpc-var-row-${cv.id}`}
          aoRemover={() => aoMudar(cvs.filter((item) => item.id !== cv.id))}
        >
          <CampoNomeEu id={cv.id} nome={cv.name} eu={cv.eu} />
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1">
              <Label htmlFor={`${cv.id}-kind`}>Modelo (kind)</Label>
              <Select
                id={`${cv.id}-kind`}
                data-testid={`mpc-kind-${cv.id}`}
                value={cv.kind}
                onChange={(evento) => {
                  const kind = evento.target.value as TipoLinhaMpc;
                  aoMudar(cvs.map((item) => (item.id !== cv.id ? item : { ...item, kind })));
                }}
              >
                <option value="selfreg">Autorregulável (SOPDT)</option>
                <option value="integrating">Integrador (IOPDT)</option>
              </Select>
            </div>
            {/* TSS mora só na aba Horizontes (tarefa 4.3): precisa ser estado controlado
                para Ts_mpc/Np/Nc derivarem ao vivo — um segundo campo aqui, não-controlado,
                divergiria do que o usuário digitou lá. */}
            <CampoNumero
              id={cv.id}
              campo="weight"
              rotulo="Peso"
              valor={cv.weight}
              testid="mpc-cv-weight"
            />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <CampoNumero
              id={cv.id}
              campo="sp_limits_min"
              rotulo="SP mín."
              valor={cv.sp_limits.min}
            />
            <CampoNumero
              id={cv.id}
              campo="sp_limits_max"
              rotulo="SP máx."
              valor={cv.sp_limits.max}
            />
          </div>
        </LinhaVariavel>
      ))}
    </div>
  );
}

function ListaRestricao({
  constraints,
  aoMudar,
}: {
  constraints: VariavelRestricao[];
  aoMudar: (constraints: VariavelRestricao[]) => void;
}) {
  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="plaqueta text-xs text-fg-muted">Restrições</h3>
        <Button
          type="button"
          size="sm"
          data-testid="mpc-add-constraint"
          onClick={() => {
            const id = gerarIdVariavel("co");
            aoMudar([
              ...constraints,
              {
                id,
                name: "",
                eu: "",
                kind: "selfreg",
                tss: 600,
                range: { low: 0, high: 100 },
                priority: 1,
              },
            ]);
          }}
        >
          Adicionar restrição
        </Button>
      </div>
      {constraints.map((co) => (
        <LinhaVariavel
          key={co.id}
          varId={co.id}
          testid={`mpc-var-row-${co.id}`}
          aoRemover={() => aoMudar(constraints.filter((item) => item.id !== co.id))}
        >
          <CampoNomeEu id={co.id} nome={co.name} eu={co.eu} />
          <div className="space-y-1">
            <Label htmlFor={`${co.id}-kind`}>Modelo (kind)</Label>
            <Select
              id={`${co.id}-kind`}
              data-testid={`mpc-kind-${co.id}`}
              value={co.kind}
              onChange={(evento) => {
                const kind = evento.target.value as TipoLinhaMpc;
                aoMudar(
                  constraints.map((item) => (item.id !== co.id ? item : { ...item, kind })),
                );
              }}
            >
              <option value="selfreg">Autorregulável (SOPDT)</option>
              <option value="integrating">Integrador (IOPDT)</option>
            </Select>
          </div>
          {/* TSS mora só na aba Horizontes (tarefa 4.3) — mesma nota da ListaCv acima. */}
          <div className="grid grid-cols-3 gap-3">
            <CampoNumero id={co.id} campo="range_low" rotulo="Faixa mín." valor={co.range.low} />
            <CampoNumero id={co.id} campo="range_high" rotulo="Faixa máx." valor={co.range.high} />
            <CampoNumero id={co.id} campo="priority" rotulo="Prioridade" valor={co.priority} />
          </div>
        </LinhaVariavel>
      ))}
    </div>
  );
}

/** Linha de uma DV. Os dois campos de faixa seguem não-controlados (padrão do modal), mas a
 *  nota precisa sumir assim que o operador digita — senão contradiz o que ele está vendo. Um
 *  `onInput` no par de campos basta: lê o DOM sob demanda, sem tornar os inputs controlados. */
function LinhaDv({ dv, aoRemover }: { dv: VariavelDv; aoRemover: () => void }) {
  const [digitou, setDigitou] = useState(dv.range !== null);
  const faixa = useRef<HTMLDivElement>(null);
  return (
    <LinhaVariavel varId={dv.id} testid={`mpc-var-row-${dv.id}`} aoRemover={aoRemover}>
      <CampoNomeEu id={dv.id} nome={dv.name} eu={dv.eu} />
      <div
        ref={faixa}
        className="grid grid-cols-2 gap-3"
        onInput={() => {
          const campos = faixa.current?.querySelectorAll("input") ?? [];
          setDigitou(Array.from(campos).some((campo) => campo.value.trim() !== ""));
        }}
      >
        <CampoNumero id={dv.id} campo="range_low" rotulo="Faixa mín." valor={dv.range?.low ?? null} />
        <CampoNumero id={dv.id} campo="range_high" rotulo="Faixa máx." valor={dv.range?.high ?? null} />
      </div>
      {/* TD-003: ponto de linearização — o modelo do MPC é incremental, então a porta de
          entrada da DV fica na coordenada absoluta da planta, sem Script somando constantes. */}
      <CampoNumero
        id={dv.id}
        campo="operating_point"
        rotulo="Ponto de operação"
        valor={dv.operating_point}
      />
      {!digitou && (
        <p className="text-[10px] text-fg-muted">
          Sem faixa: o faceplate desta DV ficará sem barra (RF-702).
        </p>
      )}
    </LinhaVariavel>
  );
}

/** DVs têm faixa OPCIONAL (spec §4.2-5, RFC-16, ao contrário de MV/CV/Restrição, que sempre
 *  têm uma): os dois campos ficam ao lado de Nome/EU, mesmo padrão `CampoNumero` que a
 *  Restrição já usa para `range_low`/`range_high` (`ListaRestricao` acima). Sem faixa, uma
 *  nota discreta avisa que o faceplate (§6.5) ficará sem barra — RF-702 pede limites, e
 *  omissão silenciosa é exatamente o defeito que RFC-16 fecha. */
function ListaDv({
  dvs,
  aoMudar,
}: {
  dvs: VariavelDv[];
  aoMudar: (dvs: VariavelDv[]) => void;
}) {
  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="plaqueta text-xs text-fg-muted">DVs (distúrbios medidos)</h3>
        <Button
          type="button"
          size="sm"
          data-testid="mpc-add-dv"
          onClick={() =>
            aoMudar([
              ...dvs,
              { id: gerarIdVariavel("dv"), name: "", eu: "", range: null, operating_point: 0 },
            ])
          }
        >
          Adicionar DV
        </Button>
      </div>
      {dvs.map((dv) => (
        <LinhaDv
          key={dv.id}
          dv={dv}
          aoRemover={() => aoMudar(dvs.filter((item) => item.id !== dv.id))}
        />
      ))}
    </div>
  );
}

/** Aba Variáveis (spec F4 §7.3, §2.1): 4 listas com criar/remover. Estrutura (ids, `kind`,
 *  presença do `pid`) vive em estado controlado — decide o que renderiza e é usada pela aba
 *  Modelos; nome/EU/números ficam não-controlados, lidos pelo id no Aplicar (mesmo padrão do
 *  TFS, `config/CamposTfs.tsx`). */
export function TabVariables({ variaveis, aoMudar, tags }: Props) {
  return (
    <div data-testid="mpc-tab-variaveis" className="space-y-6">
      <ListaMv mvs={variaveis.mvs} tags={tags} aoMudar={(mvs) => aoMudar({ ...variaveis, mvs })} />
      <ListaCv cvs={variaveis.cvs} aoMudar={(cvs) => aoMudar({ ...variaveis, cvs })} />
      <ListaRestricao
        constraints={variaveis.constraints}
        aoMudar={(constraints) => aoMudar({ ...variaveis, constraints })}
      />
      <ListaDv dvs={variaveis.dvs} aoMudar={(dvs) => aoMudar({ ...variaveis, dvs })} />
    </div>
  );
}
