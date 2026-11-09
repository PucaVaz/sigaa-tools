"""The extension selection flow: parsers, client, session encoding, CLI and MCP."""

import json
import secrets
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from sigaa import cli as cli_module
from sigaa.client import SigaaClient
from sigaa.errors import NavigationError, ParseError, UnrecognizedPageError, error_stage
from sigaa.extensao import filter_opportunities
from sigaa.http import Session, encode_form
from sigaa.institutions import Capability, get
from sigaa.parsers import selecao_extensao as parser

FIXTURES = Path(__file__).parent / "fixtures"


def _page(name: str) -> str:
    return (FIXTURES / f"selecao_extensao_{name}.html").read_text(encoding="utf-8")


SEARCH_PAGE = _page("busca")
RESULTS_PAGE = _page("resultados")
EMPTY_PAGE = _page("vazio")
CHANGED_PAGE = _page("layout_alterado")
FORM_PAGE = _page("inscricao")
SUCCESS_PAGE = _page("sucesso")
REFUSAL_PAGE = _page("recusa")

SEARCH_URL = "https://sigaa.ufpb.br/sigaa/graduacao/agregador_bolsa/busca.jsf"
FORM_URL = "https://sigaa.ufpb.br/sigaa/extensao/DiscenteExtensao/inscricao_discente.jsf"
TRILHA_ID = "16743"
TRILHA_TITLE = (
    "TRILHA – UFPB: FORMAÇÃO TÉCNICA, MENTORIA E PROTAGONISMO ESTUDANTIL EM COMPUTAÇÃO"
    " - Etapa 2026-2027"
)
CLOSED_ID = "15720"
QUALIFICATIONS = "Experiência em programação e monitoria de Cálculo – 2º período"
QUALIFICATIONS_FIELD = "j_id_jsp_956955954_1:qualificacoes_dados_aluno"
LATTES_FIELD = "j_id_jsp_956955954_1:lattes_dados_aluno"
ALREADY_REGISTERED = (
    "Você já realizou a inscrição para esta ação de extensão, portanto não pode realizar novamente."
)
TEST_PASSWORD = secrets.token_urlsafe(16)


class TestSearchPostback:
    def test_selects_the_extension_type_and_keeps_the_form_defaults(self):
        action, fields = parser.build_search_postback(SEARCH_PAGE)

        assert action == "/sigaa/graduacao/agregador_bolsa/busca.jsf"
        assert fields == {
            "busca": "busca",
            "busca:idServidor": "0",
            "javax.faces.ViewState": "j_id2",
            "busca:buscaAnoAtividade": "2026",
            "busca:nome": "",
            "busca:tipo": "2",
            "busca:tipoAtividade": "3",
            "busca:centro": "1632",
            "busca:btaoBuscar": "Buscar",
        }

    def test_year_replaces_the_prefilled_one(self):
        _, fields = parser.build_search_postback(SEARCH_PAGE, 2025)

        assert fields["busca:buscaAnoAtividade"] == "2025"

    def test_a_page_without_the_search_form_is_unrecognized(self):
        with pytest.raises(UnrecognizedPageError):
            parser.build_search_postback(SUCCESS_PAGE)

    def test_a_search_form_without_the_extension_type_is_unrecognized(self):
        page = SEARCH_PAGE.replace('<option value="2">EXTENS&#195;O</option>', "")

        with pytest.raises(UnrecognizedPageError):
            parser.build_search_postback(page)


