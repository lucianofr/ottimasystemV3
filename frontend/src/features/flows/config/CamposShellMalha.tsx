import { Label } from "../../../components/ui/label";
import { Select } from "../../../components/ui/select";
import { SHED_OPTS, type DadosShellMalha } from "../graph";
import { caixaDeModoDesabilitada, MODOS_COM_CAIXA, PORTA_DO_MODO_REMOTO } from "./campos";
import { Campo, CampoBooleano } from "./CamposComuns";

/**
 * Seções de shell dos blocos malha (RF-641, RF-642, RF-644): o mesmo conjunto de campos para
 * PID Malha e Fuzzy Malha, só o recorte muda com o `tipo`. Tracking/override e feedforward
 * existem apenas no PID Malha e vêm em `<details>` nativo recolhido — os inputs continuam no
 * DOM e entram no `FormData` do Aplicar mesmo fechados (um checkbox ausente seria lido como
 * desmarcado), então NUNCA se condiciona a renderização ao estado aberto/fechado.
 *
 * Campos não-controlados lidos por `montarDadosShellMalha` (`campos.ts`): o `name` de cada
 * input é o nome do campo no contrato, exceto `permitted`, que é uma caixa por modo
 * (`permitted_<modo>`). Faixas e coerência (SP mín < máx, OUT mín < máx…) são validadas no
 * servidor (422 em pt-BR no Salvar); nada é replicado aqui.
 */

type TipoMalha = "pid_loop" | "fuzzy_loop";

const MODOS_NORMAIS: Record<TipoMalha, readonly { valor: string; rotulo: string }[]> = {
  pid_loop: [
    { valor: "man", rotulo: "MAN" },
    { valor: "auto", rotulo: "AUTO" },
    { valor: "cas", rotulo: "CAS" },
    { valor: "rcas", rotulo: "RCAS" },
  ],
  fuzzy_loop: [
    { valor: "man", rotulo: "MAN" },
    { valor: "auto", rotulo: "AUTO" },
  ],
};

const ROTULO_SHED: Record<(typeof SHED_OPTS)[number], string> = {
  shed_to_auto: "ir para AUTO",
  shed_to_man: "ir para MAN",
  shed_to_normal: "ir para o modo normal",
};

/** Fuzzy Malha v2 não tem cascata: só OOS/MAN/AUTO (o servidor recusa os demais). */
const MODOS_DO_FUZZY: readonly string[] = ["oos", "man", "auto"];

const ESTILO_LEGENDA = "plaqueta text-[10px] text-fg-muted";

