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
| Plano de Curso | ✅ | Cronograma de Aulas + Avaliações (exam dates) via `get_course_plan` / `sigaa plan --class`. **No clock times on the page** — `SLOT_TIMES_UNCONFIRMED` stays unconfirmed. |
| Frequência | ✅ | Mapa de Frequências (per-date status + totals) via `get_attendance` / `sigaa attendance --class`. |
| Tarefas | 🟢 | Reachable (returns "Nenhum item foi encontrado" on the test turma). Parser pending real data. |
| Materiais (Tópicos de Aula) | ✅ | Uploaded files + external links are listed inline on the Principal page (`div.topico-aula` → `div.item`), no deep nav needed. File rows download via a `formAva` postback to `/sigaa/ava/index.jsf` (`list_materials` / `download_material` / `sigaa materials`). |
| Arquivos / Referências / Vídeos / Conteúdo (deep menu) | 🟢 | Reachable; files already surface via Materiais above. |
| Participantes / Situação dos Discentes | 🟢 | Reachable: professor + full roster (name, curso, matrícula, e-mail). Parser pending need. |
| Avaliações / Enquetes / Questionários / Fóruns | ⚪ | Not probed. |

### The bounce problem — RESOLVED (2026-06-11)
Deep `formMenu` items work with the current flow: a fresh `enter_turma` POST
followed by the `formMenu` postback built from that Principal page's decoded
anchor text (`find_menu_field`). The earlier "bounce" diagnosis was a false
positive: the literal "Selecione uma das turmas" string also appears in the
Principal sidebar, so substring checks misread valid pages as bounced. Verified
live: Tarefas, Plano de Curso, Frequência, and Participantes all render real
content. Caveat: reuse one Principal page per postback — do not chain two deep
posts off the same cached `turma_html` without re-entering.

## Portal menu (`/sigaa/portais/discente/...`, sidebar postbacks)

| Item | Status | Notes |
|------|--------|-------|
| Minhas Notas (Relatório de Notas) | ✅ | All-semester grade tables. |
| Turma event cards (Avaliação/Atividade) | ✅ | Deadlines with stable ids. |
| Histórico acadêmico | ✅ | Full transcript as PDF (`get_historico_pdf` / `sigaa historico`). |
| Atestado de Matrícula | ✅ | Printable HTML enrollment certificate with official SIGAA assets (`sigaa atestado-matricula` / `sigaa_download_atestado_matricula`). |
| Meus Dados Pessoais | ⚪ | Profile fields. |
| Declaração de Vínculo | ✅ | Enrollment declaration as PDF (`sigaa declaracao-vinculo` / `sigaa_download_declaracao_vinculo`). |
| Ver Comprovante de Matrícula | ⚪ | Enrollment receipt. |
| Consultar Estrutura Curricular | ✅ | Progresso e componentes ao vivo via `get_curriculum_status`, `sigaa curriculum` e `sigaa_get_curriculum`. A visão padrão reúne matriculados + pendentes obrigatórios; optativas pendentes são opções, não componentes todos obrigatórios. |
| CRA | ✅ | Valor oficial extraído do histórico acadêmico via `get_cra`, `sigaa cra` e `sigaa_get_cra`; pode estar indisponível para um ingressante cujo histórico ainda não o informe. |

## Confirmed working endpoints (reference)

- Login: `POST /sigaa/logon.jsf`; enter portal via `GET /sigaa/portal/discente/`.
- Enter turma: `POST /sigaa/portais/discente/beta/discente.jsf` with `{form_id, field, idTurma, ViewState=j_id1}`.
- TV menu / news body: `POST /sigaa/ava/index.jsf` with `formMenu` or per-row form fields, `ViewState=j_id2`.
- Grades report: portal sidebar postback "Minhas Notas" → `tabelaRelatorio` per semester.
- Currículo: `GET /sigaa/portal/discente/integralizacao/` (entrada/redirecionamento) e depois `GET /sigaa/portal/discente/integralizacao/dados/` para o JSON.
- CRA: baixa o histórico acadêmico pelo postback JSF do portal e extrai localmente o valor oficial do PDF.

A resposta normalizada de currículo do CLI/MCP omite deliberadamente o
identificador interno do estudante no SIGAA (`idDiscente`).

## Recommended next order
1. ~~Histórico acadêmico~~ — ✅ done (PDF download).
2. ~~Fix the turma-frame load~~ — ✅ resolved (no fix needed; see bounce note above).
3. ~~Plano de Curso~~ — ✅ done (`sigaa plan --class`). Page has no clock times, so
   `SLOT_TIMES_UNCONFIRMED` needs another source (official UFPB slot table or a
   browser capture of the timetable widget).
4. ~~Atestado de Matrícula + Declaração de Vínculo~~ — ✅ done (native HTML + PDF downloads).
5. ~~Ver Notas (per-turma)~~ — ✅ done (`sigaa grades --class`).
6. **Tarefas parser** once a turma has real assignments (page reachable, currently empty).
7. **Participantes parser** if roster data becomes useful.