class TestOpportunities:
    def test_parses_every_row(self):
        opportunities = parser.parse_opportunities(RESULTS_PAGE)

        assert [o.opportunity_id for o in opportunities] == ["14225", "15658", CLOSED_ID, TRILHA_ID]
        trilha = opportunities[-1]
        assert trilha.title == TRILHA_TITLE
        assert trilha.paid_slots == 1
        assert trilha.coordinator is None
        assert trilha.unit == "CI - DEPARTAMENTO DE COMPUTAÇÃO CIENTÍFICA"
        assert trilha.unit_code == "CI-DCC"
        assert trilha.can_apply is True

    def test_a_row_without_the_selection_link_cannot_be_applied_to(self):
        closed = next(
            o for o in parser.parse_opportunities(RESULTS_PAGE) if o.opportunity_id == CLOSED_ID
        )

        assert closed.can_apply is False

    def test_empty_only_when_sigaa_says_so(self):
        assert parser.parse_opportunities(EMPTY_PAGE) == []

    def test_the_untouched_search_form_is_not_an_empty_result(self):
        with pytest.raises(UnrecognizedPageError):
            parser.parse_opportunities(SEARCH_PAGE)

    def test_a_changed_results_table_is_unrecognized(self):
        with pytest.raises(UnrecognizedPageError):
            parser.parse_opportunities(CHANGED_PAGE)

    def test_a_row_without_an_id_fails_the_whole_page(self):
        page = RESULTS_PAGE.replace("'id':'14225'", "'other':'14225'").replace(
            "'idOportunidade':'14225'", "'other':'14225'"
        )

        with pytest.raises(UnrecognizedPageError):
            parser.parse_opportunities(page)

    def test_an_auth_redirect_is_a_parse_failure(self):
        with pytest.raises(ParseError) as caught:
            parser.parse_opportunities((FIXTURES / "auth_redirect.html").read_text())

        assert error_stage(caught.value) == "parse"

    def test_filter_matches_every_word_ignoring_case_and_accents(self):
        opportunities = parser.parse_opportunities(RESULTS_PAGE)

        assert [o.opportunity_id for o in filter_opportunities(opportunities, "trilha")] == [
            "15658", CLOSED_ID, TRILHA_ID,
        ]
        assert [
            o.opportunity_id for o in filter_opportunities(opportunities, "formacao TRILHA")
        ] == [TRILHA_ID]
        assert len(filter_opportunities(opportunities, None)) == 4


class TestApplyPostback:
    def test_replays_the_row_link(self):
        action, fields = parser.build_apply_postback(RESULTS_PAGE, TRILHA_ID)

        link = "listagemResultado:cadastrarInteresseParticipacaoExtensaoj_id_1001"
        assert action == "/sigaa/graduacao/agregador_bolsa/busca.jsf"
        assert fields == {
            "listagemResultado": "listagemResultado",
            "javax.faces.ViewState": "j_id3",
            link: link,
            "idTipoBolsa": "2",
            "idOportunidade": TRILHA_ID,
            "idUsuario": "0",
        }

    @pytest.mark.parametrize("opportunity_id", [CLOSED_ID, "99999"])
    def test_an_opportunity_without_a_selection_link_is_a_navigation_error(self, opportunity_id):
        with pytest.raises(NavigationError, match="not open for selection"):
            parser.build_apply_postback(RESULTS_PAGE, opportunity_id)


class TestSelectionForm:
    def test_describes_the_action(self):
        form = parser.parse_selection_form(FORM_PAGE)

        assert form.opportunity_id == TRILHA_ID
        assert form.title == TRILHA_TITLE
        assert form.action_code == "PJ823-2026"
        assert form.coordinator == "TATIANA ARAUJO SIMOES"
        assert form.kind == "PROJETO"
        assert form.unit == "CI - DEPARTAMENTO DE COMPUTAÇÃO CIENTÍFICA"
        assert form.funding.startswith("FINANCIAMENTO INTERNO")

    def test_never_returns_the_student_contact_details(self):
        described = json.dumps(vars(parser.parse_selection_form(FORM_PAGE)))

        assert "fulano" not in described
        assert "00000" not in described

    def test_a_refusal_carries_sigaa_messages(self):
        with pytest.raises(parser.SelectionRejectedError, match="já realizou a inscrição"):
            parser.parse_selection_form(REFUSAL_PAGE)

    def test_any_other_page_is_unrecognized(self):
        with pytest.raises(UnrecognizedPageError):
            parser.parse_selection_form(SEARCH_PAGE)

    def test_registration_postback_presses_only_the_register_button(self):
        action, fields = parser.build_registration_postback(FORM_PAGE, QUALIFICATIONS, None)

        assert action == "/sigaa/extensao/DiscenteExtensao/inscricao_discente.jsf"
        assert fields == {
            "j_id_jsp_956955954_1": "j_id_jsp_956955954_1",
            "id": TRILHA_ID,
            "javax.faces.ViewState": "j_id4",
            QUALIFICATIONS_FIELD: QUALIFICATIONS,
            LATTES_FIELD: "",
            "j_id_jsp_956955954_1:j_id_jsp_956955954_22": "Registrar-se como Interessado",
        }


