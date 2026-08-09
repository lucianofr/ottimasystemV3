"""Mesa de casos de `ottima_core.portability.tag_ref` (spec F6 §2.2-1/2/3/5, decisão A-2).

`TAG_REF_FIELDS` é o único lugar onde a lista de campos com referência de tag vive —
`test_completude_...` prova por introspecção que ela cobre todo `*_tag_id` de
`_CONFIG_KEYS` (`parse.py`) e `PidBinding.model_fields` (`mpc_config.py`); um campo novo
esquecido no registro deve deixar esse teste vermelho.
"""

import pytest

from ottima_core.flowgraph.mpc_config import PidBinding
from ottima_core.flowgraph.parse import _CONFIG_KEYS
from ottima_core.portability.tag_ref import (
    CAMPOS_NO_DATA,
    CAMPOS_NO_PID,
    TAG_REF_FIELDS,
    CampoTagRef,
    ReferenciaTagInvalida,
    grafo_para_banco,
    grafo_para_bundle,
    problemas_de_tag_ref,
)


def grafo_banco() -> dict:
    """Grafo de referência na forma banco (`*_tag_id`): `opc_read`, `opc_write` e um `mpc`
    de 2 MVs — a primeira com `mode_read_tag_id`, a segunda sem (campo opcional ausente)."""
    return {
        "nodes": [
            {
                "id": "r1",
                "type": "opc_read",
                "position": {"x": 0.0, "y": 0.0},
                "data": {"exec_order": 1, "label": "Leitura TT-101", "tag_id": 101},
            },
            {
                "id": "w1",
                "type": "opc_write",
                "position": {"x": 100.0, "y": 0.0},
                "data": {"exec_order": 2, "label": "Escrita PV-201", "tag_id": 202},
            },
            {
                "id": "m1",
                "type": "mpc",
                "position": {"x": 200.0, "y": 0.0},
                "data": {
                    "exec_order": 3,
                    "label": "MPC coluna",
                    "name": "mpc-1",
                    "multiplier": 1,
                    "models": {},
                    "variables": {
                        "mvs": [
                            {
                                "id": "mv_1",
                                "name": "MV1",
                                "eu": "%",
                                "limits": {"min": 0.0, "max": 100.0},
                                "du_max": 5.0,
                                "initial_value": 0.0,
                                "pid": {
                                    "write_tag_id": 301,
                                    "target_mode": "cas",
                                    "mode_cmd_tag_id": 302,
                                    "mode_read_tag_id": 303,
                                    "readback_tag_id": 304,
                                    "mode_values": {"auto": 0, "target": 1},
                                },
                            },
                            {
                                "id": "mv_2",
                                "name": "MV2",
                                "eu": "%",
                                "limits": {"min": 0.0, "max": 100.0},
                                "du_max": 5.0,
                                "initial_value": 0.0,
                                "pid": {
                                    "write_tag_id": 401,
                                    "target_mode": "cas",
                                    "mode_cmd_tag_id": 402,
                                    "readback_tag_id": 404,
                                    "mode_values": {"auto": 0, "target": 1},
                                },
                            },
                        ],
                        "cvs": [],
                        "constraints": [],
                        "dvs": [],
                    },
                },
            },
        ],
        "edges": [],
    }


REF_POR_ID: dict[int, tuple[str, str]] = {
    101: ("gateway-1", "TT-101"),
    202: ("gateway-1", "PV-201"),
    301: ("gateway-1", "MV1_W"),
    302: ("gateway-1", "MV1_MODE_CMD"),
    303: ("gateway-1", "MV1_MODE_READ"),
    304: ("gateway-1", "MV1_READBACK"),
    401: ("gateway-1", "MV2_W"),
    402: ("gateway-1", "MV2_MODE_CMD"),
    404: ("gateway-1", "MV2_READBACK"),
}
ID_POR_REF: dict[tuple[str, str], int] = {v: k for k, v in REF_POR_ID.items()}


