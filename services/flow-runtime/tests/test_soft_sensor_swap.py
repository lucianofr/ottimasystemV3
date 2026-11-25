"""SoftSensorBlock: troca de modelo sem interrupção (RF-584, spec §5.6).

Regra de contagem do prazo: o candidato tem idade 0 na varredura em que é instalado (início
do `step` seguinte ao `set_candidate`) e é rejeitado na varredura em que a idade atinge
`ceil(max(2*K*period_s, 60) / Ts)`, antes de ser avaliado nela.
"""

import asyncio

import pytest

from ottima_core.bus import KIND_SOFT_SENSOR_MODEL_ACTIVATED, KIND_SOFT_SENSOR_MODEL_REJECTED
from ottima_core.signal import Quality
from ottima_core.softsensor import load_model, synthetic
from ottima_flow_runtime.blocks.base import Signal
from ottima_flow_runtime.blocks.soft_sensor import BindingUpdate, SoftSensorBlock


def carregar(par, model_id=1):
    meta, blob = par
    return load_model(model_id, meta.model_dump(), blob)


def bloco(model=None, *, ts=1.0, n_inputs=2, prewarm=None, missing_reason=None, persist=None):
    eventos, gravacoes = [], []

    async def emit(**kw):
        eventos.append(kw)

    async def grava(u):
        gravacoes.append(u)

    b = SoftSensorBlock(
        "ss",
        n_inputs=n_inputs,
        ts_seconds=ts,
        model=model,
        prewarm=prewarm,
        missing_reason=missing_reason,
        emit_event=emit,
        persist=persist or grava,
    )
    return b, eventos, gravacoes


def entradas(*vals, q=Quality.GOOD):
    return {f"IN{i + 1}": Signal(v, quality=q) for i, v in enumerate(vals)}


def kinds(eventos, kind):
    return [e for e in eventos if e["kind"] == kind]


async def test_candidato_do_mesmo_periodo_e_promovido_no_passo_seguinte():
    b, eventos, gravacoes = bloco(carregar(synthetic.pls([1.0, 1.0], 0.0), model_id=1))
    await b.step(entradas(1.0, 2.0))
    b.set_candidate(carregar(synthetic.pls([2.0, 2.0], 0.0), model_id=2), b.active_buffer_copy())
    assert b.candidate_model_id is None  # só enfileirou
    out = (await b.step(entradas(1.0, 2.0)))["out"]
    assert b.active_model_id == 2 and b.candidate_model_id is None
    assert gravacoes[-1] == BindingUpdate(2, None)
    assert (out.v, out.quality) == (pytest.approx(6.0), Quality.GOOD)
    [ativado] = kinds(eventos, KIND_SOFT_SENSOR_MODEL_ACTIVATED)
    assert ativado["severity"] == "info"
    assert ativado["payload"] == {"block_id": "ss", "model_id": 2, "previous_model_id": 1}


async def test_saida_nunca_piora_na_troca():
    b, _, gravacoes = bloco(carregar(synthetic.pls([1.0, 1.0], 0.0), model_id=1))
    qualidades = [(await b.step(entradas(0.1, 0.2)))["out"].quality for _ in range(3)]
    # janela 5 com 3 amostras herdadas: um passo em dobro (4 amostras), promove no seguinte
    b.set_candidate(
        carregar(synthetic.lstm(2, sequence_length=5), model_id=2), b.active_buffer_copy()
    )
    qualidades.append((await b.step(entradas(0.1, 0.2)))["out"].quality)
    assert b.candidate_model_id == 2
    qualidades.append((await b.step(entradas(0.1, 0.2)))["out"].quality)
    assert b.active_model_id == 2
    qualidades += [(await b.step(entradas(0.1, 0.2)))["out"].quality for _ in range(3)]
    assert b.active_model_id == 2 and gravacoes == [BindingUpdate(2, None)]
    assert qualidades == [Quality.GOOD] * len(qualidades)


async def test_candidato_sem_valor_nao_e_promovido_mesmo_com_o_ativo_bad():
    b, _, gravacoes = bloco(carregar(synthetic.pls([1.0, 1.0], 0.0), model_id=1))
    await b.step(entradas(1.0, 2.0))
    b.set_candidate(carregar(synthetic.lstm(2, sequence_length=5), model_id=2), None)
    ruim = {"IN1": Signal(None, quality=Quality.BAD), "IN2": Signal(2.0, quality=Quality.GOOD)}
    for _ in range(3):
        out = (await b.step(ruim))["out"]
        assert (out.v, out.quality) == (pytest.approx(3.0), Quality.BAD)
    assert b.active_model_id == 1 and b.candidate_model_id == 2
    assert gravacoes == []


