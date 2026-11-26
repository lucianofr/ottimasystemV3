"""Testes do buffer de amostras e da regra de qualidade da saída (RF-583, ADR-046 D5, spec §5.4).

`evaluate` decide se a saída de um sensor virtual pode alimentar uma malha: a tabela de
qualidade é testada linha a linha, na ordem em que a regra a aplica.
"""

import numpy as np
import pytest

from ottima_core.signal import Quality
from ottima_core.softsensor import (
    BUFFER_STEPS,
    Evaluation,
    SampleBuffer,
    evaluate,
    load_model,
    synthetic,
)


def _dump(par):
    return par[0].model_dump(mode="json"), par[1]


def PLS(**kw):
    return load_model(1, *_dump(synthetic.pls([1.0, 1.0], 0.0, **kw)))


def LSTM3():
    return load_model(2, *_dump(synthetic.lstm(2, sequence_length=3)))


def test_janela_incompleta_e_bad_sem_valor():
    buf = SampleBuffer(2)
    buf.push([1.0, 1.0], Quality.GOOD)
    assert evaluate(LSTM3(), buf) == Evaluation(None, Quality.BAD, "incomplete")


def test_buffer_vazio_e_incompleto():
    assert evaluate(PLS(), SampleBuffer(2)) == Evaluation(None, Quality.BAD, "incomplete")


def test_amostra_bad_na_janela_contamina_ate_sair():
    buf = SampleBuffer(2)
    buf.push([1.0, 1.0], Quality.BAD)
    for _ in range(2):
        buf.push([1.0, 1.0], Quality.GOOD)
    assert evaluate(LSTM3(), buf) == Evaluation(None, Quality.BAD, "bad_sample")
    buf.push([1.0, 1.0], Quality.GOOD)  # a BAD saiu da janela de 3
    assert evaluate(LSTM3(), buf).quality is Quality.GOOD


def test_incompleta_vence_bad_sample():
    buf = SampleBuffer(2)
    buf.push([1.0, 1.0], Quality.BAD)
    assert evaluate(LSTM3(), buf).reason == "incomplete"


def test_porta_sem_valor_vira_bad():
    buf = SampleBuffer(2)
    buf.push([None, 1.0], Quality.GOOD)
    assert evaluate(PLS(), buf) == Evaluation(None, Quality.BAD, "bad_sample")


def test_porta_nao_finita_vira_bad_e_grava_nan():
    buf = SampleBuffer(2)
    buf.push([float("inf"), 1.0], Quality.GOOD)
    buf.push([float("nan"), 2.0], Quality.UNCERTAIN)
    values, qualities = buf.last(2)
    assert qualities == (Quality.BAD, Quality.BAD)
    assert np.isnan(values[:, 0]).all() and values[:, 1].tolist() == [1.0, 2.0]


def test_bad_na_janela_vence_extrapolacao_e_incerteza():
    buf = SampleBuffer(2)
    buf.push([1e9, 1.0], Quality.BAD)  # fora da faixa, mas BAD: nem calcula
    assert evaluate(PLS(), buf) == Evaluation(None, Quality.BAD, "bad_sample")


def test_uncertain_na_janela_rebaixa_mas_calcula():
    buf = SampleBuffer(2)
    buf.push([1.0, 2.0], Quality.UNCERTAIN)
    ev = evaluate(PLS(), buf)
    assert (ev.value, ev.quality, ev.reason) == (pytest.approx(3.0), Quality.UNCERTAIN, "uncertain")


def test_uncertain_antigo_fora_da_janela_nao_rebaixa():
    buf = SampleBuffer(2)
    buf.push([1.0, 1.0], Quality.UNCERTAIN)
    for _ in range(3):
        buf.push([1.0, 1.0], Quality.GOOD)
    assert evaluate(LSTM3(), buf).reason == "ok"