class TestCampos:
    def test_tag_ref_fields_e_a_concatenacao_dos_dois_grupos(self) -> None:
        assert TAG_REF_FIELDS == CAMPOS_NO_DATA + CAMPOS_NO_PID
        assert len(TAG_REF_FIELDS) == 5

    def test_campo_tag_ref_e_frozen_e_slots(self) -> None:
        campo = CampoTagRef("tag_id", "tag_ref", True)
        with pytest.raises(AttributeError):
            campo.id_key = "outro"  # type: ignore[misc]
        assert not hasattr(campo, "__dict__")  # slots=True: sem __dict__ por instância

    def test_mode_read_tag_id_e_o_unico_campo_opcional(self) -> None:
        opcionais = [campo.id_key for campo in TAG_REF_FIELDS if not campo.obrigatorio]
        assert opcionais == ["mode_read_tag_id"]

    def test_completude_tag_ref_fields_cobre_todo_id_key_tag_id(self) -> None:
        """TST-06: introspecção — `TAG_REF_FIELDS` cobre todo campo `*_tag_id` de
        `_CONFIG_KEYS` (nós `data`) e de `PidBinding.model_fields` (nós `pid`)."""
        ids_data = {key for keys in _CONFIG_KEYS.values() for key in keys if key.endswith("tag_id")}
        ids_pid = {name for name in PidBinding.model_fields if name.endswith("tag_id")}
        esperado = ids_data | ids_pid
        registrado = {campo.id_key for campo in TAG_REF_FIELDS}
        assert registrado == esperado

    def test_completude_detectaria_campo_novo_nao_registrado(self) -> None:
        """Prova que a introspecção acima é sensível: um `*_tag_id` extra simulado (como se
        alguém tivesse acrescentado um campo de referência de tag e esquecido de registrar
        aqui) quebra a igualdade de conjuntos que `test_completude_...` exige."""
        ids_data = {key for keys in _CONFIG_KEYS.values() for key in keys if key.endswith("tag_id")}
        ids_pid = {name for name in PidBinding.model_fields if name.endswith("tag_id")}
        esperado_com_campo_esquecido = ids_data | ids_pid | {"novo_setpoint_tag_id"}
        registrado = {campo.id_key for campo in TAG_REF_FIELDS}
        assert registrado != esperado_com_campo_esquecido


class TestGrafoParaBundle:
    def test_troca_tag_id_por_tag_ref_nos_6_lugares(self) -> None:
        bundle = grafo_para_bundle(grafo_banco(), REF_POR_ID)

        r1 = bundle["nodes"][0]["data"]
        assert "tag_id" not in r1
        assert r1["tag_ref"] == {"connection": "gateway-1", "tag": "TT-101"}

        w1 = bundle["nodes"][1]["data"]
        assert w1["tag_ref"] == {"connection": "gateway-1", "tag": "PV-201"}

        mvs = bundle["nodes"][2]["data"]["variables"]["mvs"]
        pid_1 = mvs[0]["pid"]
        assert pid_1["write_tag_ref"] == {"connection": "gateway-1", "tag": "MV1_W"}
        assert pid_1["mode_cmd_tag_ref"] == {"connection": "gateway-1", "tag": "MV1_MODE_CMD"}
        assert pid_1["mode_read_tag_ref"] == {"connection": "gateway-1", "tag": "MV1_MODE_READ"}
        assert pid_1["readback_tag_ref"] == {"connection": "gateway-1", "tag": "MV1_READBACK"}
        assert not any(key.endswith("_tag_id") for key in pid_1)

        pid_2 = mvs[1]["pid"]
        assert "mode_read_tag_ref" not in pid_2
        assert "mode_read_tag_id" not in pid_2

    def test_nao_muta_o_grafo_recebido(self) -> None:
        original = grafo_banco()
        congelado = grafo_banco()
        grafo_para_bundle(original, REF_POR_ID)
        assert original == congelado

    def test_id_ausente_do_mapa_levanta_com_caminho_do_no_agregado(self) -> None:
        mapa_incompleto = dict(REF_POR_ID)
        del mapa_incompleto[101]
        del mapa_incompleto[303]

        with pytest.raises(ReferenciaTagInvalida) as excinfo:
            grafo_para_bundle(grafo_banco(), mapa_incompleto)

        problemas = excinfo.value.problemas
        assert len(problemas) == 2
        assert any("nó 'r1'" in problema for problema in problemas)
        assert any("nó 'm1'" in problema for problema in problemas)

    def test_campo_obrigatorio_ausente_no_grafo_vira_problema_sem_keyerror(self) -> None:
        grafo = grafo_banco()
        del grafo["nodes"][0]["data"]["tag_id"]

        with pytest.raises(ReferenciaTagInvalida) as excinfo:
            grafo_para_bundle(grafo, REF_POR_ID)

        problemas = excinfo.value.problemas
        assert any("tag_id" in problema and "obrigatório" in problema for problema in problemas)


