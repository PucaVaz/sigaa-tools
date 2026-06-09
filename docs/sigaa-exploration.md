# SIGAA UFPB — feature exploration map

Survey of scrapeable surfaces beyond what's implemented, with verification status
against the live account (SIGAA v26.6.0, 2026-06). Use this to pick the next build.

## Status legend
- ✅ **implemented** — parser + client + store + surface, tested
- 🟢 **reachable** — endpoint hit, data confirmed, not yet wired into the package
- 🟡 **needs work** — navigation bounces to "Selecione uma das turmas"; flow gap
- ⚪ **untested** — link exists, not probed

## Turma Virtual menu (`/sigaa/ava/index.jsf`, `formMenu` postbacks)

| Item | Status | Notes |
|------|--------|-------|
| Principal | ✅ | Landing page from `enter_turma`. Hosts the Notícias panel. |
| Notícias | ✅ | List + per-row body (`get_news_body`). |
| Ver Notas | ✅ | Per-turma grade table (Unid.1..N, Exame, Resultado, Faltas, Sit.), linked to id_turma. `formMenu` postback to a standalone report; dodges the bounce by re-deriving the turma from its own report id. (`get_turma_grades` / `sigaa grades --class`). |
| Plano de Curso | 🟡 | Bounced. Would confirm the **slot→clock time table** (resolves `SLOT_TIMES_UNCONFIRMED`). High value. |
| Frequência | 🟡 | Menu-param matcher didn't resolve the link (entity-encoded text) + bounce. Attendance per class. |
| Tarefas | 🟡 | Bounced. Assignments with due dates + submission status. |
| Materiais (Tópicos de Aula) | ✅ | Uploaded files + external links are listed inline on the Principal page (`div.topico-aula` → `div.item`), no deep nav needed. File rows download via a `formAva` postback to `/sigaa/ava/index.jsf` (`list_materials` / `download_material` / `sigaa materials`). |
| Arquivos / Referências / Vídeos / Conteúdo (deep menu) | 🟡 | Dedicated menu pages still bounce, but their files already surface via Materiais above. |
| Participantes / Situação dos Discentes | 🟡 | Bounced. Roster. |
| Avaliações / Enquetes / Questionários / Fóruns | ⚪ | Not probed. |

### The bounce problem (next reverse-engineering task)
Deep `formMenu` items return the turma-selection page even with a fresh
`enter_turma` and with `idTurma`/`id` re-asserted in the POST. The Principal
page carries a "Por favor, aguarde enquanto carregamos a página…" notice —
strong sign there is a **follow-up request that loads the turma frame and sets
the AVA session's current turma**, which we skip. `Ver Notas` works because it
renders a standalone printable report that re-derives the turma from its own id.

**Fix approach:** capture a real browser navigation (DevTools → Network) for one
deep item (e.g. Tarefas) to see the exact request sequence after entering a
turma — likely a GET to `/sigaa/ava/index.jsf` (or a `?...` frame URL) that
primes the session before the `formMenu` POST works. Replicate that GET in
`enter_turma`, then the existing menu-post helper should unlock all deep items.

## Portal menu (`/sigaa/portais/discente/...`, sidebar postbacks)

| Item | Status | Notes |
|------|--------|-------|
| Minhas Notas (Relatório de Notas) | ✅ | All-semester grade tables. |
| Turma event cards (Avaliação/Atividade) | ✅ | Deadlines with stable ids. |
| Histórico acadêmico | ✅ | Full transcript as PDF (`get_historico_pdf` / `sigaa historico`). |
| Atestado de Matrícula | 🟢 | HTML enrollment proof (nível, vínculo, curso, turmas). Easy parse. |
| Meus Dados Pessoais | ⚪ | Profile fields. |
| Declaração de Vínculo | ⚪ | Printable doc. |
| Ver Comprovante de Matrícula | ⚪ | Enrollment receipt. |
| Consultar Estrutura Curricular | ⚪ | Curriculum + pending CH (progress already on portal header). |

## Confirmed working endpoints (reference)

- Login: `POST /sigaa/logon.jsf`; enter portal via `GET /sigaa/portal/discente/`.
- Enter turma: `POST /sigaa/portais/discente/beta/discente.jsf` with `{form_id, field, idTurma, ViewState=j_id1}`.
- TV menu / news body: `POST /sigaa/ava/index.jsf` with `formMenu` or per-row form fields, `ViewState=j_id2`.
- Grades report: portal sidebar postback "Minhas Notas" → `tabelaRelatorio` per semester.

## Recommended next order
1. ~~Histórico acadêmico~~ — ✅ done (PDF download).
2. **Fix the turma-frame load** in `enter_turma` — unlocks Tarefas, Arquivos, Frequência, Participantes, Plano de Curso at once. The single biggest lever.
3. **Plano de Curso** (after #2) → confirm `SLOT_TIMES_UNCONFIRMED`, making ICS class times trustworthy.
4. **Atestado de Matrícula** → parse the HTML enrollment proof (🟢, low effort).
5. ~~Ver Notas (per-turma)~~ — ✅ done (`sigaa grades --class`).
