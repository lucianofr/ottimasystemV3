"""Portabilidade de projeto (spec F6 §2): schemas do arquivo de projeto (bundle),
tradução de referência de tag nos dois sentidos, e montagem/coerência interna do
bundle. Tudo puro — nenhum símbolo daqui toca banco, Redis ou disco.
"""

from ottima_core.portability.bundle import (
    montar_bundle,
    problemas_de_coerencia_interna,
    ref_por_id,
)
from ottima_core.portability.schemas import (
    SCHEMA_VERSION,
    BundleConnection,
    BundleFlow,
    BundleProject,
    BundleTag,
    BundleTagRef,
    ProjectBundle,
)
from ottima_core.portability.tag_ref import (
    TAG_REF_FIELDS,
    ReferenciaTagInvalida,
    grafo_para_banco,
    grafo_para_bundle,
    problemas_de_tag_ref,
)

__all__ = [
    "SCHEMA_VERSION",
    "BundleConnection",
    "BundleFlow",
    "BundleProject",
    "BundleTag",
    "BundleTagRef",
    "ProjectBundle",
    "TAG_REF_FIELDS",
    "ReferenciaTagInvalida",
    "grafo_para_banco",
    "grafo_para_bundle",
    "problemas_de_tag_ref",
    "montar_bundle",
    "problemas_de_coerencia_interna",
    "ref_por_id",
]
