"""SoftSensorBlock: passo de modelo, qualidade da saída e eventos de borda (RF-582/583, §5.2-4)."""

import asyncio

import pytest

from ottima_core.bus import (
    KIND_SOFT_SENSOR_EXTRAPOLATING,
    KIND_SOFT_SENSOR_MODEL_ACTIVATED,
    KIND_SOFT_SENSOR_MODEL_MISSING,
)
from ottima_core.signal import Quality
from ottima_core.softsensor import SampleBuffer, load_model, synthetic
from ottima_flow_runtime.blocks.base import Signal
from ottima_flow_runtime.blocks.soft_sensor import SoftSensorBlock


def carregar(par, model_id=1):
    meta, blob = par
    return load_model(model_id, meta.model_dump(), blob)


def bloco(model=None, *, ts=1.0, n_inputs=2, prewarm=None, missing_reason=None):
    eventos, gravacoes = [], []

    async def emit(**kw):
        eventos.append(kw)

    async def persist(u):
        gravacoes.append(u)

    b = SoftSensorBlock(
        "ss",
        n_inputs=n_inputs,
        ts_seconds=ts,
        model=model,
        prewarm=prewarm,
        missing_reason=missing_reason,
        emit_event=emit,
        persist=persist,
    )
    return b, eventos, gravacoes


def entradas(*vals, q=Quality.GOOD):
    return {f"IN{i + 1}": Signal(v, quality=q) for i, v in enumerate(vals)}


async def test_sem_modelo_sai_none_bad_e_avisa_uma_vez():
    b, eventos, _ = bloco()
    for _ in range(3):
        out = (await b.step(entradas(1.0, 2.0)))["out"]
        assert (out.v, out.quality) == (None, Quality.BAD)
    assert [e["kind"] for e in eventos] == [KIND_SOFT_SENSOR_MODEL_MISSING]
    assert eventos[0]["payload"] == {"block_id": "ss", "reason": "no_model"}
    assert eventos[0]["severity"] == "warning"


async def test_sem_modelo_reporta_o_motivo_recebido():
    b, eventos, _ = bloco(missing_reason="corrupt")
    await b.step(entradas(1.0, 2.0))
    assert eventos[0]["payload"]["reason"] == "corrupt"


async def test_pls_sai_good_no_primeiro_passo():
    b, *_ = bloco(carregar(synthetic.pls([2.0, -1.0], 0.5)))
    out = (await b.step(entradas(3.0, 4.0)))["out"]
    assert (out.v, out.quality) == (pytest.approx(2.5), Quality.GOOD)


async def test_passo_de_modelo_a_cada_n_varreduras():
    b, *_ = bloco(carregar(synthetic.pls([1.0], 0.0, period_s=5.0)), n_inputs=1)
    saidas = [(await b.step(entradas(float(i))))["out"].v for i in range(11)]
    assert saidas == [0.0] * 5 + [5.0] * 5 + [10.0]


async def test_entre_passos_porta_bad_rebaixa_a_saida_mantida():
    b, *_ = bloco(carregar(synthetic.pls([1.0, 1.0], 0.0, period_s=5.0)))
    assert (await b.step(entradas(1.0, 2.0)))["out"].v == pytest.approx(3.0)
    out = (
        await b.step(
            {"IN1": Signal(9.0, quality=Quality.BAD), "IN2": Signal(9.0, quality=Quality.GOOD)}
        )
    )["out"]
    assert (out.v, out.quality) == (pytest.approx(3.0), Quality.BAD)
    out = (await b.step(entradas(9.0, 9.0, q=Quality.UNCERTAIN)))["out"]
    assert (out.v, out.quality) == (pytest.approx(3.0), Quality.UNCERTAIN)
    out = (await b.step(entradas(9.0, 9.0)))["out"]
    assert (out.v, out.quality) == (pytest.approx(3.0), Quality.GOOD)


