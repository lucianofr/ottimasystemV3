"""Mesa de casos do bloco `mpc` em `validate_graph` (spec F4 §2.2, plano F4a tarefa 1.2).

Cada caso inválido muta exatamente um campo do esqueleto válido de referência montado por
`mpc_node()`/`mpc_graph()`, mesmo padrão de `test_flowgraph.py`: a diferença entre "passa" e
"reprova" fica explícita no teste. `mpc_graph()` fia automaticamente uma leitura OPC dedicada
em cada porta de entrada dinâmica (CV/Restrição/DV — decisão A-10), então os testes de
caps/matriz/números/horizontes/pid ficam isolados da regra de portas obrigatórias.
"""

from ottima_core.flowgraph import TagRef, parse_graph, validate_graph

TS = 1.0


# --------------------------------------------------------------------------------------
# Construtores do esqueleto §2.1
# --------------------------------------------------------------------------------------


def pid_binding(tag_base: int, *, with_mode_read: bool = True) -> dict:
    binding = {
        "write_tag_id": tag_base,
        "target_mode": "rcas",
        "mode_cmd_tag_id": tag_base + 1,
        "readback_tag_id": tag_base + 2,
        "mode_values": {"auto": 1, "target": 3},
    }
    if with_mode_read:
        binding["mode_read_tag_id"] = tag_base + 3
    return binding


def mv(suffix: str, *, pid: dict | None = None, **overrides) -> dict:
    node = {
        "id": f"mv_{suffix}",
        "name": f"MV {suffix}",
        "eu": "m3/h",
        "limits": {"min": 0.0, "max": 100.0},
        "du_max": 5.0,
        "initial_value": 0.0,
    }
    if pid is not None:
        node["pid"] = pid
    node.update(overrides)
    return node


def cv(suffix: str, *, kind: str = "selfreg", tss: float = 30.0, weight: float = 1.0, **overrides) -> dict:
    node = {
        "id": f"cv_{suffix}",
        "name": f"CV {suffix}",
        "eu": "C",
        "kind": kind,
        "tss": tss,
        "weight": weight,
        "sp_limits": {"min": 80.0, "max": 120.0},
    }
    node.update(overrides)
    return node


def co(suffix: str, *, kind: str = "selfreg", tss: float = 45.0, priority: int = 1, **overrides) -> dict:
    node = {
        "id": f"co_{suffix}",
        "name": f"Restrição {suffix}",
        "eu": "%",
        "kind": kind,
        "tss": tss,
        "range": {"low": 20.0, "high": 80.0},
        "priority": priority,
    }
    node.update(overrides)
    return node


def dv(suffix: str) -> dict:
    return {"id": f"dv_{suffix}", "name": f"DV {suffix}", "eu": "m3/h"}


def selfreg_params(**overrides: float) -> dict:
    return {"K": 1.2, "tau1": 10.0, "tau2": 2.0, "theta": 15.0, **overrides}


def integrating_params(**overrides: float) -> dict:
    return {"Ki": 0.5, "theta": 10.0, **overrides}


def pair(kind: str = "selfreg", *, enabled: bool = True, **param_overrides: float) -> dict:
    params = selfreg_params(**param_overrides) if kind == "selfreg" else integrating_params(**param_overrides)
    return {"enabled": enabled, "params": params}


def _auto_models(rows: list[dict], columns: list[dict]) -> dict:
    """Matriz totalmente conectada (todo par habilitado e válido) — isola os testes de
    caps/números/horizontes/pid/portas da regra de matriz (§2.2-3), que ganha seus próprios
    casos dedicados."""
    return {row["id"]: {col["id"]: pair(row["kind"]) for col in columns} for row in rows}