class TestRegistrationResult:
    def test_success_alert_is_registered_and_masks_the_email(self):
        result = parser.parse_registration_result(SUCCESS_PAGE)

        assert result.status == parser.STATUS_REGISTERED
        assert result.messages == [
            "Operação realizada com sucesso. E-mail de confirmação enviado para: [e-mail]"
        ]

    def test_error_alert_is_rejected(self):
        result = parser.parse_registration_result(REFUSAL_PAGE)

        assert result.status == parser.STATUS_REJECTED
        assert result.messages == [ALREADY_REGISTERED]

    def test_a_page_without_any_alert_is_never_reported_as_registered(self):
        result = parser.parse_registration_result(FORM_PAGE)

        assert result.status == parser.STATUS_UNCONFIRMED
        assert result.messages == []


class TestFormEncoding:
    def test_encodes_text_in_the_institution_charset(self):
        body = encode_form({"field": "período º – ção", "many": ["1", "2"]}, "cp1252")

        assert body == b"field=per%EDodo+%BA+%96+%E7%E3o&many=1&many=2"

    def test_refuses_text_the_charset_cannot_represent(self):
        with pytest.raises(ValueError, match="cannot store"):
            encode_form({"field": "ok 🙂"}, "cp1252")

    def test_session_posts_the_encoded_body_only_when_a_charset_is_given(self):
        seen = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append((request.headers["content-type"], request.content))
            return httpx.Response(200, text="Sair do SIGAA")

        provider = get("ufpb")
        session = Session(
            "aluno.teste",
            TEST_PASSWORD,
            client=httpx.Client(transport=httpx.MockTransport(handler)),
            profile=provider.profile,
            navigator=provider.navigator,
        )
        session._authenticated = True

        session.post(FORM_URL, {"field": "ção"}, charset="cp1252")
        session.post(FORM_URL, {"field": "ção"})

        assert seen == [
            ("application/x-www-form-urlencoded", b"field=%E7%E3o"),
            ("application/x-www-form-urlencoded", b"field=%C3%A7%C3%A3o"),
        ]


class _ScriptedSession:
    """Answers each POST with the next scripted page and records the request."""

    def __init__(self, *pages: str):
        self.pages = list(pages)
        self.posts: list[tuple[str, dict, str | None]] = []

    def post(self, url, data, *, charset=None):
        self.posts.append((url, data, charset))
        return self.pages.pop(0)


def _client(*pages: str) -> SigaaClient:
    client = object.__new__(SigaaClient)
    client.profile = get("ufpb").profile
    client._session = _ScriptedSession(*pages)
    client.clicked = []

    def menu_post(label):
        client.clicked.append(label)
        return SEARCH_PAGE

    client._portal_menu_post = menu_post
    return client


class TestClient:
    def test_ufpb_declares_the_capability_and_its_form_charset(self):
        profile = get("ufpb").profile

        assert Capability.EXTENSION_SELECTION in profile.capabilities
        assert profile.form_charset == "cp1252"

    @pytest.mark.parametrize("institution", ["ufcg", "ufg"])
    def test_other_institutions_do_not_offer_it(self, institution):
        assert Capability.EXTENSION_SELECTION not in get(institution).profile.capabilities

    def test_lists_opportunities_through_the_portal_menu(self):
        client = _client(RESULTS_PAGE)

        opportunities = client.list_extension_opportunities(2026)

        assert client.clicked == ["Inscrever-se em Seleção de Projeto de Ensino"]
        assert len(opportunities) == 4
        url, fields, charset = client._session.posts[0]
        assert url == SEARCH_URL
        assert fields["busca:tipo"] == "2"
        assert charset is None

    def test_opening_a_selection_submits_nothing(self):
        client = _client(RESULTS_PAGE, FORM_PAGE)

        form = client.describe_extension_selection(client.open_extension_selection(TRILHA_ID))

        assert form.title == TRILHA_TITLE
        assert [url for url, _, _ in client._session.posts] == [SEARCH_URL, SEARCH_URL]

    def test_registers_with_the_text_in_the_institution_charset(self):
        client = _client(SUCCESS_PAGE)

        result = client.register_extension_interest(FORM_PAGE, f"  {QUALIFICATIONS}  ")

        assert result.status == parser.STATUS_REGISTERED
        url, fields, charset = client._session.posts[0]
        assert url == FORM_URL
        assert fields[QUALIFICATIONS_FIELD] == QUALIFICATIONS
        assert fields[LATTES_FIELD] == ""
        assert charset == "cp1252"

    def test_blank_qualifications_never_reach_sigaa(self):
        client = _client(SUCCESS_PAGE)

        with pytest.raises(ValueError, match="qualifications"):
            client.register_extension_interest(FORM_PAGE, "   ")

        assert client._session.posts == []