def test_tudo_valido_e_good_com_valor():
    buf = SampleBuffer(2)
    buf.push([1.0, 2.0], Quality.GOOD)
    ev = evaluate(PLS(), buf)
    assert (ev.value, ev.quality, ev.reason) == (pytest.approx(3.0), Quality.GOOD, "ok")


def test_fora_da_faixa_alem_de_5_por_cento_e_extrapolacao():
    m = PLS(ranges=[(0.0, 10.0), (0.0, 10.0)])
    buf = SampleBuffer(2)
    buf.push([10.5, 5.0], Quality.GOOD)  # exatamente no limite
    assert evaluate(m, buf).quality is Quality.GOOD
    buf.push([10.51, 5.0], Quality.GOOD)
    ev = evaluate(m, buf)
    assert (ev.value, ev.quality, ev.reason) == (
        pytest.approx(15.51),
        Quality.UNCERTAIN,
        "extrapolating",
    )


def test_fora_da_faixa_pelo_lado_de_baixo_tambem_extrapola():
    m = PLS(ranges=[(0.0, 10.0), (0.0, 10.0)])
    buf = SampleBuffer(2)
    buf.push([5.0, -0.5], Quality.GOOD)  # exatamente no limite
    assert evaluate(m, buf).quality is Quality.GOOD
    buf.push([5.0, -0.51], Quality.GOOD)
    assert evaluate(m, buf).reason == "extrapolating"


def test_extrapolacao_olha_as_k_linhas_e_nao_so_a_ultima():
    buf = SampleBuffer(2)
    buf.push([1e7, 1.0], Quality.GOOD)  # faixa sintética é ±1e6
    buf.push([1.0, 1.0], Quality.GOOD)
    buf.push([1.0, 1.0], Quality.GOOD)
    assert evaluate(LSTM3(), buf).reason == "extrapolating"
    buf.push([1.0, 1.0], Quality.GOOD)  # a linha fora da faixa saiu da janela de 3
    assert evaluate(LSTM3(), buf).reason == "ok"


def test_extrapolacao_vence_uncertain_no_motivo():
    m = PLS(ranges=[(0.0, 10.0), (0.0, 10.0)])
    buf = SampleBuffer(2)
    buf.push([50.0, 5.0], Quality.UNCERTAIN)
    assert evaluate(m, buf).reason == "extrapolating"


def test_faixa_de_span_zero_aceita_o_proprio_valor():
    m = PLS(ranges=[(7.0, 7.0), (0.0, 10.0)])
    buf = SampleBuffer(2)
    buf.push([7.0, 5.0], Quality.GOOD)
    assert evaluate(m, buf).quality is Quality.GOOD
    buf.push([7.001, 5.0], Quality.GOOD)
    assert evaluate(m, buf).reason == "extrapolating"


def test_resultado_nao_finito_e_bad_sem_valor():
    m = PLS()
    buf = SampleBuffer(2)
    buf.push([1e308, 1e308], Quality.GOOD)  # w=[1,1]: a soma estoura e predict devolve inf
    assert evaluate(m, buf) == Evaluation(None, Quality.BAD, "non_finite")


def test_buffer_com_n_inputs_diferente_do_modelo_e_erro_de_programacao():
    buf = SampleBuffer(3)
    buf.push([1.0, 1.0, 1.0], Quality.GOOD)
    with pytest.raises(ValueError):
        evaluate(PLS(), buf)


def test_buffer_e_circular_em_256():
    assert BUFFER_STEPS == 256
    buf = SampleBuffer(1)
    for i in range(300):
        buf.push([float(i)], Quality.GOOD)
    assert len(buf) == 256 and buf.last(1)[0][0, 0] == 299.0
    assert buf.last(256)[0][0, 0] == 44.0  # a mais antiga que sobrou


def test_last_devolve_as_mais_recentes_da_mais_antiga_para_a_mais_nova():
    buf = SampleBuffer(2)
    for i in range(4):
        buf.push([float(i), 10.0 + i], Quality.GOOD if i % 2 else Quality.UNCERTAIN)
    values, qualities = buf.last(3)
    assert values.tolist() == [[1.0, 11.0], [2.0, 12.0], [3.0, 13.0]]
    assert qualities == (Quality.GOOD, Quality.UNCERTAIN, Quality.GOOD)


