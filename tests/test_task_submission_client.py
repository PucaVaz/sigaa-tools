from pathlib import Path
from types import SimpleNamespace

from sigaa.client import SigaaClient


FIXTURES = Path(__file__).parent / "fixtures"
TAREFA = (FIXTURES / "tarefa.html").read_text(encoding="utf-8")


def test_submit_tarefa_posts_selected_file_to_the_task_form(tmp_path):
    upload = tmp_path / "solucao.zip"
    upload.write_bytes(b"solution")
    page = TAREFA.replace(
        '    </form>',
        '    <input name="formResponder:enviar" type="submit" value="Enviar tarefa"/>\n    </form>',
    )

    class Session:
        def post_multipart(self, url, fields, file_field, path):
            assert url == "https://sigaa.ufpb.br/sigaa/ava/TarefaTurma/enviarTarefa.jsf"
            assert fields["formResponder:enviar"] == "Enviar tarefa"
            assert file_field == "formResponder:idArquivo"
            assert path == upload
            return "<div>Tarefa enviada com sucesso.</div>"

    client = object.__new__(SigaaClient)
    client.profile = SimpleNamespace(host="https://sigaa.ufpb.br")
    client._session = Session()
    client._open_event = lambda event_id: page

    assert client.submit_tarefa("48550620", upload) == {"status": "submitted"}
