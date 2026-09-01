from ottima_core.models import Base


def test_metadata_tem_todas_as_tabelas_relacionais():
    assert set(Base.metadata.tables) == {
        "users",
        "projects",
        "opc_connections",
        "tags",
        "calculated_tags",
        "calculated_tag_inputs",
        "flows",
        "mpc_setpoints",
        "loop_setpoints",
        "history_retention_settings",
        "system_settings",
    }


def test_indice_parcial_unico_de_projeto_ativo_declarado():
    idx = {i.name: i for i in Base.metadata.tables["projects"].indexes}
    assert "uq_projects_single_active" in idx
    assert idx["uq_projects_single_active"].unique is True