def _settings():
    return SimpleNamespace(
        institution="ufpb",
        username="configured-user",
        resolve_password=lambda: TEST_PASSWORD,
    )


def _fake_client(calls: list, failure: Exception | None = None, receipt: str = SUCCESS_PAGE):
    class FakeClient:
        def __init__(self, username, password, **kwargs):
            assert (username, password) == ("configured-user", TEST_PASSWORD)
            calls.append(("timeout", kwargs["timeout"]))

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return None

        def list_extension_opportunities(self, year=None):
            if failure is not None:
                raise failure
            calls.append(("list", year))
            return parser.parse_opportunities(RESULTS_PAGE)

        def open_extension_selection(self, opportunity_id, year=None):
            if failure is not None:
                raise failure
            calls.append(("open", opportunity_id, year))
            return FORM_PAGE

        def describe_extension_selection(self, selection_html):
            return parser.parse_selection_form(selection_html)

        def register_extension_interest(self, selection_html, qualifications, lattes_url=None):
            calls.append(("register", qualifications, lattes_url))
            return parser.parse_registration_result(receipt)

    return FakeClient


def _run_cli(monkeypatch, argv, **fake):
    calls: list = []
    monkeypatch.setattr(cli_module, "SigaaClient", _fake_client(calls, **fake))
    args = cli_module._build_parser().parse_args(["selecao-extensao", *argv])
    return cli_module._cmd_selecao_extensao(args, _settings()), calls


class TestCli:
    def test_command_declares_its_capability(self):
        args = cli_module._build_parser().parse_args(["selecao-extensao"])

        assert args.func is cli_module._cmd_selecao_extensao
        assert args.capability is Capability.EXTENSION_SELECTION

    def test_search_json_uses_the_shared_contract(self, monkeypatch, capsys):
        code, calls = _run_cli(monkeypatch, ["--search", "trilha ufpb", "--year", "2026", "--json"])

        data = json.loads(capsys.readouterr().out)
        assert code == 0
        assert ("list", 2026) in calls
        assert ("timeout", 240.0) in calls
        assert (data["query"], data["listed"], data["matched"]) == ("trilha ufpb", 4, 1)
        assert data["opportunities"] == [
            {
                "opportunity_id": TRILHA_ID,
                "title": TRILHA_TITLE,
                "paid_slots": 1,
                "coordinator": None,
                "unit": "CI - DEPARTAMENTO DE COMPUTAÇÃO CIENTÍFICA",
                "unit_code": "CI-DCC",
                "can_apply": True,
            }
        ]

    def test_human_listing_marks_closed_selections(self, monkeypatch, capsys):
        code, _ = _run_cli(monkeypatch, ["--search", "trilhas"])

        captured = capsys.readouterr()
        assert code == 0
        assert f"{CLOSED_ID} closed" in captured.out
        assert "1 of 4 opportunities" in captured.err

    def test_apply_without_confirm_only_previews(self, monkeypatch, capsys):
        code, calls = _run_cli(monkeypatch, ["--apply", TRILHA_ID])

        output = capsys.readouterr().out
        assert code == 0
        assert not [call for call in calls if call[0] == "register"]
        assert f"PJ823-2026 - {TRILHA_TITLE}" in output
        assert "nothing submitted" in output

    def test_confirm_registers_and_reports_sigaa_answer(self, monkeypatch, capsys):
        code, calls = _run_cli(
            monkeypatch,
            ["--apply", TRILHA_ID, "--qualifications", QUALIFICATIONS, "--confirm", "--json"],
        )

        data = json.loads(capsys.readouterr().out)
        assert code == 0
        assert ("register", QUALIFICATIONS, None) in calls
        assert (data["submitted"], data["status"]) == (True, "registered")
        assert data["action"]["action_code"] == "PJ823-2026"
        assert "[e-mail]" in data["messages"][0]

    def test_a_refused_registration_exits_nonzero(self, monkeypatch, capsys):
        code, _ = _run_cli(
            monkeypatch,
            ["--apply", TRILHA_ID, "--qualifications", QUALIFICATIONS, "--confirm"],
            receipt=REFUSAL_PAGE,
        )

        assert code == 1
        assert "status: rejected" in capsys.readouterr().out

    def test_an_unconfirmed_registration_exits_nonzero(self, monkeypatch, capsys):
        code, _ = _run_cli(
            monkeypatch,
            ["--apply", TRILHA_ID, "--qualifications", QUALIFICATIONS, "--confirm"],
            receipt=FORM_PAGE,
        )

        assert code == 1
        assert "without a confirmation" in capsys.readouterr().out

    @pytest.mark.parametrize("argv, problem", [
        (["--confirm"], "--confirm requires --apply"),
        (["--apply", TRILHA_ID, "--confirm"], "--confirm requires --qualifications"),
    ])
    def test_confirm_needs_a_target_and_a_text(self, monkeypatch, capsys, argv, problem):
        code, calls = _run_cli(monkeypatch, argv)

        assert code == 1
        assert calls == []
        assert problem in capsys.readouterr().err

    def test_parse_failure_exits_nonzero(self, monkeypatch, capsys):
        failure = UnrecognizedPageError("extension_opportunities", {})
        code, _ = _run_cli(monkeypatch, ["--json"], failure=failure)

        captured = capsys.readouterr()
        assert code == 1
        assert captured.out == ""
        assert "unrecognized extension_opportunities page" in captured.err