def mpc_node(
    *,
    mvs: list[dict] | None = None,
    cvs: list[dict] | None = None,
    constraints: list[dict] | None = None,
    dvs: list[dict] | None = None,
    models: dict | None = None,
    multiplier: int = 1,
    name: str = "MPC teste",
    node_id: str = "m1",
) -> dict:
    mvs = [mv("a")] if mvs is None else mvs
    cvs = [cv("a")] if cvs is None else cvs
    constraints = [] if constraints is None else constraints
    dvs = [] if dvs is None else dvs
    rows = [*cvs, *constraints]
    columns = [*mvs, *dvs]
    if models is None:
        models = _auto_models(rows, columns)
    return {
        "id": node_id,
        "type": "mpc",
        "position": {"x": 0.0, "y": 0.0},
        "data": {
            "exec_order": 1,  # mpc_graph() sobrescreve para depois dos leitores
            "name": name,
            "multiplier": multiplier,
            "variables": {"mvs": mvs, "cvs": cvs, "constraints": constraints, "dvs": dvs},
            "models": models,
        },
    }


def mpc_graph(node: dict) -> dict:
    """Grafo com um único bloco `mpc`, cada porta de entrada dinâmica obrigatória (CV,
    Restrição, DV — decisão A-10) fiada a um leitor OPC dedicado; as saídas MV ficam livres
    de propósito (podem ficar desconectadas, spec §2.1-5).
    """
    variables = node["data"]["variables"]
    input_ids = [v["id"] for v in (*variables["cvs"], *variables["constraints"], *variables["dvs"])]

    sources: list[dict] = []
    edges: list[dict] = []
    for index, input_id in enumerate(input_ids, start=1):
        source_id = f"r{index}"
        sources.append(
            {
                "id": source_id,
                "type": "opc_read",
                "position": {"x": -200.0, "y": float(index) * 80.0},
                "data": {"exec_order": index, "tag_id": 900 + index},
            }
        )
        edges.append(
            {
                "id": f"e{index}",
                "source": source_id,
                "target": node["id"],
                "sourceHandle": "out",
                "targetHandle": input_id,
            }
        )
    node["data"]["exec_order"] = len(sources) + 1
    return {"nodes": [*sources, node], "edges": edges}


def mpc_tags(node: dict) -> dict[int, TagRef]:
    """Tags do projeto: uma leitura por porta de entrada + as do `pid` de cada MV."""
    variables = node["data"]["variables"]
    input_ids = [v["id"] for v in (*variables["cvs"], *variables["constraints"], *variables["dvs"])]
    tags: dict[int, TagRef] = {
        900 + index: TagRef(id=900 + index, conn_id=1, direction="r", data_type="float")
        for index in range(1, len(input_ids) + 1)
    }
    for m in variables["mvs"]:
        pid = m.get("pid")
        if not pid:
            continue
        tags[pid["write_tag_id"]] = TagRef(
            id=pid["write_tag_id"], conn_id=2, direction="w", data_type="float"
        )
        tags[pid["mode_cmd_tag_id"]] = TagRef(
            id=pid["mode_cmd_tag_id"], conn_id=2, direction="w", data_type="float"
        )
        tags[pid["readback_tag_id"]] = TagRef(
            id=pid["readback_tag_id"], conn_id=2, direction="r", data_type="float"
        )
        mode_read = pid.get("mode_read_tag_id")
        if mode_read is not None:
            tags[mode_read] = TagRef(id=mode_read, conn_id=2, direction="r", data_type="float")
    return tags


def result_of(graph: dict, tags: dict[int, TagRef], ts_seconds: float = TS):
    return validate_graph(parse_graph(graph), tags, ts_seconds)


def errors_of(graph: dict, tags: dict[int, TagRef], ts_seconds: float = TS) -> list[str]:
    return result_of(graph, tags, ts_seconds).errors


def warnings_of(graph: dict, tags: dict[int, TagRef], ts_seconds: float = TS) -> list[str]:
    return result_of(graph, tags, ts_seconds).warnings


def has(messages: list[str], *fragments: str) -> bool:
    """Alguma mensagem contém todos os fragmentos."""
    return any(all(fragment in message for fragment in fragments) for message in messages)