async def test_candidato_extrapolando_espera_e_e_rejeitado_no_prazo():
    b, eventos, gravacoes = bloco(carregar(synthetic.pls([1.0], 0.0), model_id=1), n_inputs=1)
    estreito = carregar(synthetic.pls([1.0], 0.0, ranges=[(0.0, 1.0)]), model_id=2)
    b.set_candidate(estreito, b.active_buffer_copy())
    for _ in range(60):  # varreduras 0..59: prazo = max(2*1*1, 60) = 60 varreduras
        out = (await b.step(entradas(5.0)))["out"]
        assert out.quality is Quality.GOOD
        assert b.candidate_model_id == 2
    assert gravacoes == []
    await b.step(entradas(5.0))  # varredura 60
    assert b.active_model_id == 1 and b.candidate_model_id is None
    assert gravacoes == [BindingUpdate(1, None, reset_desired_to_active=True)]
    [rejeitado] = kinds(eventos, KIND_SOFT_SENSOR_MODEL_REJECTED)
    assert rejeitado["severity"] == "warning"
    assert rejeitado["payload"] == {"block_id": "ss", "model_id": 2, "reason": "extrapolating"}


async def test_prazo_cresce_com_janela_e_periodo():
    # K=3, period_s=20, Ts=1: max(2*3*20, 60) = 120 s = 120 varreduras
    b, _, gravacoes = bloco(carregar(synthetic.pls([1.0, 1.0], 0.0), model_id=1))
    b.set_candidate(carregar(synthetic.lstm(2, sequence_length=3, period_s=20.0), model_id=2), None)
    ruim = {"IN1": Signal(None, quality=Quality.BAD), "IN2": Signal(2.0, quality=Quality.GOOD)}
    for _ in range(120):
        await b.step(ruim)
    assert b.candidate_model_id == 2 and gravacoes == []
    await b.step(ruim)
    assert b.candidate_model_id is None
    assert gravacoes == [BindingUpdate(1, None, reset_desired_to_active=True)]


async def test_candidato_de_outro_periodo_nao_herda_o_buffer():
    b, _, gravacoes = bloco(carregar(synthetic.pls([1.0, 1.0], 0.0), model_id=1))
    for _ in range(3):  # varreduras 0..2: buffer do ativo com 3 amostras
        await b.step(entradas(0.1, 0.2))
    b.set_candidate(carregar(synthetic.lstm(2, sequence_length=2, period_s=5.0), model_id=2), None)
    # Empurra só nas varreduras 5 e 10: a janela de 2 fecha na 10, nunca antes.
    for i in range(3, 10):
        await b.step(entradas(0.1, 0.2))
        assert b.active_model_id == 1, f"promovido cedo na varredura {i}"
    await b.step(entradas(0.1, 0.2))  # varredura 10
    assert b.active_model_id == 2
    assert gravacoes == [BindingUpdate(2, None)]


async def test_sem_modelo_em_uso_o_candidato_assume_na_hora():
    b, eventos, gravacoes = bloco()
    b.set_candidate(carregar(synthetic.lstm(2, sequence_length=3), model_id=5), None)
    out = (await b.step(entradas(0.1, 0.2)))["out"]
    assert b.active_model_id == 5 and b.candidate_model_id is None
    assert (out.v, out.quality) == (None, Quality.BAD)  # janela incompleta
    assert gravacoes == [BindingUpdate(5, None)]
    [ativado] = kinds(eventos, KIND_SOFT_SENSOR_MODEL_ACTIVATED)
    assert ativado["payload"] == {"block_id": "ss", "model_id": 5, "previous_model_id": None}
    assert len(eventos) == 1  # sem model_missing: o modelo chegou antes da 1a varredura
    for _ in range(2):
        out = (await b.step(entradas(0.1, 0.2)))["out"]
    assert out.v is not None and out.quality is Quality.GOOD


async def test_segundo_candidato_substitui_o_primeiro_e_reinicia_o_prazo():
    b, eventos, gravacoes = bloco(carregar(synthetic.pls([1.0], 0.0), model_id=1), n_inputs=1)
    b.set_candidate(carregar(synthetic.pls([1.0], 0.0, ranges=[(0.0, 1.0)]), model_id=2), None)
    for _ in range(30):  # varreduras 0..29
        await b.step(entradas(5.0))
    b.set_candidate(carregar(synthetic.pls([1.0], 0.0, ranges=[(0.0, 1.0)]), model_id=3), None)
    for _ in range(60):  # varreduras 30..89: o prazo do 3 começa do zero na 30
        await b.step(entradas(5.0))
        assert b.candidate_model_id == 3
    assert gravacoes == []
    await b.step(entradas(5.0))  # varredura 90
    assert b.candidate_model_id is None
    assert gravacoes == [BindingUpdate(1, None, reset_desired_to_active=True)]
    assert [e["payload"]["model_id"] for e in kinds(eventos, KIND_SOFT_SENSOR_MODEL_REJECTED)] == [
        3
    ]