def test_last_com_menos_amostras_que_k_e_none():
    buf = SampleBuffer(2)
    buf.push([1.0, 1.0], Quality.GOOD)
    assert buf.last(2) is None
    assert buf.last(1) is not None


def test_last_com_k_menor_que_1_e_erro():
    buf = SampleBuffer(1)
    buf.push([1.0], Quality.GOOD)
    with pytest.raises(ValueError):
        buf.last(0)


def test_last_devolve_copia_e_nao_expoe_o_buffer():
    buf = SampleBuffer(1)
    buf.push([1.0], Quality.GOOD)
    values, _ = buf.last(1)
    values[0, 0] = 99.0
    assert buf.last(1)[0][0, 0] == 1.0


def test_push_com_numero_de_portas_errado_e_erro():
    buf = SampleBuffer(2)
    with pytest.raises(ValueError):
        buf.push([1.0], Quality.GOOD)


def test_preload_substitui_o_conteudo_mais_antiga_primeiro():
    buf = SampleBuffer(2)
    buf.push([9.0, 9.0], Quality.GOOD)
    buf.preload(
        np.array([[1.0, 2.0], [3.0, 4.0], [5.0, 6.0]]),
        [Quality.BAD, Quality.UNCERTAIN, Quality.GOOD],
    )
    assert len(buf) == 3
    values, qualities = buf.last(3)
    assert values.tolist() == [[1.0, 2.0], [3.0, 4.0], [5.0, 6.0]]
    assert qualities == (Quality.BAD, Quality.UNCERTAIN, Quality.GOOD)


def test_preload_acima_da_capacidade_mantem_as_mais_novas():
    buf = SampleBuffer(1)
    buf.preload(np.arange(300.0).reshape(300, 1), [Quality.GOOD] * 300)
    assert len(buf) == 256 and buf.last(256)[0][0, 0] == 44.0 and buf.last(1)[0][0, 0] == 299.0


def test_preload_com_valor_nao_finito_vira_bad_como_no_push():
    buf = SampleBuffer(2)
    buf.preload(np.array([[1.0, np.nan], [np.inf, 2.0]]), [Quality.GOOD, Quality.GOOD])
    values, qualities = buf.last(2)
    assert qualities == (Quality.BAD, Quality.BAD)
    assert np.isnan(values[0, 1]) and np.isnan(values[1, 0])


def test_preload_copia_o_array_de_entrada():
    buf = SampleBuffer(1)
    src = np.array([[1.0]])
    buf.preload(src, [Quality.GOOD])
    src[0, 0] = 99.0
    assert buf.last(1)[0][0, 0] == 1.0


def test_preload_com_forma_ou_qualidades_incoerentes_e_erro():
    buf = SampleBuffer(2)
    with pytest.raises(ValueError):
        buf.preload(np.zeros((3, 1)), [Quality.GOOD] * 3)  # colunas != n_inputs
    with pytest.raises(ValueError):
        buf.preload(np.zeros((3, 2)), [Quality.GOOD] * 2)  # uma qualidade por linha


def test_copy_e_independente():
    buf = SampleBuffer(1)
    buf.push([1.0], Quality.GOOD)
    dup = buf.copy()
    dup.push([2.0], Quality.UNCERTAIN)
    buf.push([3.0], Quality.BAD)
    assert buf.last(2)[0].ravel().tolist() == [1.0, 3.0]
    assert dup.last(2)[0].ravel().tolist() == [1.0, 2.0]
    assert dup.last(2)[1] == (Quality.GOOD, Quality.UNCERTAIN)


def test_copy_preserva_a_capacidade():
    buf = SampleBuffer(1, capacity=4)
    dup = buf.copy()
    for i in range(10):
        dup.push([float(i)], Quality.GOOD)
    assert len(dup) == 4 and len(buf) == 0
