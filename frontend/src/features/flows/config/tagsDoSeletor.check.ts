import { expect, test } from "@playwright/test";

import type { TagOut } from "../../../lib/api";
import { sufixoDirecao, tagsDoSeletor } from "./tagsDoSeletor";

function tag(parcial: Partial<TagOut> = {}): TagOut {
  return {
    id: 1,
    connection_id: 10,
    name: "MV-101",
    node_id: "ns=2;s=MV101",
    project_id: null,
    direction: "r",
    data_type: "float",
    eu: "%",
    description: "",
    created_at: "2026-09-29T12:00:00Z",
    updated_at: "2026-09-29T12:00:00Z",
    ...parcial,
  };
}

const LEITURA = tag({ id: 1, direction: "r" });
const ESCRITA = tag({ id: 2, direction: "w" });

test("seletor de leitura oferece tags r e w (readback do último valor escrito)", () => {
  expect(tagsDoSeletor([LEITURA, ESCRITA], "r")).toEqual([LEITURA, ESCRITA]);
});

test("seletor de escrita segue restrito a tags w", () => {
  expect(tagsDoSeletor([LEITURA, ESCRITA], "w")).toEqual([ESCRITA]);
});

test("tag de escrita ganha sufixo só no seletor de leitura", () => {
  expect(sufixoDirecao(ESCRITA, "r")).toBe(" · Escrita");
  expect(sufixoDirecao(ESCRITA, "w")).toBe("");
  expect(sufixoDirecao(LEITURA, "r")).toBe("");
});