# --------------------------------------------------------------------------------------
# item 1 — mpc sai da lista de tipos rejeitados
# --------------------------------------------------------------------------------------


def test_parse_aceita_tipo_mpc():
    """Item 1 do Entregável: `mpc` sai da lista de tipos rejeitados (decisão A-1 revista)."""
    graph = parse_graph(mpc_graph(mpc_node()))
    assert graph.node("m1").type == "mpc"


def test_esqueleto_valido_aprova_sem_erros_nem_warnings():
    node = mpc_node(mvs=[mv("a", pid=pid_binding(10))])
    graph = mpc_graph(node)
    tags = mpc_tags(node)
    result = result_of(graph, tags)
    assert result.errors == []
    assert result.warnings == []


# --------------------------------------------------------------------------------------
# regra 2 — tetos (MVs 1..4, CVs+Restrições 1..6, DVs 0..4)
# --------------------------------------------------------------------------------------


def test_zero_mv_e_erro():
    node = mpc_node(mvs=[], cvs=[cv("a")])
    graph = mpc_graph(node)
    tags = mpc_tags(node)
    assert has(errors_of(graph, tags), "MVs", "1..4")


def test_um_mv_aprova():
    node = mpc_node(mvs=[mv("a")], cvs=[cv("a")])
    graph = mpc_graph(node)
    tags = mpc_tags(node)
    assert not has(errors_of(graph, tags), "MVs", "1..4")


def test_quatro_mv_aprova():
    node = mpc_node(mvs=[mv(letter) for letter in "abcd"], cvs=[cv("a")])
    graph = mpc_graph(node)
    tags = mpc_tags(node)
    assert not has(errors_of(graph, tags), "MVs", "1..4")


def test_cinco_mv_e_erro():
    node = mpc_node(mvs=[mv(letter) for letter in "abcde"], cvs=[cv("a")])
    graph = mpc_graph(node)
    tags = mpc_tags(node)
    assert has(errors_of(graph, tags), "MVs", "1..4")


def test_zero_cv_e_restricao_e_erro():
    node = mpc_node(cvs=[], constraints=[])
    graph = mpc_graph(node)
    tags = mpc_tags(node)
    assert has(errors_of(graph, tags), "CVs somadas a Restrições", "1..6")


def test_seis_cv_mais_restricao_aprova():
    node = mpc_node(cvs=[cv(letter) for letter in "abc"], constraints=[co(letter) for letter in "def"])
    graph = mpc_graph(node)
    tags = mpc_tags(node)
    assert not has(errors_of(graph, tags), "CVs somadas a Restrições", "1..6")


def test_sete_cv_mais_restricao_e_erro():
    node = mpc_node(cvs=[cv(letter) for letter in "abcd"], constraints=[co(letter) for letter in "efg"])
    graph = mpc_graph(node)
    tags = mpc_tags(node)
    assert has(errors_of(graph, tags), "CVs somadas a Restrições", "1..6")


def test_zero_dv_aprova():
    node = mpc_node(dvs=[])
    graph = mpc_graph(node)
    tags = mpc_tags(node)
    assert not has(errors_of(graph, tags), "DVs", "0..4")


def test_quatro_dv_aprova():
    node = mpc_node(dvs=[dv(letter) for letter in "abcd"])
    graph = mpc_graph(node)
    tags = mpc_tags(node)
    assert not has(errors_of(graph, tags), "DVs", "0..4")


def test_cinco_dv_e_erro():
    node = mpc_node(dvs=[dv(letter) for letter in "abcde"])
    graph = mpc_graph(node)
    tags = mpc_tags(node)
    assert has(errors_of(graph, tags), "DVs", "0..4")


# --------------------------------------------------------------------------------------
# regra 3 — matriz `models`
# --------------------------------------------------------------------------------------


