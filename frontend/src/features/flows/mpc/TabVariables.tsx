import { useRef, type ReactNode } from "react";

import { Button } from "../../../components/ui/button";
import { Input } from "../../../components/ui/input";
import { Label } from "../../../components/ui/label";
import { Select } from "../../../components/ui/select";
import { Tooltip, type TooltipContent } from "../../../components/ui/tooltip";
import type { TagOut } from "../../../lib/api";
import type {
  AcaoFalhaLinha,
  AcaoFalhaMv,
  ObjetivoCv,
  ObjetivoMv,
  ObjetivoRestricao,
  TipoLinhaMpc,
  VariaveisMpc,
  VariavelCv,
  VariavelDv,
  VariavelMv,
  VariavelRestricao,
} from "../graph";
import { Campo } from "../config/CamposComuns";
import { AJUDA_COMUM, AJUDA_CV, AJUDA_DV, AJUDA_LINHA, AJUDA_MV, AJUDA_RESTRICAO } from "./ajudaMpc";
import { CamposPid } from "./CamposPid";
import {
  gerarIdVariavel,
  nomeCampoVar,
  pidAoAlternar,
  tagsPorDirecao,
  variavelMvDoFormulario,
} from "./mpcLogic";
import { SelectTag } from "./SelectTag";

/** Rótulos do combobox "Função objetivo" por tipo de variável (ADR-027 §9 estendido) —
 *  `Record` completo por tipo para o TS provar em compile-time que nenhuma opção ficou sem
 *  rótulo (mesmo estilo dos `ROTULO_*` da casa). */
const ROTULO_OBJETIVO_MV: Record<ObjetivoMv, string> = {
  none: "Nenhuma",
  maximize: "Maximizar",
  minimize: "Minimizar",
  psv: "PSV (valor preferido)",
  equalize: "Equalizar",
};

const ROTULO_OBJETIVO_CV: Record<ObjetivoCv, string> = {
  none: "Nenhuma",
  maximize: "Maximizar",
  minimize: "Minimizar",
  observe_limit: "Observar limites",
  target: "Alvo (Target)",
  psv: "PSV (valor preferido)",
};

const ROTULO_OBJETIVO_RESTRICAO: Record<ObjetivoRestricao, string> = {
  none: "Nenhuma",
  maximize: "Maximizar",
  minimize: "Minimizar",
};

/** Rótulos da ação de falha (RF-613): MV não tem o que simular (sem modelo próprio). */
const ROTULO_FALHA_MV: Record<AcaoFalhaMv, string> = {
  no_action: "Sem ação",
  shed_local: "Shed p/ local",
  manual: "Manual",
};

const ROTULO_FALHA_LINHA: Record<AcaoFalhaLinha, string> = {
  no_action: "Sem ação",
  shed_local: "Shed p/ local",
  manual: "Manual",
  simulate_manual: "Simular→Manual",
  simulate_shed_local: "Simular→Local",
};

interface Props {
  variaveis: VariaveisMpc;
  aoMudar: (variaveis: VariaveisMpc) => void;
  tags: readonly TagOut[];
}

function CampoNomeEu({ id, nome, eu }: { id: string; nome: string; eu: string }) {
  return (
    <div className="grid grid-cols-2 gap-3">
      <div className="space-y-1">
        <Label htmlFor={`${id}-name`} tooltip={AJUDA_COMUM.nome}>Nome</Label>
        <Input id={`${id}-name`} name={nomeCampoVar(id, "name")} defaultValue={nome} />
      </div>
      <div className="space-y-1">
        <Label htmlFor={`${id}-eu`} tooltip={AJUDA_COMUM.eu}>EU</Label>
        <Input id={`${id}-eu`} name={nomeCampoVar(id, "eu")} defaultValue={eu} />
      </div>
    </div>
  );
}

