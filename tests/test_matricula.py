from sigaa.parsers.matricula import parse_messages, parse_open_turmas, parse_request_number

PAGE = """
<table>
<tr><td>1º Nível</td></tr>
<tr><td><img src="/sigaa/img/graduacao/matriculas/matricula_permitida.png"/></td>
    <td>* ABC1234 - COMPONENTE UM (Obrig. Currículo)</td></tr>
<tr><td><input type="checkbox" name="selecaoTurmas" value="111" id="cc_1t_01s_1CHK'_temReservas'"/></td>
    <td>Turma 01</td><td>FULANO DE TAL</td><td>24M23</td><td>SALA 1</td><td>60 alunos</td></tr>
<tr><td><img src="/sigaa/img/graduacao/matriculas/matricula_negada.png"/></td>
    <td>* DEF5678 - COMPONENTE DOIS (Optativa)</td></tr>
<tr><td><input type="checkbox" name="selecaoTurmas" value="222" id="cc_2t_01s_1CHK"/></td>
    <td>Turma 02</td><td>BELTRANA DA SILVA</td><td>35T45</td><td>SALA 2</td><td>40 alunos</td></tr>
</table>
"""


def test_parse_open_turmas():
    turmas = {t.turma_id: t for t in parse_open_turmas(PAGE)}
    one, two = turmas["111"], turmas["222"]
    assert one.component_code == "ABC1234" and one.kind == "Obrig. Currículo"
    assert one.level == "1º" and one.allowed and one.has_reservation
    assert one.turma_label == "Turma 01" and one.teachers == "FULANO DE TAL"
    assert one.schedule_raw == "24M23" and one.capacity == "60 alunos"
    assert two.component_code == "DEF5678" and not two.allowed and not two.has_reservation
    assert two.schedule_raw == "35T45"


def test_parse_request_number():
    html = "<html><body>Solicitação de Matrícula N° 633511 Imprimir</body></html>"
    assert parse_request_number(html) == "633511"
    assert parse_request_number("<html><body>nada</body></html>") is None


def test_parse_messages_fallback():
    html = "<html><body>As seguintes turmas foram selecionadas com sucesso: X - Turma 01.</body></html>"
    assert any("selecionadas com sucesso" in m for m in parse_messages(html))
