import { expect, test } from "@playwright/test";

import type { LeituraTag } from "../../app/CanalAoVivo";
import { celulaOnline, tagIdsDeLeitura } from "./tagsOnline";

function leitura(parcial: Partial<LeituraTag> = {}): LeituraTag {
  return { v: 51.2, ts: "2026-08-04T12:00:00Z", quality: 0, ok: true, ...parcial };
}

// --- tagIdsDeLeitura ---

/** Monitored item é leitura (`subscriptions.py:147-150`) e o heartbeat só republica tag `r`
 *  (`heartbeat.py:108-109`): assinar uma tag `w` gastaria slot da fila do /ws (8, drop-oldest)
 *  por um valor que nunca chega. */
test("tagIdsDeLeitura devolve só as tags de leitura, na ordem da tabela", () => {
  const linhas = [
    { id: 7, direction: "r" as const },
    { id: 8, direction: "w" as const },
    { id: 9, direction: "r" as const },
  ];

  expect(tagIdsDeLeitura(linhas)).toEqual([7, 9]);
});

test("tagIdsDeLeitura sem nenhuma tag de leitura devolve vazio", () => {
  expect(tagIdsDeLeitura([{ id: 8, direction: "w" }])).toEqual([]);
});

// --- celulaOnline ---

test("leitura boa com socket aberto mostra o valor e a quality Boa", () => {
  expect(celulaOnline("r", leitura(), true)).toEqual({
    valor: "51,2",
    quality: "Boa",
    tone: "success",
  });
});

/** O caso que justifica carregar a quality inteira: incerta não é boa nem ruim. */
test("quality incerta (1) tem rótulo e tom próprios, distintos de ruim", () => {
  expect(celulaOnline("r", leitura({ quality: 1, ok: false }), true)).toEqual({
    valor: "51,2",
    quality: "Incerta",
    tone: "warn",
  });
});

/** Quality ruim NÃO apaga o número: o heartbeat republica o último valor conhecido sob
 *  `quality=2` (`heartbeat.py:92-105`) e a Regra do Canal Redundante manda comunicar a
 *  severidade ao lado do valor, não no lugar dele. */
test("quality ruim (2) mantém o último valor conhecido e marca alarme", () => {
  expect(celulaOnline("r", leitura({ quality: 2, ok: false }), true)).toEqual({
    valor: "51,2",
    quality: "Ruim",
    tone: "alarm",
  });
});

test("value null (falha de leitura no worker) zera o valor mas preserva a quality", () => {
  expect(celulaOnline("r", leitura({ v: null, quality: 2, ok: false }), true)).toEqual({
    valor: null,
    quality: "Ruim",
    tone: "alarm",
  });
});

/** `status_to_quality` fecha o contrato em 0/1/2 (reservado já vira 2): inteiro fora disso é
 *  worker fora do contrato — mostra o cru em vez de inventar rótulo, e trata como não-confiável. */
test("quality fora do contrato mostra o inteiro cru sob tom de alarme", () => {
  const celula = celulaOnline("r", leitura({ quality: 8, ok: false }), true);

  expect(celula.quality).toBe("8");
  expect(celula.tone).toBe("alarm");
});

test("tag de escrita não tem valor online: travessão nas duas colunas", () => {
  expect(celulaOnline("w", undefined, true)).toEqual({
    valor: null,
    quality: "—",
    tone: "neutral",
  });
});

test("tag de leitura que ainda não publicou fica em travessão, sem fingir dado", () => {
  expect(celulaOnline("r", undefined, true)).toEqual({
    valor: null,
    quality: "—",
    tone: "neutral",
  });
});

/** Socket caído congela `tagValues` no último lote: exibir aquele número como se fosse a
 *  leitura de agora é a falha perigosa desta tela — o travessão é o lado seguro. */
test("socket fora do ar descarta a leitura em mão em vez de exibir valor congelado", () => {
  expect(celulaOnline("r", leitura(), false)).toEqual({
    valor: null,
    quality: "—",
    tone: "neutral",
  });
});

test("inteiro e booleano usam o mesmo formato decimal do barramento (float coagido)", () => {
  expect(celulaOnline("r", leitura({ v: 1 }), true).valor).toBe("1");
  expect(celulaOnline("r", leitura({ v: 0 }), true).valor).toBe("0");
});