export function CamposShellMalha({
  dados,
  tipo,
  portasLigadas,
}: {
  dados: DadosShellMalha;
  tipo: TipoMalha;
  portasLigadas: ReadonlySet<string>;
}) {
  const ehPid = tipo === "pid_loop";
  const modos = ehPid ? MODOS_COM_CAIXA : MODOS_COM_CAIXA.filter((modo) => MODOS_DO_FUZZY.includes(modo));

  return (
    <div className="space-y-4">
      <fieldset className="space-y-2">
        <legend className={ESTILO_LEGENDA}>Setpoint</legend>
        <div className="grid grid-cols-2 gap-3">
          <Campo
            id="sp_lo_lim"
            rotulo="SP mínimo (EU)"
            valor={dados.sp_lo_lim}
            ajuda="Menor setpoint que o operador pode ajustar. Precisa ser menor que o SP máximo."
          />
          <Campo
            id="sp_hi_lim"
            rotulo="SP máximo (EU)"
            valor={dados.sp_hi_lim}
            ajuda="Maior setpoint que o operador pode ajustar."
          />
          <Campo
            id="sp_rate_up"
            rotulo="Rampa de subida (vazio = sem rampa) · EU/s"
            valor={dados.sp_rate_up}
            placeholder="sem rampa"
            ajuda="Máxima taxa de subida do SP."
          />
          <Campo
            id="sp_rate_dn"
            rotulo="Rampa de descida (vazio = sem rampa) · EU/s"
            valor={dados.sp_rate_dn}
            placeholder="sem rampa"
            ajuda="Máxima taxa de descida do SP."
          />
        </div>
        <CampoBooleano
          id="sp_pv_track_in_man"
          rotulo="SP acompanha a PV em manual"
          valor={dados.sp_pv_track_in_man}
          ajuda="Em MAN o SP segue a PV, e a volta para AUTO sai sem degrau."
        />
      </fieldset>

      <fieldset className="space-y-2">
        <legend className={ESTILO_LEGENDA}>Saída</legend>
        <div className="grid grid-cols-2 gap-3">
          <Campo
            id="out_scale_lo"
            rotulo="Escala de OUT mínima — estrutural (EU)"
            valor={dados.out_scale_lo}
            ajuda="Valor em EU da saída em 0 %; a porta out emite o valor escalado."
          />
          <Campo
            id="out_scale_hi"
            rotulo="Escala de OUT máxima — estrutural (EU)"
            valor={dados.out_scale_hi}
            ajuda="Valor em EU da saída em 100 %. Em cascata, é a faixa de SP do secundário."
          />
          {/* RF-644: a escala de OUT está em LOOP_STRUCTURAL_KEYS — mesmo aviso do FLL. */}
          <p className="col-span-2 text-[10px] leading-tight text-warn-fg">
            Atenção: a escala de OUT é ESTRUTURAL — a troca re-instancia o bloco no próximo deploy
            e a malha aterrissa em MAN com a saída mantida (bumpless).
          </p>
          <Campo
            id="out_lo_lim"
            rotulo="Limite de saída mínimo (%)"
            valor={dados.out_lo_lim}
            ajuda="Piso da saída. Precisa ser menor que o limite máximo."
          />
          <Campo
            id="out_hi_lim"
            rotulo="Limite de saída máximo (%)"
            valor={dados.out_hi_lim}
            ajuda="Teto da saída."
          />
          <Campo
            id="out_rate_up"
            rotulo="Rampa de saída subida (vazio = sem rampa) · %/s"
            valor={dados.out_rate_up}
            placeholder="sem rampa"
            ajuda="Máxima taxa de subida da saída."
          />
          <Campo
            id="out_rate_dn"
            rotulo="Rampa de saída descida (vazio = sem rampa) · %/s"
            valor={dados.out_rate_dn}
            placeholder="sem rampa"
            ajuda="Máxima taxa de descida da saída."
          />
          <Campo
            id="out_startup"
            rotulo="Saída de partida (%)"
            valor={dados.out_startup}
            ajuda="Saída assumida na partida do bloco; fica entre os limites de saída."
          />
          <Campo
            id="pv_ftime"
            rotulo="Filtro de PV (0 desliga) · s"
            valor={dados.pv_ftime}
            ajuda="Constante de tempo do filtro da PV."
          />
        </div>
      </fieldset>

      <fieldset className="space-y-3">
        <legend className={ESTILO_LEGENDA}>Modos</legend>
        <fieldset className="space-y-1">
          <legend className="text-xs text-fg">Modos permitidos</legend>
          <div className="flex flex-wrap gap-x-4 gap-y-1">
            {modos.map((modo) => {
              const marcado = dados.permitted.includes(modo);
              const desabilitado = caixaDeModoDesabilitada(modo, portasLigadas, marcado);
              const id = `permitted_${modo}`;
              const idMotivo = `${id}-motivo`;
              return (
                <div key={modo} className="space-y-0.5">
                  <label className="flex items-center gap-2 text-xs text-fg" htmlFor={id}>
                    <input
                      type="checkbox"
                      id={id}
                      name={id}
                      data-testid={`config-permitted-${modo}`}
                      defaultChecked={marcado}
                      disabled={desabilitado}
                      aria-describedby={desabilitado ? idMotivo : undefined}
                      className="h-3.5 w-3.5 accent-[var(--color-accent)]"
                    />
                    {modo.toUpperCase()}
                  </label>
                  {desabilitado && (
                    <p id={idMotivo} className="text-[10px] leading-tight text-fg-muted">
                      ligue a porta {PORTA_DO_MODO_REMOTO[modo]} para permitir este modo
                    </p>
                  )}
                </div>
              );
            })}
          </div>
          <p className="text-[10px] leading-tight text-fg-muted">
            Modos que o operador pode comandar.
            {ehPid && " Os modos remotos exigem aresta chegando na porta correspondente."}
          </p>
        </fieldset>

        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-1">
            <Label htmlFor="normal">Modo normal</Label>
            <Select id="normal" name="normal" data-testid="config-normal" defaultValue={dados.normal}>
              {MODOS_NORMAIS[tipo].map((opcao) => (
                <option key={opcao.valor} value={opcao.valor}>
                  {opcao.rotulo}
                </option>
              ))}
            </Select>
            <p className="text-[10px] leading-tight text-fg-muted">
              Modo normal da malha: destino do rebaixamento “ir para o modo normal” e do modo pedido que não é permitido.
            </p>
          </div>
          {ehPid && (
            <div className="space-y-1">
              <Label htmlFor="shed_opt">Ao perder o modo remoto</Label>
              <Select id="shed_opt" name="shed_opt" data-testid="config-shed-opt" defaultValue={dados.shed_opt}>
                {SHED_OPTS.map((opcao) => (
                  <option key={opcao} value={opcao}>
                    {ROTULO_SHED[opcao]}
                  </option>
                ))}
              </Select>
              <p className="text-[10px] leading-tight text-fg-muted">
                Rebaixamento quando CAS, RCAS ou ROUT deixam de ter qualidade boa.
              </p>
            </div>
          )}
        </div>
        {ehPid && (
          <CampoBooleano
            id="shed_no_return"
            rotulo="Não retornar ao modo remoto sozinho"
            valor={dados.shed_no_return}
            ajuda="Depois do rebaixamento, voltar ao modo remoto passa a ser um comando explícito do operador."
          />
        )}
      </fieldset>

      {ehPid && (
        <>
          <details data-testid="config-secao-tracking">
            <summary className={`${ESTILO_LEGENDA} cursor-pointer`}>Tracking e override</summary>
            <div className="mt-2 space-y-3">
              <div className="grid grid-cols-2 gap-3">
                <CampoBooleano
                  id="track_enable"
                  rotulo="Habilitar tracking (trk_in_d)"
                  valor={dados.track_enable}
                  ajuda="Com a entrada trk_in_d ativa, a saída segue o valor de tracking."
                />
                <CampoBooleano
                  id="track_in_manual"
                  rotulo="Tracking também em manual"
                  valor={dados.track_in_manual}
                  ajuda="Mantém o tracking ativo mesmo com o bloco em MAN."
                />
                <CampoBooleano
                  id="use_pv_for_bkcal"
                  rotulo="BKCAL_OUT usa a PV"
                  valor={dados.use_pv_for_bkcal}
                  ajuda="A back-calculation envia a PV, e não o SP de trabalho, ao primário da cascata."
                />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <Campo
                  id="trk_val"
                  rotulo="Valor de tracking (%)"
                  valor={dados.trk_val}
                  ajuda="Saída imposta enquanto o tracking está ativo."
                />
                <Campo
                  id="lo_val"
                  rotulo="Valor de override local (lo_in_d) · %"
                  valor={dados.lo_val}
                  ajuda="Saída forçada enquanto o intertravamento lo_in_d está ativo."
                />
              </div>
            </div>
          </details>

          <details data-testid="config-secao-feedforward">
            <summary className={`${ESTILO_LEGENDA} cursor-pointer`}>Feedforward</summary>
            <div className="mt-2 space-y-3">
              <CampoBooleano
                id="ff_enable"
                rotulo="Habilitar feedforward (bias_in)"
                valor={dados.ff_enable}
                ajuda="O sinal de bias_in, convertido para %, vezes o ganho, entra como viés na saída."
              />
              <div className="grid grid-cols-3 gap-3">
                <Campo
                  id="ff_gain"
                  rotulo="Ganho"
                  valor={dados.ff_gain}
                  ajuda="Multiplica o sinal de feedforward."
                />
                <Campo
                  id="ff_scale_lo"
                  rotulo="Escala do sinal mínima (EU)"
                  valor={dados.ff_scale_lo}
                  ajuda="Valor em EU de bias_in que corresponde a 0 %."
                />
                <Campo
                  id="ff_scale_hi"
                  rotulo="Escala do sinal máxima (EU)"
                  valor={dados.ff_scale_hi}
                  ajuda="Valor em EU de bias_in que corresponde a 100 %."
                />
              </div>
            </div>
          </details>
        </>
      )}
    </div>
  );
}