async def test_lstm_sem_prewarm_sai_none_ate_a_janela_encher():
    b, *_ = bloco(carregar(synthetic.lstm(2, sequence_length=3)))
    outs = [(await b.step(entradas(0.1, 0.2)))["out"] for _ in range(3)]
    assert [(o.v, o.quality) for o in outs[:2]] == [(None, Quality.BAD)] * 2
    assert outs[2].v is not None and outs[2].quality is Quality.GOOD


def _prewarm(rows, n_inputs=2, q=Quality.GOOD):
    buf = SampleBuffer(n_inputs)
    buf.preload([[0.1] * n_inputs] * rows, [q] * rows)
    return buf


async def test_lstm_com_prewarm_sai_good_no_primeiro_passo():
    b, *_ = bloco(carregar(synthetic.lstm(2, sequence_length=3)), prewarm=_prewarm(3))
    out = (await b.step(entradas(0.1, 0.2)))["out"]
    assert out.v is not None and out.quality is Quality.GOOD


async def test_bad_no_meio_mantem_o_ultimo_valor_com_qualidade_bad():
    b, *_ = bloco(carregar(synthetic.lstm(2, sequence_length=3)), prewarm=_prewarm(3))
    anterior = (await b.step(entradas(0.1, 0.2)))["out"].v
    assert anterior is not None
    contaminada = [
        (
            await b.step(
                {"IN1": Signal(None, quality=Quality.BAD), "IN2": Signal(0.2, quality=Quality.GOOD)}
            )
        )["out"]
    ]
    contaminada += [(await b.step(entradas(0.3, 0.4)))["out"] for _ in range(2)]
    assert [(o.v, o.quality) for o in contaminada] == [(anterior, Quality.BAD)] * 3
    limpa = (await b.step(entradas(0.3, 0.4)))["out"]
    assert limpa.quality is Quality.GOOD and limpa.v != anterior


async def test_porta_ausente_conta_como_bad():
    b, *_ = bloco(carregar(synthetic.pls([1.0, 1.0], 0.0)))
    out = (await b.step({"IN1": Signal(1.0, quality=Quality.GOOD)}))["out"]
    assert (out.v, out.quality) == (None, Quality.BAD)
    await b.step(entradas(1.0, 2.0))
    out = (await b.step({"IN2": Signal(1.0, quality=Quality.GOOD)}))["out"]
    assert (out.v, out.quality) == (pytest.approx(3.0), Quality.BAD)


async def test_extrapolacao_emite_evento_so_na_borda():
    b, eventos, _ = bloco(
        carregar(synthetic.pls([1.0], 0.0, ranges=[(0.0, 10.0)]), model_id=7), n_inputs=1
    )
    qualidades = [(await b.step(entradas(v)))["out"].quality for v in (5.0, 20.0, 20.0, 5.0)]
    assert qualidades == [Quality.GOOD, Quality.UNCERTAIN, Quality.UNCERTAIN, Quality.GOOD]
    extrap = [e for e in eventos if e["kind"] == KIND_SOFT_SENSOR_EXTRAPOLATING]
    assert [e["payload"] for e in extrap] == [
        {"block_id": "ss", "model_id": 7, "active": True},
        {"block_id": "ss", "model_id": 7, "active": False},
    ]


async def test_persist_que_levanta_nao_derruba_o_step():
    # emit_event também levanta: os dois pontos de saída são capturados e logados.
    async def falha(*_a, **_kw):
        raise RuntimeError("banco fora")

    b = SoftSensorBlock(
        "ss",
        n_inputs=2,
        ts_seconds=1.0,
        model=None,
        prewarm=None,
        missing_reason=None,
        emit_event=falha,
        persist=falha,
    )
    await b.step(entradas(1.0, 2.0))  # model_missing com emit quebrado
    b.set_candidate(carregar(synthetic.pls([1.0, 1.0], 0.0), model_id=4), None)
    out = (await b.step(entradas(1.0, 2.0)))["out"]  # promoção com persist e emit quebrados
    assert b.active_model_id == 4
    assert (out.v, out.quality) == (pytest.approx(3.0), Quality.GOOD)