/** Linha base de toda variável (RF-609/610): `description` (≤14, não-controlado) e a faixa
 *  de instrumento `zero`/`span` — a escala do faceplate e a base do ganho %/%. DV não tem
 *  description (o config não tem o campo): `comDescricao={false}` rende só zero/span. */
function CampoZeroSpan({
  id,
  descricao,
  zero,
  span,
  testidPrefixo,
}: {
  id: string;
  /** `undefined` (DV) omite o campo de descrição. */
  descricao: string | undefined;
  zero: number;
  span: number;
  testidPrefixo: string;
}) {
  return (
    <div className="grid grid-cols-3 gap-3">
      {descricao !== undefined && (
        <div className="space-y-1">
          <Label htmlFor={`${id}-description`} tooltip={AJUDA_COMUM.descricao}>Descrição</Label>
          <Input
            id={`${id}-description`}
            name={nomeCampoVar(id, "description")}
            defaultValue={descricao}
            maxLength={14}
            placeholder="descrição (≤14)"
            data-testid={`${testidPrefixo}-description`}
          />
        </div>
      )}
      <CampoNumero id={id} campo="zero" rotulo="Zero" valor={zero} testid={`${testidPrefixo}-zero`} tooltip={AJUDA_COMUM.zero} />
      <CampoNumero id={id} campo="span" rotulo="Span" valor={span} testid={`${testidPrefixo}-span`} tooltip={AJUDA_COMUM.span} />
    </div>
  );
}

/** Delega a `Campo` (`config/CamposComuns.tsx`, ARCH-21/TD-024): id HTML é `<id>-<campo>`
 *  (não-colidente entre variáveis, mesmo padrão de antes), `name` desacoplado pela convenção
 *  `nomeCampoVar` do MPC via o prop `nome`. `testid` só é desenhado quando o chamador passa
 *  um — metade dos campos do MPC nunca teve testid, e isso continua assim. */
