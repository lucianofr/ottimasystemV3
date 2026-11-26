"""Testes do artefato do sensor virtual (RF-581, ADR-046 D3): `.npz` em float32 lido sem pickle,
`ModelMeta` e `load_model` (chaves e formas por método contra `n_inputs`)."""

import io
import struct
import tracemalloc
import zlib

import numpy as np
import pytest

from ottima_core.softsensor import (
    MAX_ARTIFACT_BYTES,
    MAX_ARTIFACT_UNPACKED_BYTES,
    ArtifactError,
    LoadedModel,
    ModelMeta,
    load_model,
    model_steps,
    pack_weights,
    synthetic,
    unpack_weights,
)


def _carregar(par: tuple[ModelMeta, bytes]) -> LoadedModel:
    return load_model(1, par[0].model_dump(mode="json"), par[1])


def _carregar_bytes(meta: ModelMeta, blob: bytes) -> LoadedModel:
    return load_model(1, meta.model_dump(mode="json"), blob)


def test_pack_unpack_preserva_valores_em_float32():
    blob = pack_weights({"w": np.array([1.5, -2.0]), "b": np.array([0.25])})
    out = unpack_weights(blob)
    assert out["w"].dtype == np.float32
    np.testing.assert_allclose(out["w"], [1.5, -2.0])


