# ADR-002 — Barramento interno via Redis pub/sub

**Status:** Aceito · 2026-08-03

## Contexto
Requisito explícito: o worker OPC publica leituras num barramento interno e os demais workers consomem. Produtores e consumidores devem ser desacoplados; novos consumidores (recorder, runtime, WS) não podem exigir mudança no produtor.

## Decisão
**Redis pub/sub** como barramento interno. Canais de leitura (`opc.values.<conn_id>`) publicados pelo opc-worker; canal de escrita (`opc.writes`) consumido pelo opc-worker. Consumidores: flow-runtime, recorder, FastAPI (WS → frontend).

## Consequências
- (+) Desacoplamento por construção; adicionar consumidor = assinar canal.
- (+) Padrão de alta representação no treino de agentes de IA → código gerado confiável.
- (−) Pub/sub Redis é fire-and-forget (sem persistência/replay). Se um consumidor cair, perde mensagens do intervalo. Aceitável para dados cíclicos de processo; NÃO usar para comandos que exigem garantia de entrega sem confirmação adicional.