function CampoNumero({
  id,
  campo,
  rotulo,
  valor,
  ajuda,
  testid,
  tooltip,
}: {
  id: string;
  campo: string;
  rotulo: string;
  /** `null` renderiza o campo VAZIO — é o que mantém `range: null` alcançável na DV: um "0"
   *  impresso aqui volta como texto não-vazio no Aplicar e vira a faixa degenerada `{0, 0}`,
   *  que o servidor recusa (`range.low < range.high`) e deixa o flow insalvável. */
  valor: number | null;
  /** Texto de apoio opcional (repassado a `Campo`) — usado quando o mesmo campo muda de
   *  significado por `kind` da linha (ex.: "Faixa do SP (%)" na CV integradora, RF-615
   *  revisado). Sem uso, comportamento idêntico a antes (`Campo` já trata como opcional). */
  ajuda?: string;
  testid?: string;
  tooltip?: TooltipContent;
}) {
  return (
    <Campo
      id={`${id}-${campo}`}
      nome={nomeCampoVar(id, campo)}
      rotulo={rotulo}
      valor={valor}
      ajuda={ajuda}
      testid={testid}
      tooltip={tooltip}
    />
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
                description: "",
                zero: 0,
                span: 100,
                limits: { min: 0, max: 100 },
                max_rate: 1,
                du_min: 0,
                move_weight: 1,
                initial_value: 0,
                // TD-003: ponto de linearização 0 e sem readback preservam o comportamento
                // anterior à tarefa (porta já nascia na coordenada absoluta da planta).
                operating_point: 0,
                readback_tag_id: null,
                pid: null,
                objective: "none",
                psv: null,
                fail_action: "no_action",
                local_shed_mode: null,
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
          <CampoZeroSpan
            id={mv.id}
            descricao={mv.description}
            zero={mv.zero}
            span={mv.span}
            testidPrefixo="mpc-mv"
          />
          <div className="grid grid-cols-3 gap-3">
            <CampoNumero id={mv.id} campo="limits_min" rotulo="Limite mín." valor={mv.limits.min} tooltip={AJUDA_MV.limiteMin} />
            <CampoNumero id={mv.id} campo="limits_max" rotulo="Limite máx." valor={mv.limits.max} tooltip={AJUDA_MV.limiteMax} />
            <CampoNumero
              id={mv.id}
              campo="max_rate"
              rotulo="Taxa máx (EU/s)"
              valor={mv.max_rate}
              testid="mpc-mv-max-rate"
              tooltip={AJUDA_MV.maxRate}
            />
            <CampoNumero
              id={mv.id}
              campo="du_min"
              rotulo="Δu mínimo"
              valor={mv.du_min}
              testid="mpc-mv-du-min"
              tooltip={AJUDA_MV.duMin}
            />
            <CampoNumero
              id={mv.id}
              campo="move_weight"
              rotulo="Peso de movimento"
              valor={mv.move_weight}
              testid="mpc-mv-move-weight"
              tooltip={AJUDA_MV.moveWeight}
            />
            <CampoNumero
              id={mv.id}
              campo="initial_value"
              rotulo="Valor inicial"
              valor={mv.initial_value}
              tooltip={AJUDA_MV.valorInicial}
            />
            <CampoNumero
              id={mv.id}
              campo="operating_point"
              rotulo="Ponto de operação"
              valor={mv.operating_point}
              tooltip={AJUDA_MV.pontoOperacao}
            />
            <CampoNumero
              id={mv.id}
              campo="readback_tag_id"
              rotulo="Tag de posição (readback)"
              valor={mv.readback_tag_id}
              tooltip={AJUDA_MV.readbackTag}
            />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1">
              <Label htmlFor={`${mv.id}-objective`} tooltip={AJUDA_MV.objetivo}>Função objetivo</Label>
              <Select
                id={`${mv.id}-objective`}
                data-testid={`mpc-objective-${mv.id}`}
                value={mv.objective}
                onChange={(evento) => {
                  const objective = evento.target.value as ObjetivoMv;
                  aoMudar(
                    mvs.map((item) =>
                      item.id !== mv.id
                        ? item
                        : {
                            ...item,
                            objective,
                            // PSV pede o valor preferido no mesmo gesto; fora dele o campo
                            // some do DOM e o `psv` volta a `null` (servidor valida as duas
                            // direções — "psv só vale com objetivo PSV").
                            psv: objective === "psv" ? (item.psv ?? 0) : null,
                          },
                    ),
                  );
                }}
              >
                {(Object.keys(ROTULO_OBJETIVO_MV) as ObjetivoMv[]).map((valor) => (
                  <option key={valor} value={valor}>
                    {ROTULO_OBJETIVO_MV[valor]}
                  </option>
                ))}
              </Select>
            </div>
            {mv.objective === "psv" && (
              <CampoNumero
                id={mv.id}
                campo="psv"
                rotulo="Valor preferido (PSV)"
                valor={mv.psv}
                testid="mpc-mv-psv"
                tooltip={AJUDA_MV.psv}
              />
            )}
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
            <Tooltip content={AJUDA_MV.comPid} stopClick>MV com PID (RF-604) — ausente ⇒ MV direta (decisão A-8)</Tooltip>
          </label>
          {mv.pid !== null && <CamposPid varId={mv.id} pid={mv.pid} tags={tags} />}
          <details className="space-y-2 border-t border-border pt-2">
            <summary className="plaqueta cursor-pointer text-[10px] text-fg-muted">
              Avançado
            </summary>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1">
                <Label htmlFor={`${mv.id}-fail-action`} tooltip={AJUDA_MV.failAction}>Ação de falha</Label>
                <Select
                  id={`${mv.id}-fail-action`}
                  data-testid="mpc-mv-fail-action"
                  value={mv.fail_action}
                  onChange={(evento) => {
                    const fail_action = evento.target.value as AcaoFalhaMv;
                    aoMudar(
                      mvs.map((item) =>
                        item.id !== mv.id
                          ? item
                          : {
                              ...item,
                              fail_action,
                              // Fora de shed_local o campo sai do DOM — zera junto para não
                              // ficar um modo de shed invisível guardado no config.
                              local_shed_mode:
                                fail_action === "shed_local" ? item.local_shed_mode : null,
                            },
                      ),
                    );
                  }}
                >
                  {(Object.keys(ROTULO_FALHA_MV) as AcaoFalhaMv[]).map((valor) => (
                    <option key={valor} value={valor}>
                      {ROTULO_FALHA_MV[valor]}
                    </option>
                  ))}
                </Select>
              </div>
              {mv.fail_action === "shed_local" && (
                <div className="space-y-1" title={mv.pid === null ? "Exige MV com PID" : undefined}>
                  <Label htmlFor={`${mv.id}-local_shed_mode`} tooltip={AJUDA_MV.localShedMode}>Modo local no shed</Label>
                  <Input
                    id={`${mv.id}-local_shed_mode`}
                    name={nomeCampoVar(mv.id, "local_shed_mode")}
                    type="text"
                    inputMode="decimal"
                    className="process-value"
                    defaultValue={mv.local_shed_mode === null ? "" : String(mv.local_shed_mode)}
                    disabled={mv.pid === null}
                    placeholder="auto do PID"
                    data-testid="mpc-mv-local-shed-mode"
                  />
                </div>
              )}
            </div>
          </details>
        </LinhaVariavel>
      ))}
    </div>
  );
}

