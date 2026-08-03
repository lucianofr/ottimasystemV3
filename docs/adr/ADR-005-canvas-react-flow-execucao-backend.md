# ADR-005 — Canvas com React Flow; execução 100% no backend

**Status:** Aceito · 2026-08-03

## Contexto
Requisito: canvas onde o admin arrasta blocos (OPC-Read, OPC-Write, MPC, Python-Script) e conecta lógicas. É preciso decidir onde o grafo executa.

## Decisão
Editor com **React Flow (@xyflow/react)**; cada tipo de bloco é um custom node. O grafo é serializado como JSON e persistido no Postgres. **O frontend apenas edita o grafo; a execução é exclusivamente no flow-runtime (backend).**

## Consequências
- (+) React Flow é a lib de node editors com maior representação no treino → nós customizados, handles tipados e validação de conexão gerados com pouco erro.
- (+) Execução determinística no servidor, independente de navegador aberto.
- (−) Exige um interpretador de grafo no backend (ordenação topológica, tipagem de sinais) — componente central a especificar no PRD.