def test_linha_so_com_par_de_dv_e_erro():
    m, c, d = mv("a"), cv("a"), dv("a")
    models = {c["id"]: {m["id"]: pair("selfreg", enabled=False), d["id"]: pair("selfreg")}}
    node = mpc_node(mvs=[m], cvs=[c], dvs=[d], models=models)
    graph = mpc_graph(node)
    tags = mpc_tags(node)
    assert has(errors_of(graph, tags), "cv_a", "cuja coluna é MV")


def test_mv_sem_par_habilitado_e_erro():
    m1, m2, c = mv("a"), mv("b"), cv("a")
    models = {c["id"]: {m1["id"]: pair("selfreg"), m2["id"]: pair("selfreg", enabled=False)}}
    node = mpc_node(mvs=[m1, m2], cvs=[c], models=models)
    graph = mpc_graph(node)
    tags = mpc_tags(node)
    assert has(errors_of(graph, tags), "mv_b", "não tem nenhum par habilitado")


def test_dv_sem_par_habilitado_e_erro():
    m, c, d = mv("a"), cv("a"), dv("a")
    models = {c["id"]: {m["id"]: pair("selfreg"), d["id"]: pair("selfreg", enabled=False)}}
    node = mpc_node(mvs=[m], cvs=[c], dvs=[d], models=models)
    graph = mpc_graph(node)
    tags = mpc_tags(node)
    assert has(errors_of(graph, tags), "dv_a", "não tem nenhum par habilitado")


def test_par_habilitado_selfreg_com_params_incompletos_e_erro():
    m, c = mv("a"), cv("a", kind="selfreg")
    bad_pair = {"enabled": True, "params": {"K": 1.0, "tau1": 10.0, "theta": 5.0}}  # falta tau2
    node = mpc_node(mvs=[m], cvs=[c], models={c["id"]: {m["id"]: bad_pair}})
    graph = mpc_graph(node)
    tags = mpc_tags(node)
    assert has(errors_of(graph, tags), "cv_a", "mv_a", "params inválidos ou incompletos")


def test_par_habilitado_integrating_com_ki_zero_e_erro():
    m, c = mv("a"), cv("a", kind="integrating")
    models = {c["id"]: {m["id"]: pair("integrating", Ki=0.0)}}
    node = mpc_node(mvs=[m], cvs=[c], models=models)
    graph = mpc_graph(node)
    tags = mpc_tags(node)
    assert has(errors_of(graph, tags), "cv_a", "mv_a", "params inválidos ou incompletos")


def test_linha_orfa_em_models_e_erro():
    m, c = mv("a"), cv("a")
    models = {c["id"]: {m["id"]: pair("selfreg")}, "cv_fantasma": {m["id"]: pair("selfreg")}}
    node = mpc_node(mvs=[m], cvs=[c], models=models)
    graph = mpc_graph(node)
    tags = mpc_tags(node)
    assert has(errors_of(graph, tags), "cv_fantasma", "não corresponde a nenhuma CV ou Restrição")


def test_coluna_orfa_em_models_e_erro():
    m, c = mv("a"), cv("a")
    models = {c["id"]: {m["id"]: pair("selfreg"), "mv_fantasma": pair("selfreg")}}
    node = mpc_node(mvs=[m], cvs=[c], models=models)
    graph = mpc_graph(node)
    tags = mpc_tags(node)
    assert has(errors_of(graph, tags), "mv_fantasma", "não corresponde a nenhuma MV ou DV")


# --------------------------------------------------------------------------------------
# regra 4 — números
# --------------------------------------------------------------------------------------


def test_tss_zero_na_cv_e_erro():
    node = mpc_node(cvs=[cv("a", tss=0.0)])
    graph = mpc_graph(node)
    tags = mpc_tags(node)
    assert has(errors_of(graph, tags), "cv_a", "tss > 0")