function ListaCv({
  cvs,
  tags,
  aoMudar,
}: {
  cvs: VariavelCv[];
  tags: readonly TagOut[];
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
                description: "",
                zero: 0,
                span: 100,
                kind: "selfreg",
                tss: 600,
                weight: 1,
                sp_limits: { min: 0, max: 100 },
                priority: 1,
                objective: "none",
                traj_tau_s: 0,
                track_sp: true,
                fail_action: "no_action",
                fail_timeout_s: 60,
                sp_range_pct: null,
                remote_sp_tag_id: null,
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
          <CampoZeroSpan
            id={cv.id}
            descricao={cv.description}
            zero={cv.zero}
            span={cv.span}
            testidPrefixo="mpc-cv"
          />
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1">
              <Label htmlFor={`${cv.id}-kind`} tooltip={AJUDA_LINHA.kind}>Modelo (kind)</Label>
              <Select
                id={`${cv.id}-kind`}
                data-testid={`mpc-kind-${cv.id}`}
                value={cv.kind}
                onChange={(evento) => {
                  const kind = evento.target.value as TipoLinhaMpc;
                  aoMudar(
                    cvs.map((item) =>
                      item.id !== cv.id
                        ? item
                        : // Linha integradora não tem objetivo econômico (o LP decide TAXA,
                          // ADR-027 §4): trocar para ela zera no mesmo gesto — nunca fica um
                          // config inválido escondido atrás de um select desabilitado.
                          { ...item, kind, objective: kind === "integrating" ? "none" : item.objective },
                    ),
                  );
                }}
              >
                <option value="selfreg">Autorregulável (SOPDT)</option>
                <option value="integrating">Integrador (IOPDT)</option>
              </Select>
            </div>
            <div className="space-y-1">
              <Label htmlFor={`${cv.id}-objective`} tooltip={AJUDA_CV.objetivo}>Função objetivo</Label>
              <Select
                id={`${cv.id}-objective`}
                data-testid={`mpc-objective-${cv.id}`}
                value={cv.objective}
                disabled={cv.kind === "integrating"}
                title={
                  cv.kind === "integrating"
                    ? "Linha integradora não tem função objetivo (o SSTO decide taxa, não nível)"
                    : undefined
                }
                onChange={(evento) => {
                  const objective = evento.target.value as ObjetivoCv;
                  aoMudar(cvs.map((item) => (item.id !== cv.id ? item : { ...item, objective })));
                }}
              >
                {(Object.keys(ROTULO_OBJETIVO_CV) as ObjetivoCv[]).map((valor) => (
                  <option key={valor} value={valor}>
                    {ROTULO_OBJETIVO_CV[valor]}
                  </option>
                ))}
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
              tooltip={AJUDA_CV.peso}
            />
            <CampoNumero
              id={cv.id}
              campo="priority"
              rotulo="Prioridade"
              valor={cv.priority}
              testid="mpc-cv-priority"
              tooltip={AJUDA_LINHA.prioridade}
            />
            <CampoNumero
              id={cv.id}
              campo="traj_tau_s"
              rotulo="Trajetória τ (s)"
              valor={cv.traj_tau_s}
              testid="mpc-cv-traj-tau"
              tooltip={AJUDA_CV.trajTau}
            />
          </div>
          <label className="flex items-center gap-2 text-xs text-fg">
            <input
              type="checkbox"
              data-testid="mpc-cv-track-sp"
              checked={cv.track_sp}
              onChange={(evento) => {
                const track_sp = evento.target.checked;
                aoMudar(cvs.map((item) => (item.id !== cv.id ? item : { ...item, track_sp })));
              }}
              className="h-3.5 w-3.5 accent-[var(--color-accent)]"
            />
            <Tooltip content={AJUDA_CV.trackSp} stopClick>SP rastreia PV fora de AUTO (RF-612)</Tooltip>
          </label>
          <div className="grid grid-cols-2 gap-3">
            <CampoNumero
              id={cv.id}
              campo="sp_limits_min"
              rotulo="SP mín."
              valor={cv.sp_limits.min}
              tooltip={AJUDA_CV.spMin}
            />
            <CampoNumero
              id={cv.id}
              campo="sp_limits_max"
              rotulo="SP máx."
              valor={cv.sp_limits.max}
              tooltip={AJUDA_CV.spMax}
            />
          </div>
          <details className="space-y-2 border-t border-border pt-2">
            <summary className="plaqueta cursor-pointer text-[10px] text-fg-muted">
              Avançado
            </summary>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1">
                <Label htmlFor={`${cv.id}-fail-action`} tooltip={AJUDA_LINHA.failAction}>Ação de falha</Label>
                <Select
                  id={`${cv.id}-fail-action`}
                  data-testid="mpc-cv-fail-action"
                  value={cv.fail_action}
                  onChange={(evento) => {
                    const fail_action = evento.target.value as AcaoFalhaLinha;
                    aoMudar(
                      cvs.map((item) => (item.id !== cv.id ? item : { ...item, fail_action })),
                    );
                  }}
                >
                  {(Object.keys(ROTULO_FALHA_LINHA) as AcaoFalhaLinha[]).map((valor) => (
                    <option key={valor} value={valor}>
                      {ROTULO_FALHA_LINHA[valor]}
                    </option>
                  ))}
                </Select>
              </div>
              {cv.fail_action !== "no_action" && (
                <CampoNumero
                  id={cv.id}
                  campo="fail_timeout_s"
                  rotulo="Timeout de falha (s)"
                  valor={cv.fail_timeout_s}
                  testid="mpc-cv-fail-timeout"
                  tooltip={AJUDA_LINHA.failTimeout}
                />
              )}
              <CampoNumero
                id={cv.id}
                campo="sp_range_pct"
                rotulo="Faixa do SP (%)"
                valor={cv.sp_range_pct}
                ajuda={
                  cv.kind === "integrating"
                    ? "Linha integradora: vira drift tolerado (% do span) ao longo do TSS da linha, não faixa de nível fixa."
                    : undefined
                }
                testid="mpc-cv-sp-range-pct"
                tooltip={AJUDA_CV.spRangePct}
              />
              <div className="space-y-1">
                <Label htmlFor={`${cv.id}-remote-sp`} tooltip={AJUDA_CV.remoteSp}>SP remoto (tag R, RF-614)</Label>
                <SelectTag
                  id={`${cv.id}-remote-sp`}
                  campo="remote_sp_tag_id"
                  varId={cv.id}
                  tags={tagsPorDirecao(tags, "r")}
                  valorAtual={cv.remote_sp_tag_id}
                  testid="mpc-cv-remote-sp-tag"
                />
              </div>
            </div>
          </details>
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
                description: "",
                zero: 0,
                span: 100,
                kind: "selfreg",
                tss: 600,
                range: { low: 0, high: 100 },
                priority: 1,
                objective: "none",
                fail_action: "no_action",
                fail_timeout_s: 60,
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
          <CampoZeroSpan
            id={co.id}
            descricao={co.description}
            zero={co.zero}
            span={co.span}
            testidPrefixo="mpc-restricao"
          />
          <div className="space-y-1">
            <Label htmlFor={`${co.id}-kind`} tooltip={AJUDA_LINHA.kind}>Modelo (kind)</Label>
            <Select
              id={`${co.id}-kind`}
              data-testid={`mpc-kind-${co.id}`}
              value={co.kind}
              onChange={(evento) => {
                const kind = evento.target.value as TipoLinhaMpc;
                aoMudar(
                  constraints.map((item) =>
                    item.id !== co.id
                      ? item
                      : // Mesma regra da CV: integradora não tem objetivo econômico — zera no
                        // mesmo gesto (servidor rejeita com "Objetivo econômico exige linha
                        // autorregulável (selfreg)").
                        { ...item, kind, objective: kind === "integrating" ? "none" : item.objective },
                  ),
                );
              }}
            >
              <option value="selfreg">Autorregulável (SOPDT)</option>
              <option value="integrating">Integrador (IOPDT)</option>
            </Select>
          </div>
          <div className="space-y-1">
            <Label htmlFor={`${co.id}-objective`} tooltip={AJUDA_RESTRICAO.objetivo}>Função objetivo</Label>
            <Select
              id={`${co.id}-objective`}
              data-testid={`mpc-objective-${co.id}`}
              value={co.objective}
              disabled={co.kind === "integrating"}
              title={
                co.kind === "integrating"
                  ? "Linha integradora não tem função objetivo (o SSTO decide taxa, não nível)"
                  : undefined
              }
              onChange={(evento) => {
                const objective = evento.target.value as ObjetivoRestricao;
                aoMudar(
                  constraints.map((item) => (item.id !== co.id ? item : { ...item, objective })),
                );
              }}
            >
              {(Object.keys(ROTULO_OBJETIVO_RESTRICAO) as ObjetivoRestricao[]).map((valor) => (
                <option key={valor} value={valor}>
                  {ROTULO_OBJETIVO_RESTRICAO[valor]}
                </option>
              ))}
            </Select>
          </div>
          {/* TSS mora só na aba Horizontes (tarefa 4.3) — mesma nota da ListaCv acima. */}
          <div className="grid grid-cols-3 gap-3">
            <CampoNumero id={co.id} campo="range_low" rotulo="Faixa mín." valor={co.range.low} tooltip={AJUDA_RESTRICAO.faixaMin} />
            <CampoNumero id={co.id} campo="range_high" rotulo="Faixa máx." valor={co.range.high} tooltip={AJUDA_RESTRICAO.faixaMax} />
            <CampoNumero id={co.id} campo="priority" rotulo="Prioridade" valor={co.priority} tooltip={AJUDA_LINHA.prioridade} />
          </div>
          <details className="space-y-2 border-t border-border pt-2">
            <summary className="plaqueta cursor-pointer text-[10px] text-fg-muted">
              Avançado
            </summary>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1">
                <Label htmlFor={`${co.id}-fail-action`} tooltip={AJUDA_LINHA.failAction}>Ação de falha</Label>
                <Select
                  id={`${co.id}-fail-action`}
                  data-testid="mpc-restricao-fail-action"
                  value={co.fail_action}
                  onChange={(evento) => {
                    const fail_action = evento.target.value as AcaoFalhaLinha;
                    aoMudar(
                      constraints.map((item) =>
                        item.id !== co.id ? item : { ...item, fail_action },
                      ),
                    );
                  }}
                >
                  {(Object.keys(ROTULO_FALHA_LINHA) as AcaoFalhaLinha[]).map((valor) => (
                    <option key={valor} value={valor}>
                      {ROTULO_FALHA_LINHA[valor]}
                    </option>
                  ))}
                </Select>
              </div>
              {co.fail_action !== "no_action" && (
                <CampoNumero
                  id={co.id}
                  campo="fail_timeout_s"
                  rotulo="Timeout de falha (s)"
                  valor={co.fail_timeout_s}
                  testid="mpc-restricao-fail-timeout"
                  tooltip={AJUDA_LINHA.failTimeout}
                />
              )}
            </div>
          </details>
        </LinhaVariavel>
      ))}
    </div>
  );
}

