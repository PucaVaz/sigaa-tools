from sigaa.parsers.curriculo import parse_components, prerequisite_met

DATA = {
    "disciplinas": [
        {"codigo": "AAA0001", "nome": "INTRO", "tipoIntegralizacao": "OB", "periodo": 1,
         "cargaHoraria": 60, "obrigatoria": True, "situacao": "CONCLUIDO"},
        {"codigo": "BBB0002", "nome": "SEGUNDA", "tipoIntegralizacao": "OB", "periodo": 2,
         "cargaHoraria": 60, "obrigatoria": True, "situacao": "PENDENTE",
         "expressaoPreRequisito": "( AAA0001 ) "},
        {"codigo": "CCC0003", "nome": "TERCEIRA", "tipoIntegralizacao": "OP", "periodo": 3,
         "cargaHoraria": 30, "obrigatoria": False, "situacao": "PENDENTE",
         "expressaoPreRequisito": "( BBB0002 ) E ( AAA0001 OU DDD0004 ) "},
    ]
}


def test_parse_components_flags():
    comps = {c.code: c for c in parse_components(DATA)}
    assert comps["AAA0001"].completed and comps["AAA0001"].prerequisite_met
    assert not comps["BBB0002"].completed and comps["BBB0002"].prerequisite_met
    assert not comps["CCC0003"].prerequisite_met  # BBB0002 not yet completed
    assert comps["CCC0003"].hours == 30 and not comps["CCC0003"].mandatory


def test_prerequisite_expressions():
    done = {"AAA0001", "BBB0002"}
    assert prerequisite_met(None, done)
    assert prerequisite_met("", done)
    assert prerequisite_met("( AAA0001 ) E ( BBB0002 )", done)
    assert prerequisite_met("( ZZZ0009 ) OU ( AAA0001 )", done)
    assert not prerequisite_met("( ZZZ0009 ) E ( AAA0001 )", done)


def test_prerequisite_rejects_garbage():
    import pytest

    with pytest.raises(ValueError):
        prerequisite_met("( AAA0001 ) E import os", set())