class TestMcpTools:
    @pytest.fixture(autouse=True)
    def _mcp(self, monkeypatch):
        pytest.importorskip("mcp")
        from sigaa import mcp_server

        self.mcp_server = mcp_server
        self.calls: list = []
        monkeypatch.setattr(mcp_server, "Settings", _settings)

    def _fake(self, monkeypatch, **fake):
        monkeypatch.setattr(self.mcp_server, "SigaaClient", _fake_client(self.calls, **fake))

    def test_tools_are_registered_and_kept_in_hosted_mode(self):
        from sigaa.config import HOSTED_MODE

        names = {"sigaa_search_extension_opportunities", "sigaa_apply_extension_selection"}
        assert names <= set(self.mcp_server.mcp._tool_manager._tools)
        assert names.isdisjoint(self.mcp_server.hidden_tools_for_mode(HOSTED_MODE))

    def test_search_filters_by_title(self, monkeypatch):
        self._fake(monkeypatch)

        data = self.mcp_server.sigaa_search_extension_opportunities("trilha ufpb")

        assert (data["listed"], data["matched"]) == (4, 1)
        assert data["opportunities"][0]["opportunity_id"] == TRILHA_ID

    def test_search_requires_a_query(self, monkeypatch):
        from mcp.server.fastmcp.exceptions import ToolError

        self._fake(monkeypatch)

        with pytest.raises(ToolError, match="query is required"):
            self.mcp_server.sigaa_search_extension_opportunities("  ")
        assert self.calls == []

    def test_apply_defaults_to_a_preview(self, monkeypatch):
        self._fake(monkeypatch)

        data = self.mcp_server.sigaa_apply_extension_selection(TRILHA_ID, QUALIFICATIONS)

        assert (data["submitted"], data["status"]) == (False, "preview")
        assert data["action"]["coordinator"] == "TATIANA ARAUJO SIMOES"
        assert not [call for call in self.calls if call[0] == "register"]

    def test_apply_with_confirm_registers(self, monkeypatch):
        self._fake(monkeypatch)

        data = self.mcp_server.sigaa_apply_extension_selection(
            TRILHA_ID, QUALIFICATIONS, year=2026, confirm=True
        )

        assert ("open", TRILHA_ID, 2026) in self.calls
        assert ("register", QUALIFICATIONS, None) in self.calls
        assert data["status"] == "registered"

    def test_confirm_without_qualifications_is_refused_before_any_request(self, monkeypatch):
        from mcp.server.fastmcp.exceptions import ToolError

        self._fake(monkeypatch)

        with pytest.raises(ToolError, match="qualifications text is required"):
            self.mcp_server.sigaa_apply_extension_selection(TRILHA_ID, confirm=True)
        assert self.calls == []

    def test_a_live_failure_is_a_tool_error(self, monkeypatch):
        from mcp.server.fastmcp.exceptions import ToolError

        self._fake(monkeypatch, failure=NavigationError("not open for selection"))

        with pytest.raises(ToolError, match="not open for selection"):
            self.mcp_server.sigaa_apply_extension_selection(TRILHA_ID)

    def test_requires_credentials(self, monkeypatch):
        from mcp.server.fastmcp.exceptions import ToolError

        settings = SimpleNamespace(institution="ufpb", username=None, resolve_password=lambda: None)
        monkeypatch.setattr(self.mcp_server, "Settings", lambda: settings)

        with pytest.raises(ToolError, match="no credentials"):
            self.mcp_server.sigaa_search_extension_opportunities("trilha")