def test_tss_zero_na_restricao_e_erro():
    node = mpc_node(cvs=[], constraints=[co("a", tss=0.0)])
    graph = mpc_graph(node)
    tags = mpc_tags(node)
    assert has(errors_of(graph, tags), "co_a", "tss > 0")


def test_limits_min_maior_ou_igual_a_max_e_erro():
    node = mpc_node(mvs=[mv("a", limits={"min": 50.0, "max": 50.0})])
    graph = mpc_graph(node)
    tags = mpc_tags(node)
    assert has(errors_of(graph, tags), "mv_a", "limits.min < limits.max")


def test_sp_limits_min_maior_ou_igual_a_max_e_erro():
    node = mpc_node(cvs=[cv("a", sp_limits={"min": 100.0, "max": 100.0})])
    graph = mpc_graph(node)
    tags = mpc_tags(node)
    assert has(errors_of(graph, tags), "cv_a", "sp_limits.min < sp_limits.max")


def test_range_low_maior_ou_igual_a_high_e_erro():
    node = mpc_node(cvs=[], constraints=[co("a", range={"low": 50.0, "high": 50.0})])
    graph = mpc_graph(node)
    tags = mpc_tags(node)
    assert has(errors_of(graph, tags), "co_a", "range.low < range.high")


def test_du_max_zero_e_erro():
    node = mpc_node(mvs=[mv("a", du_max=0.0)])
    graph = mpc_graph(node)
    tags = mpc_tags(node)
    assert has(errors_of(graph, tags), "mv_a", "du_max > 0")


def test_weight_zero_e_erro():
    node = mpc_node(cvs=[cv("a", weight=0.0)])
    graph = mpc_graph(node)
    tags = mpc_tags(node)
    assert has(errors_of(graph, tags), "cv_a", "weight > 0")


def test_priority_zero_e_erro_estrutural():
    """`priority: Field(ge=1)` já trava em `MpcConfig` (tarefa 1.1) — a reprovação sai pelo
    mesmo canal `ValidationResult.errors`, via `MpcConfig.model_validate` (§2.2-1)."""
    node = mpc_node(cvs=[], constraints=[co("a", priority=0)])
    graph = mpc_graph(node)
    tags = mpc_tags(node)
    assert has(errors_of(graph, tags), "priority")


# --------------------------------------------------------------------------------------
# regra 5/7 — horizontes (Np) e dimensão de estados
# --------------------------------------------------------------------------------------


def test_np_abaixo_do_piso_e_erro():
    node = mpc_node(multiplier=1000, cvs=[cv("a")])  # tss padrão 30.0 -> Np=1
    graph = mpc_graph(node)
    tags = mpc_tags(node)
    assert has(errors_of(graph, tags), "multiplicador grande demais para o TSS")


def test_np_no_piso_aprova():
    node = mpc_node(multiplier=20, cvs=[cv("a")])  # Np=ceil(30/20)=2
    graph = mpc_graph(node)
    tags = mpc_tags(node)
    errors = errors_of(graph, tags)
    assert not has(errors, "multiplicador grande demais")
    assert not has(errors, "aumente o multiplicador")


def test_np_no_teto_aprova_com_warning():
    node = mpc_node(multiplier=1, cvs=[cv("a", tss=120.0)])  # Np=120
    graph = mpc_graph(node)
    tags = mpc_tags(node)
    result = result_of(graph, tags)
    assert not has(result.errors, "aumente o multiplicador")
    assert has(result.warnings, "Np=120", "acima de 60")


def test_np_acima_do_teto_e_erro():
    node = mpc_node(multiplier=1, cvs=[cv("a", tss=121.0)])  # Np=121
    graph = mpc_graph(node)
    tags = mpc_tags(node)
    assert has(errors_of(graph, tags), "aumente o multiplicador ou reduza o TSS")


def test_np_no_limiar_do_warning_nao_avisa():
    node = mpc_node(multiplier=1, cvs=[cv("a", tss=60.0)])  # Np=60, limite exato
    graph = mpc_graph(node)
    tags = mpc_tags(node)
    assert not has(warnings_of(graph, tags), "acima de 60")