async def test_set_candidate_no_meio_de_um_step_so_vale_no_step_seguinte():
    gravacoes = []
    terceiro = carregar(synthetic.pls([3.0, 3.0], 0.0), model_id=3)

    async def persist(u):
        gravacoes.append(u)
        if u.active_model_id == 2:
            b.set_candidate(terceiro, None)

    b, *_ = bloco(carregar(synthetic.pls([1.0, 1.0], 0.0), model_id=1), persist=persist)
    await b.step(entradas(1.0, 2.0))
    b.set_candidate(carregar(synthetic.pls([2.0, 2.0], 0.0), model_id=2), b.active_buffer_copy())
    await b.step(entradas(1.0, 2.0))
    assert b.active_model_id == 2 and b.candidate_model_id is None
    out = (await b.step(entradas(1.0, 2.0)))["out"]
    assert b.active_model_id == 3  # PLS com janela de 1: aplicado e já promovido
    assert gravacoes == [BindingUpdate(2, None), BindingUpdate(3, None)]
    assert (out.v, out.quality) == (pytest.approx(9.0), Quality.GOOD)


async def test_propriedades_do_slot_em_uso():
    b, *_ = bloco()
    assert (b.active_model_id, b.active_period_s, b.active_buffer_copy()) == (None, None, None)
    b, *_ = bloco(carregar(synthetic.pls([1.0, 1.0], 0.0, period_s=5.0)), ts=1.0)
    await b.step(entradas(1.0, 2.0))
    copia = b.active_buffer_copy()
    assert b.active_period_s == 5.0 and len(copia) == 1
    await b.step(entradas(1.0, 2.0))  # varredura 1: não é passo de modelo
    assert len(copia) == 1 and len(b.active_buffer_copy()) == 1


async def _ate(cond):
    for _ in range(200):
        if cond():
            return
        await asyncio.sleep(0)
    raise AssertionError("condição não satisfeita")


def _persist_que_trava(bloqueia):
    """Persist que segura a gravação de `bloqueia(u)` até `libera` ser setado."""
    gravacoes, entrou, libera = [], asyncio.Event(), asyncio.Event()

    async def persist(u):
        if bloqueia(u):
            entrou.set()
            await libera.wait()
        gravacoes.append(u)

    return persist, gravacoes, entrou, libera


async def test_rejeicao_sobrevive_ao_cancelamento_da_varredura():
    # stop/fail cancela a varredura no meio do persist: sem a gravação, o próximo deploy
    # carregaria `desired_model_id` = modelo rejeitado sem nunca tê-lo validado (§5.6-5).
    persist, gravacoes, entrou, libera = _persist_que_trava(lambda u: u.reset_desired_to_active)
    b, eventos, _ = bloco(
        carregar(synthetic.pls([1.0], 0.0), model_id=1), n_inputs=1, persist=persist
    )
    b.set_candidate(carregar(synthetic.pls([1.0], 0.0, ranges=[(0.0, 1.0)]), model_id=2), None)
    for _ in range(60):
        await b.step(entradas(5.0))
    varredura = asyncio.create_task(b.step(entradas(5.0)))  # varredura 60: rejeita
    await entrou.wait()
    varredura.cancel()
    with pytest.raises(asyncio.CancelledError):
        await varredura
    assert b.candidate_model_id is None and b.active_model_id == 1
    libera.set()
    await _ate(lambda: kinds(eventos, KIND_SOFT_SENSOR_MODEL_REJECTED))
    assert gravacoes == [BindingUpdate(1, None, reset_desired_to_active=True)]


async def test_promocao_sobrevive_ao_cancelamento_da_varredura():
    persist, gravacoes, entrou, libera = _persist_que_trava(lambda u: u.active_model_id == 2)
    b, eventos, _ = bloco(carregar(synthetic.pls([1.0, 1.0], 0.0), model_id=1), persist=persist)
    await b.step(entradas(1.0, 2.0))
    b.set_candidate(carregar(synthetic.pls([2.0, 2.0], 0.0), model_id=2), b.active_buffer_copy())
    varredura = asyncio.create_task(b.step(entradas(1.0, 2.0)))
    await entrou.wait()
    varredura.cancel()
    with pytest.raises(asyncio.CancelledError):
        await varredura
    assert b.active_model_id == 2 and b.candidate_model_id is None
    libera.set()
    await _ate(lambda: kinds(eventos, KIND_SOFT_SENSOR_MODEL_ACTIVATED))
    assert gravacoes == [BindingUpdate(2, None)]


def test_periodo_menor_que_o_ts_e_recusado_na_construcao_do_slot():
    curto = carregar(synthetic.pls([1.0, 1.0], 0.0, period_s=0.4))
    with pytest.raises(ValueError, match="período"):
        bloco(curto, ts=1.0)
    b, *_ = bloco(carregar(synthetic.pls([1.0, 1.0], 0.0)), ts=1.0)
    with pytest.raises(ValueError, match="período"):
        b.set_candidate(curto, None)  # recusado no pedido, nunca dentro da varredura
