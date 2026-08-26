"""Log do worker: o asyncua fica mudo para o loop de reconexão não floodar o log.

Com um endpoint fora do ar, o loop de reconexão (§2.2-2, teto de backoff 30 s)
tenta a cada ~15 s e a biblioteca loga a teardown dela em ERROR com traceback
completo a cada tentativa — toneladas de log e CPU à toa. O diagnóstico compacto
já é nosso (`connection.fail`, uma linha por tentativa): o asyncua é silenciado.
"""

import logging

from ottima_opc_worker.main import configure_worker_logging


def test_asyncua_silenciado_no_boot_do_worker() -> None:
    configure_worker_logging("INFO")
    assert logging.getLogger("asyncua").level == logging.CRITICAL