def test_unpack_recusa_bytes_truncados():
    blob = pack_weights({"w": np.zeros(4), "b": np.zeros(1)})
    with pytest.raises(ArtifactError):
        unpack_weights(blob[: len(blob) // 2])


def test_unpack_recusa_bytes_que_nao_sao_npz():
    with pytest.raises(ArtifactError):
        unpack_weights(b"isto nao e um npz")


def test_unpack_nunca_aceita_pickle():
    buf = io.BytesIO()
    np.savez(buf, w=np.array([object()], dtype=object))
    with pytest.raises(ArtifactError):
        unpack_weights(buf.getvalue())


def test_unpack_recusa_array_nao_numerico():
    buf = io.BytesIO()
    np.savez(buf, w=np.array(["a", "b"]))
    with pytest.raises(ArtifactError):
        unpack_weights(buf.getvalue())


def test_pack_recusa_acima_do_teto():
    grande = np.random.default_rng(0).random(3_000_000)  # ~12 MB em float32, incompressível
    with pytest.raises(ArtifactError):
        pack_weights({"w": grande, "b": np.zeros(1)})


def test_unpack_recusa_blob_acima_do_teto_comprimido_antes_de_ler():
    buf = io.BytesIO()
    # npz VÁLIDO (sem compressão) de ~8,4 MB: só o teto de bytes pode recusá-lo.
    np.savez(buf, w=np.zeros(MAX_ARTIFACT_BYTES // 8 + 1000))
    assert len(buf.getvalue()) > MAX_ARTIFACT_BYTES
    with pytest.raises(ArtifactError, match="teto"):
        unpack_weights(buf.getvalue())


def test_unpack_recusa_tamanho_descomprimido_declarado_acima_do_teto():
    buf = io.BytesIO()
    # Zip bomb: zeros comprimem a poucas dezenas de KB, mas descomprimem a 32 MiB + 4 bytes.
    # Montado direto com savez_compressed, sem passar pelo pack_weights.
    np.savez_compressed(buf, w=np.zeros(MAX_ARTIFACT_UNPACKED_BYTES // 4 + 1, dtype=np.float32))
    assert len(buf.getvalue()) < MAX_ARTIFACT_BYTES
    with pytest.raises(ArtifactError, match="descomprimido"):
        unpack_weights(buf.getvalue())


def _zip_forjado(real_bytes: int, declared: int, nome: bytes = b"w.npy") -> bytes:
    """Zip de uma entrada deflate de zeros cujo `file_size` declarado mente (`declared`)."""
    co = zlib.compressobj(9, zlib.DEFLATED, -15)
    zeros = bytes(1024 * 1024)
    dados = b"".join(co.compress(zeros) for _ in range(real_bytes // len(zeros))) + co.flush()
    local = struct.pack(
        "<IHHHHHIIIHH", 0x04034B50, 20, 0, 8, 0, 0x21, 0, len(dados), declared, len(nome), 0
    )
    cd = struct.pack(
        "<IHHHHHHIIIHHHHHII",
        0x02014B50, 20, 20, 0, 8, 0, 0x21, 0, len(dados), declared, len(nome), 0, 0, 0, 0, 0, 0,
    )  # fmt: skip
    local += nome
    cd += nome
    eocd = struct.pack("<IHHHHIIH", 0x06054B50, 0, 0, 1, 1, len(cd), len(local) + len(dados), 0)
    return local + dados + cd + eocd


@pytest.mark.parametrize("nome", [b"w.npy", b"w.txt"], ids=["entrada_npy", "entrada_nao_npy"])
def test_unpack_nao_descomprime_alem_do_declarado_em_zip_forjado(nome):
    # O diretório central diz 5000 bytes; a entrada real tem 50 MiB e não começa com o magic do
    # .npy. np.load cairia em `zip.read(chave)`, que descomprime tudo de uma vez (~GB no limite).
    blob = _zip_forjado(50 * 1024 * 1024, declared=5000, nome=nome)
    assert len(blob) < MAX_ARTIFACT_BYTES
    tracemalloc.start()
    try:
        with pytest.raises(ArtifactError):
            unpack_weights(blob)
        _, pico = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert pico < 8 * 1024 * 1024  # a carga real passa de 50 MiB


def test_pack_recusa_tamanho_descomprimido_acima_do_teto():
    grande = np.zeros(MAX_ARTIFACT_UNPACKED_BYTES // 4 + 1, dtype=np.float32)
    with pytest.raises(ArtifactError, match="descomprimido"):
        pack_weights({"w": grande, "b": np.zeros(1)})


def test_maiores_modelos_da_busca_cabem_nos_dois_tetos():
    # LSTM 256 un. x 4 camadas (~7 MB comprimido) e ESN 500 un. (spec §6, §8.2).
    for par in (
        synthetic.lstm(8, units=256, layers=4, sequence_length=50),
        synthetic.esn(8, units=500),
    ):
        assert len(par[1]) <= MAX_ARTIFACT_BYTES
        assert _carregar(par).n_inputs == 8


def test_load_model_devolve_pesos_em_float64_e_n_inputs():
    m = _carregar(synthetic.pls([1.0, 2.0, 3.0], 0.5))
    assert m.n_inputs == 3
    assert m.model_id == 1
    assert all(v.dtype == np.float64 for v in m.weights.values())


def test_load_model_recusa_forma_errada():
    meta, _ = synthetic.pls([1.0, 2.0], 0.0)
    blob = pack_weights({"w": np.zeros(3), "b": np.zeros(1)})  # 3 pesos, 2 entradas
    with pytest.raises(ArtifactError):
        load_model(1, meta.model_dump(mode="json"), blob)


def test_load_model_recusa_chave_ausente():
    meta, _ = synthetic.pls([1.0], 0.0)
    with pytest.raises(ArtifactError):
        load_model(1, meta.model_dump(mode="json"), pack_weights({"w": np.zeros(1)}))


def test_load_model_recusa_blob_que_nao_e_npz():
    meta, _ = synthetic.pls([1.0], 0.0)
    with pytest.raises(ArtifactError):
        load_model(1, meta.model_dump(mode="json"), b"lixo")


def test_load_model_recusa_metadados_invalidos():
    meta, blob = synthetic.pls([1.0], 0.0)
    ruim = meta.model_dump(mode="json") | {"method": "svm"}
    with pytest.raises(ArtifactError):
        load_model(1, ruim, blob)
    extra = meta.model_dump(mode="json") | {"campo_novo": 1}
    with pytest.raises(ArtifactError):
        load_model(1, extra, blob)


@pytest.mark.parametrize(
    "sintetico",
    [
        lambda: synthetic.esn(2, units=6, warmup=4),
        lambda: synthetic.lstm(2, units=3, layers=2, sequence_length=3),
    ],
    ids=["esn", "lstm"],
)
def test_load_model_recusa_forma_errada_em_esn_e_lstm(sintetico):
    meta, blob = sintetico()
    pesos = unpack_weights(blob)
    for chave in pesos:
        adulterado = dict(pesos)
        adulterado[chave] = np.zeros(pesos[chave].size + 1)  # forma errada em UMA chave por vez
        with pytest.raises(ArtifactError):
            load_model(1, meta.model_dump(mode="json"), pack_weights(adulterado))


def test_load_model_recusa_chave_ausente_em_esn_e_lstm():
    for par in (synthetic.esn(2, units=6), synthetic.lstm(2, units=3, layers=2)):
        pesos = unpack_weights(par[1])
        for chave in pesos:
            sem = {k: v for k, v in pesos.items() if k != chave}
            with pytest.raises(ArtifactError):
                load_model(1, par[0].model_dump(mode="json"), pack_weights(sem))


def test_load_model_recusa_camada_lstm_com_lacuna():
    meta, blob = synthetic.lstm(2, units=3, layers=2)
    pesos = {
        k.replace("_1", "_2") if k.endswith("_1") else k: v for k, v in unpack_weights(blob).items()
    }  # camadas 0 e 2: a 2 não é lida em silêncio
    with pytest.raises(ArtifactError):
        load_model(1, meta.model_dump(mode="json"), pack_weights(pesos))


def test_load_model_recusa_lstm_sem_nenhuma_camada():
    # units == n_inputs: sem a recusa, fc_w seria aplicado às entradas e "funcionaria" em silêncio.
    meta, blob = synthetic.lstm(2, units=2, layers=1)
    so_a_cauda = {k: v for k, v in unpack_weights(blob).items() if not k[-2:] == "_0"}
    with pytest.raises(ArtifactError):
        load_model(1, meta.model_dump(mode="json"), pack_weights(so_a_cauda))


def test_load_model_recusa_indice_de_camada_acima_do_numero_de_chaves():
    meta, blob = synthetic.lstm(2, units=3, layers=2)
    pesos = unpack_weights(blob) | {"w_ih_9999": np.zeros(1)}  # não vira 10 mil camadas exigidas
    with pytest.raises(ArtifactError):
        load_model(1, meta.model_dump(mode="json"), pack_weights(pesos))


def test_load_model_ignora_chave_extra_com_indice_gigante_sem_estourar():
    # Fora de `\d{1,4}` é só chave desconhecida: não expande camadas nem vaza ValueError do int().
    meta, blob = synthetic.lstm(2, units=3, layers=2)
    for chave in ("w_ih_9999999999", "b_hh_" + "9" * 5000):
        pesos = unpack_weights(blob) | {chave: np.zeros(1)}
        assert _carregar_bytes(meta, pack_weights(pesos)).n_inputs == 2


def test_meta_recusa_mais_de_32_entradas_e_warmup_fora_de_1_256():
    meta, blob = synthetic.pls([1.0] * 32, 0.0)
    base = meta.model_dump(mode="json")
    assert _carregar((meta, blob)).n_inputs == 32  # limite aceito

    mais_uma = base | {"inputs": base["inputs"] + [base["inputs"][0]]}
    with pytest.raises(ArtifactError):
        load_model(1, mais_uma, pack_weights({"w": np.zeros(33), "b": np.zeros(1)}))
    with pytest.raises(ArtifactError):
        load_model(1, base | {"inputs": []}, blob)
    for ruim in (0, 257, -1):
        with pytest.raises(ArtifactError):
            load_model(1, base | {"warmup_steps": ruim}, blob)
    for bom in (1, 256):  # limites aceitos (PLS lê só a última linha; aqui só valida a meta)
        assert load_model(1, base | {"warmup_steps": bom}, blob).meta.warmup_steps == bom


def test_meta_recusa_nao_finitos_inclusive_nas_faixas_das_entradas():
    meta, blob = synthetic.pls([1.0], 0.0)
    base = meta.model_dump(mode="json")
    for ruim in (
        base | {"period_s": 0.0},
        base | {"period_s": float("nan")},
        base | {"metrics": {"r2": float("inf")}},
        base | {"inputs": [{"name": "x", "eu": "", "min": float("nan"), "max": 1.0}]},
    ):
        with pytest.raises(ArtifactError):
            load_model(1, ruim, blob)


def test_sinteticos_sao_deterministicos_com_a_mesma_semente():
    a = unpack_weights(synthetic.esn(2, seed=7)[1])
    b = unpack_weights(synthetic.esn(2, seed=7)[1])
    c = unpack_weights(synthetic.esn(2, seed=8)[1])
    assert a.keys() == b.keys()
    for k in a:
        np.testing.assert_array_equal(a[k], b[k])
    assert not np.array_equal(a["W"], c["W"])
    assert synthetic.lstm(2, seed=3)[0] == synthetic.lstm(2, seed=3)[0]  # trained_at fixo


def test_sinteticos_preenchem_janela_faixa_e_periodo():
    assert synthetic.pls([1.0], 0.0)[0].warmup_steps == 1
    assert synthetic.esn(2, warmup=5)[0].warmup_steps == 5
    assert synthetic.lstm(2, sequence_length=3)[0].warmup_steps == 3
    assert synthetic.pls([1.0], 0.0, period_s=2.5)[0].period_s == 2.5
    padrao = synthetic.pls([1.0, 2.0], 0.0)[0].inputs
    assert [(i.min, i.max) for i in padrao] == [(-1e6, 1e6)] * 2
    sob_medida = synthetic.pls([1.0], 0.0, ranges=[(0.0, 10.0)])[0].inputs
    assert (sob_medida[0].min, sob_medida[0].max) == (0.0, 10.0)


@pytest.mark.parametrize(
    ("period_s", "ts_s", "esperado"),
    [
        (6.0, 2.0, 3),
        (5.0, 5.0, 1),
        (0.3, 0.1, 3),  # 0,3 / 0,1 = 2,9999999999999996 em float: múltiplo, dentro da tolerância
        (5.0, 2.0, None),  # razão 2,5
        (1.5, 1.0, None),
        (0.5, 1.0, None),  # período menor que o Ts: menos de um passo
    ],
)
def test_model_steps_e_o_multiplo_inteiro_do_ts_ou_none(period_s, ts_s, esperado):
    assert model_steps(period_s, ts_s) == esperado
