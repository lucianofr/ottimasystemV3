import { expect, test } from "@playwright/test";

import type { LeituraTag } from "../../app/CanalAoVivo";
import { celulaOnline } from "./tagsOnline";

function leitura(parcial: Partial<LeituraTag> = {}): LeituraTag {
  return { v: 51.2, ts: "2026-08-04T12:00:00Z", quality: 0, ok: true, ...parcial };
}

test("leitura boa com socket aberto mostra o valor e a quality Boa", () => {
  expect(celulaOnline(leitura(), true)).toEqual({
    valor: "51,2",
    quality: "Boa",
    tone: "success",
  });
});

/** O caso que justifica carregar a quality inteira: incerta não é boa nem ruim. */
test("quality incerta (1) tem rótulo e tom próprios, distintos de ruim", () => {
  expect(celulaOnline(leitura({ quality: 1, ok: false }), true)).toEqual({
    valor: "51,2",
    quality: "Incerta",
    tone: "warn",
  });
});

/** Quality ruim NÃO apaga o número: o heartbeat republica o último valor conhecido sob
 *  `quality=2` (`heartbeat.py:92-105`) e a Regra do Canal Redundante manda comunicar a
 *  severidade ao lado do valor, não no lugar dele. */
test("quality ruim (2) mantém o último valor conhecido e marca alarme", () => {
  expect(celulaOnline(leitura({ quality: 2, ok: false }), true)).toEqual({
    valor: "51,2",
    quality: "Ruim",
    tone: "alarm",
  });
});

test("value null (falha de leitura no worker) zera o valor mas preserva a quality", () => {
  expect(celulaOnline(leitura({ v: null, quality: 2, ok: false }), true)).toEqual({
    valor: null,
    quality: "Ruim",
    tone: "alarm",
  });
});

/** `status_to_quality` fecha o contrato em 0/1/2 (reservado já vira 2): inteiro fora disso é
 *  worker fora do contrato — mostra o cru em vez de inventar rótulo, e trata como não-confiável. */
test("quality fora do contrato mostra o inteiro cru sob tom de alarme", () => {
  const celula = celulaOnline(leitura({ quality: 8, ok: false }), true);

  expect(celula.quality).toBe("8");
  expect(celula.tone).toBe("alarm");
});

/** Direção NÃO é critério: o worker assina todo node que o servidor declara legível, inclusive
 *  o de uma tag `w` — e o valor dela é o comando em vigor. Quem fica sem série é o comando
 *  write-only, e isso chega aqui como ausência de leitura, testada logo abaixo. */
test("leitura de uma tag de escrita aparece igual à de uma tag de leitura", () => {
  expect(celulaOnline(leitura({ v: 100 }), true)).toEqual({
    valor: "100",
    quality: "Boa",
    tone: "success",
  });
});

test("tag sem leitura no espelho (write-only ou ainda calada) fica em travessão", () => {
  expect(celulaOnline(undefined, true)).toEqual({
    valor: null,
    quality: "—",
    tone: "neutral",
  });
});

/** Socket caído congela `tagValues` no último lote: exibir aquele número como se fosse a
 *  leitura de agora é a falha perigosa desta tela — o travessão é o lado seguro. */
test("socket fora do ar descarta a leitura em mão em vez de exibir valor congelado", () => {
  expect(celulaOnline(leitura(), false)).toEqual({
    valor: null,
    quality: "—",
    tone: "neutral",
  });
});

test("inteiro e booleano usam o mesmo formato decimal do barramento (float coagido)", () => {
  expect(celulaOnline(leitura({ v: 1 }), true).valor).toBe("1");
  expect(celulaOnline(leitura({ v: 0 }), true).valor).toBe("0");
});