def test_np_acima_do_limiar_avisa():
    node = mpc_node(multiplier=1, cvs=[cv("a", tss=61.0)])  # Np=61
    graph = mpc_graph(node)
    tags = mpc_tags(node)
    result = result_of(graph, tags)
    assert result.errors == []
    assert has(result.warnings, "Np=61", "acima de 60")


def test_dimensao_no_teto_nao_avisa():
    m, c = mv("a"), cv("a")
    models = {c["id"]: {m["id"]: pair("selfreg", theta=117.0)}}  # 2 + round(117/1) + 1 = 120
    node = mpc_node(mvs=[m], cvs=[c], multiplier=1, models=models)
    graph = mpc_graph(node)
    tags = mpc_tags(node)
    assert not has(warnings_of(graph, tags), "dimensão de estados")


def test_dimensao_acima_do_teto_avisa():
    m, c = mv("a"), cv("a")
    models = {c["id"]: {m["id"]: pair("selfreg", theta=118.0)}}  # 2 + round(118/1) + 1 = 121
    node = mpc_node(mvs=[m], cvs=[c], multiplier=1, models=models)
    graph = mpc_graph(node)
    tags = mpc_tags(node)
    assert has(warnings_of(graph, tags), "dimensão de estados")


# --------------------------------------------------------------------------------------
# regra 6 — integridade de tags do `pid`
# --------------------------------------------------------------------------------------


def test_pid_tag_inexistente_e_erro():
    node = mpc_node(mvs=[mv("a", pid=pid_binding(10))])
    graph = mpc_graph(node)
    tags = mpc_tags(node)
    del tags[10]  # write_tag_id não pertence (mais) ao projeto do flow
    assert has(errors_of(graph, tags), "mv_a", "10", "não existe ou não pertence ao projeto")


def test_pid_tag_direcao_trocada_na_escrita_e_erro():
    node = mpc_node(mvs=[mv("a", pid=pid_binding(10))])
    graph = mpc_graph(node)
    tags = mpc_tags(node)
    tags[10] = TagRef(id=10, conn_id=2, direction="r", data_type="float")  # write exige 'w'
    assert has(errors_of(graph, tags), "mv_a", "10", "direção")


def test_pid_tag_direcao_trocada_na_leitura_e_erro():
    node = mpc_node(mvs=[mv("a", pid=pid_binding(10))])
    graph = mpc_graph(node)
    tags = mpc_tags(node)
    tags[12] = TagRef(id=12, conn_id=2, direction="w", data_type="float")  # readback exige 'r'
    assert has(errors_of(graph, tags), "mv_a", "12", "direção")


def test_mv_sem_pid_e_direta():
    """MV sem `pid` é "direta" (decisão A-8): nenhuma checagem de tag para ela."""
    node = mpc_node(mvs=[mv("a")])
    graph = mpc_graph(node)
    tags = mpc_tags(node)
    assert result_of(graph, tags).errors == []


# --------------------------------------------------------------------------------------
# regra 5 do §2.1 / decisão A-10 — portas dinâmicas
# --------------------------------------------------------------------------------------


def test_entrada_cv_desconectada_e_erro():
    node = mpc_node(cvs=[cv("a")])
    graph = mpc_graph(node)
    tags = mpc_tags(node)
    graph["edges"] = [e for e in graph["edges"] if e["targetHandle"] != "cv_a"]
    assert has(errors_of(graph, tags), "m1", "cv_a", "obrigatória")


def test_saida_mv_desconectada_e_aprovada():
    """Saída de MV pode ficar solta — a malha real usa as tags do `pid` (spec §2.1-5)."""
    node = mpc_node(mvs=[mv("a")])
    graph = mpc_graph(node)  # nenhuma aresta liga a saída mv_a
    tags = mpc_tags(node)
    assert result_of(graph, tags).errors == []