/** Linha de uma DV. Os dois campos de faixa seguem não-controlados (padrão do modal). A
 *  barra do faceplate usa a faixa de instrumento (zero/span, RF-609) — o `range` opcional da
 *  DV não alimenta mais escala nenhuma. */
function LinhaDv({ dv, aoRemover }: { dv: VariavelDv; aoRemover: () => void }) {
  return (
    <LinhaVariavel varId={dv.id} testid={`mpc-var-row-${dv.id}`} aoRemover={aoRemover}>
      <CampoNomeEu id={dv.id} nome={dv.name} eu={dv.eu} />
      <CampoZeroSpan
        id={dv.id}
        descricao={undefined}
        zero={dv.zero}
        span={dv.span}
        testidPrefixo="mpc-dv"
      />
      <div className="grid grid-cols-2 gap-3">
        <CampoNumero id={dv.id} campo="range_low" rotulo="Faixa mín." valor={dv.range?.low ?? null} tooltip={AJUDA_DV.faixaMin} />
        <CampoNumero id={dv.id} campo="range_high" rotulo="Faixa máx." valor={dv.range?.high ?? null} tooltip={AJUDA_DV.faixaMax} />
      </div>
      {/* TD-003: ponto de linearização — o modelo do MPC é incremental, então a porta de
          entrada da DV fica na coordenada absoluta da planta, sem Script somando constantes. */}
      <CampoNumero
        id={dv.id}
        campo="operating_point"
        rotulo="Ponto de operação"
        valor={dv.operating_point}
        tooltip={AJUDA_DV.pontoOperacao}
      />
    </LinhaVariavel>
  );
}

/** DVs têm faixa OPCIONAL (spec §4.2-5, RFC-16, ao contrário de MV/CV/Restrição, que sempre
 *  têm uma): os dois campos ficam ao lado de Nome/EU, mesmo padrão `CampoNumero` que a
 *  Restrição já usa para `range_low`/`range_high` (`ListaRestricao` acima). */
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
              {
                id: gerarIdVariavel("dv"),
                name: "",
                eu: "",
                zero: 0,
                span: 100,
                range: null,
                operating_point: 0,
              },
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
      <ListaCv cvs={variaveis.cvs} tags={tags} aoMudar={(cvs) => aoMudar({ ...variaveis, cvs })} />
      <ListaRestricao
        constraints={variaveis.constraints}
        aoMudar={(constraints) => aoMudar({ ...variaveis, constraints })}
      />
      <ListaDv dvs={variaveis.dvs} aoMudar={(dvs) => aoMudar({ ...variaveis, dvs })} />
    </div>
  );
}