async def test_reset_mantem_modelo_e_buffer():
    b, *_ = bloco(carregar(synthetic.lstm(2, sequence_length=3)))
    for _ in range(3):
        await b.step(entradas(0.1, 0.2))
    b.reset()
    out = (await b.step(entradas(0.1, 0.2)))["out"]  # janela já cheia: buffer sobreviveu
    assert out.v is not None and out.quality is Quality.GOOD
    assert b.active_model_id == 1


async def test_reset_zera_o_ultimo_valor():
    b, *_ = bloco(carregar(synthetic.lstm(2, sequence_length=3)), prewarm=_prewarm(3))
    await b.step(entradas(0.1, 0.2))
    await b.step(
        {"IN1": Signal(None, quality=Quality.BAD), "IN2": Signal(0.2, quality=Quality.GOOD)}
    )
    b.reset()
    out = (await b.step(entradas(0.1, 0.2)))["out"]  # BAD ainda na janela, valor zerado
    assert (out.v, out.quality) == (None, Quality.BAD)


async def test_reset_reinicia_o_contador_de_varredura():
    b, *_ = bloco(carregar(synthetic.pls([1.0], 0.0, period_s=5.0)), n_inputs=1)
    await b.step(entradas(1.0))
    await b.step(entradas(2.0))
    b.reset()
    assert (await b.step(entradas(3.0)))["out"].v == pytest.approx(3.0)


async def test_eventos_levam_os_campos_de_publish_event():
    # publish_event exige severity/origin/message/kind: faltar um derruba o evento em silêncio.
    b, eventos, _ = bloco(n_inputs=1)
    await b.step(entradas(5.0))
    b.set_candidate(carregar(synthetic.pls([1.0], 0.0, ranges=[(0.0, 10.0)]), model_id=3), None)
    await b.step(entradas(20.0))
    assert [e["kind"] for e in eventos] == [
        KIND_SOFT_SENSOR_MODEL_MISSING,
        KIND_SOFT_SENSOR_MODEL_ACTIVATED,
        KIND_SOFT_SENSOR_EXTRAPOLATING,
    ]
    for e in eventos:
        assert set(e) == {"severity", "origin", "message", "kind", "payload"}
        assert e["origin"] == "flow-runtime"
        assert e["payload"]["block_id"] == "ss"
        assert e["message"]


def test_portas():
    b, *_ = bloco(n_inputs=3)
    assert b.input_ports == ("IN1", "IN2", "IN3")
    assert b.output_ports == ("out",)


@pytest.mark.parametrize(
    ("par", "janela", "chamadas"),
    [
        (synthetic.pls([1.0, 1.0], 0.0), 1, 0),
        (synthetic.esn(2, warmup=5), 5, 6),
        (synthetic.lstm(2, sequence_length=3), 3, 6),
    ],
    ids=["pls_inline", "esn_executor", "lstm_executor"],
)
async def test_pls_inline_esn_e_lstm_no_executor(monkeypatch, par, janela, chamadas):
    # ADR-004: ESN/LSTM nunca rodam no event loop; PLS é barato e roda inline.
    loop = asyncio.get_running_loop()
    original = loop.run_in_executor
    contagem = 0

    def espiao(executor, fn, *args):
        nonlocal contagem
        contagem += 1
        return original(executor, fn, *args)

    monkeypatch.setattr(loop, "run_in_executor", espiao)
    b, *_ = bloco(carregar(par))
    outs = [(await b.step(entradas(0.1, 0.2)))["out"] for _ in range(6)]
    assert contagem == chamadas
    assert outs[janela - 1].v is not None and outs[janela - 1].quality is Quality.GOOD
    assert all(o.v is None for o in outs[: janela - 1])
