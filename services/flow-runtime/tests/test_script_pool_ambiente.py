"""TD-001: o worker do `ScriptPool` não pode herdar segredo nenhum do processo pai via
variável de ambiente (`OTTIMA_DATABASE_URL`/`OTTIMA_REDIS_URL`, injetadas no flow-runtime
pelo compose) — defesa em profundidade contra fuga do sandbox do código de Script.

`fork` (não `spawn`, usado em produção) preserva no filho o monkeypatch de `_run_script`
feito no pai antes do `Process.start()`: permite observar `os.environ` de dentro do worker
sem depender do sandbox do código de Script, que já bloqueia `os` por design (sem
`__import__` em `ALLOWED_BUILTINS`, spec §3.3) e por isso não serve de sonda para este
teste — o objetivo aqui é o processo do worker em si, não o que o script do usuário alcança.
"""

import multiprocessing as mp
import os

from ottima_flow_runtime import script_pool
from ottima_flow_runtime.script_pool import ScriptResult


def test_worker_limpa_o_ambiente_antes_do_primeiro_job(monkeypatch):
    monkeypatch.setenv("OTTIMA_DATABASE_URL", "postgresql://user:senha@host/banco")

    def _sonda_environ(
        code: str, inputs: dict[str, float], state: object, n_outputs: int
    ) -> ScriptResult:
        return ScriptResult("ok", {"OUT1": float(len(os.environ))}, None, None)

    monkeypatch.setattr(script_pool, "_run_script", _sonda_environ)

    ctx = mp.get_context("fork")
    parent_conn, child_conn = ctx.Pipe()
    proc = ctx.Process(target=script_pool._worker_main, args=(child_conn,))
    proc.start()
    child_conn.close()
    try:
        assert parent_conn.recv() == script_pool._READY
        parent_conn.send(("", {}, None, 1))
        resultado = parent_conn.recv()
        # Zero: nem OTTIMA_DATABASE_URL, nem PATH/HOME/o-que-for — o worker não enxerga
        # nada do ambiente do pai depois do scrub.
        assert resultado.outputs == {"OUT1": 0.0}
    finally:
        parent_conn.send(None)
        proc.join(timeout=2.0)
        if proc.is_alive():
            proc.kill()
            proc.join(timeout=2.0)
        parent_conn.close()