class TestGrafoParaBanco:
    def test_round_trip_byte_a_byte_dos_6_lugares(self) -> None:
        banco_original = grafo_banco()
        bundle = grafo_para_bundle(grafo_banco(), REF_POR_ID)
        banco_reconstruido = grafo_para_banco(bundle, ID_POR_REF)
        assert banco_reconstruido == banco_original

    def test_ref_desconhecida_levanta_agregado(self) -> None:
        bundle = grafo_para_bundle(grafo_banco(), REF_POR_ID)
        mapa_incompleto = dict(ID_POR_REF)
        del mapa_incompleto[("gateway-1", "PV-201")]

        with pytest.raises(ReferenciaTagInvalida) as excinfo:
            grafo_para_banco(bundle, mapa_incompleto)

        assert any("nó 'w1'" in problema for problema in excinfo.value.problemas)

    def test_pid_sem_write_tag_ref_vira_problema_sem_excecao_de_chave(self) -> None:
        bundle = grafo_para_bundle(grafo_banco(), REF_POR_ID)
        pid_1 = bundle["nodes"][2]["data"]["variables"]["mvs"][0]["pid"]
        del pid_1["write_tag_ref"]

        with pytest.raises(ReferenciaTagInvalida) as excinfo:
            grafo_para_banco(bundle, ID_POR_REF)

        problemas = excinfo.value.problemas
        assert len(problemas) == 1
        assert "write_tag_ref" in problemas[0]
        assert "obrigatório" in problemas[0]


class TestProblemasDeTagRef:
    def test_grafo_valido_nao_tem_problemas(self) -> None:
        bundle = grafo_para_bundle(grafo_banco(), REF_POR_ID)
        refs = set(REF_POR_ID.values())
        assert problemas_de_tag_ref(bundle, onde="fluxo 'Coluna C-101'", refs=refs) == []

    def test_ref_desconhecida_vira_problema(self) -> None:
        bundle = grafo_para_bundle(grafo_banco(), REF_POR_ID)
        refs = set(REF_POR_ID.values()) - {("gateway-1", "TT-101")}
        problemas = problemas_de_tag_ref(bundle, onde="fluxo 'X'", refs=refs)
        assert len(problemas) == 1
        assert "nó 'r1'" in problemas[0]
        assert "TT-101" in problemas[0]

    def test_campo_obrigatorio_ausente_vira_problema_sem_traduzir(self) -> None:
        bundle = grafo_para_bundle(grafo_banco(), REF_POR_ID)
        del bundle["nodes"][2]["data"]["variables"]["mvs"][0]["pid"]["readback_tag_ref"]
        problemas = problemas_de_tag_ref(bundle, onde="fluxo 'X'", refs=set(REF_POR_ID.values()))
        assert len(problemas) == 1
        assert "readback_tag_ref" in problemas[0]
        assert "obrigatório" in problemas[0]

    def test_campo_opcional_ausente_nao_e_problema(self) -> None:
        bundle = grafo_para_bundle(grafo_banco(), REF_POR_ID)
        pid_2 = bundle["nodes"][2]["data"]["variables"]["mvs"][1]["pid"]
        assert "mode_read_tag_ref" not in pid_2
        problemas = problemas_de_tag_ref(bundle, onde="fluxo 'X'", refs=set(REF_POR_ID.values()))
        assert problemas == []

    def test_ref_mal_formada_vira_problema_sem_excecao(self) -> None:
        bundle = grafo_para_bundle(grafo_banco(), REF_POR_ID)
        bundle["nodes"][0]["data"]["tag_ref"] = "gateway-1/TT-101"
        problemas = problemas_de_tag_ref(bundle, onde="fluxo 'X'", refs=set(REF_POR_ID.values()))
        assert len(problemas) == 1
        assert "nó 'r1'" in problemas[0]

    def test_nodes_nao_lista_vira_problema_unico(self) -> None:
        problemas = problemas_de_tag_ref({"nodes": None}, onde="fluxo 'X'", refs=set())
        assert len(problemas) == 1
        assert "nodes" in problemas[0]
