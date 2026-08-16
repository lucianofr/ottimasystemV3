# Report Registry

**Last Updated:** 2026-08-15

> Central index of agent work. Check here before starting new work.

---

## YYYY-MM-DD

<!-- Format: - report-name | Status | One-line summary -->
<!-- Example: - review-auth-timeout-20251228 | Completed | Root cause and fix plan -->

## 2026-08-06

- review-spec-f5-operacao-20260806 | Completed | APPROVE WITH CHANGES — spec F5 @7899a6f: 6 Critical, 10 Important, 11 Minor; 3 Critical tocam o próprio aceite da fase

## 2026-08-07

- review-spec-f6-consolidado-20260807 | Completed | **REQUEST CHANGES** — spec F6 @da25cd6, 7 facetes em paralelo: 74 achados brutos (15 Critical), 68 após dedup; 4 exigem decisão do dono (A-8 bloqueada, RF-102 sem emenda, ADR-018, RNF-07)
- review-spec-f6-normativa-20260807 | Completed | REQUEST CHANGES (rfc) — 4C/6I/6m; RFC-03: aceite depende de ampliação não emendada do RF-102
- review-spec-f6-fatos-20260807 | Completed | REQUEST CHANGES (scout) — 75 âncoras verificadas uma a uma, 1C/4I/8m; FACT-03: §5.2-2 omite `detach_hosts`, risco de escrita em planta
- review-spec-f6-api-20260807 | Completed | REQUEST CHANGES (fastapi-reviewer) — 3C/4I/3m; API-01: o bundle normativo da spec não é importável pela regra da própria spec
- review-spec-f6-frontend-20260807 | Completed | REQUEST CHANGES (react-reviewer) — 4C/3I/1m; `api()` não suporta download autenticado nem upload binário
- review-spec-f6-testes-20260807 | Completed | REQUEST CHANGES (pr-test-analyzer) — 3C/4I/2m; A-8 inviável: `grafo_mpc_tfs` é hardcoded e o TFS é travado em 2x2. Falso-verde do E2E-F6-02 descartado com evidência
- review-spec-f6-ux-20260807 | Completed | APPROVE WITH CHANGES (ux-designer) — 0C/10I/2m; UX-06: `node_id` contém `;`, separador do 422 agregado é ambíguo
- review-spec-f6-seguranca-20260807 | Completed | APPROVE WITH CHANGES (security-reviewer) — 0C/6I/0m; SEC-01: import quebra a premissa de confiança do ADR-018. Gerou TD-001 e TD-002

## 2026-08-15

- arch-review-20260815 | Completed | Auditoria de arquitetura @e38f528, 7 fatias em paralelo: 22 candidatos de aprofundamento (12 Strong, 10 Worth exploring), 0 contradizendo ADR. ARCH-07 é defeito latente verificado — fixture de retrocompat usa `du_max` (chave sem leitor) e nunca assere `max_rate`, então regresso que zere a taxa máxima de MV passa verde. Gerou TD-015 a TD-024

---

## Archive

Older entries are moved to: `reports/archive/_registry-archive.md`

