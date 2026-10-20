"""Find which of the student's classes a classmate takes.

Each roster is read live from the class's Participantes page and never stored;
only the names that match the query leave this module.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import httpx

from ..client import SigaaClient
from ..errors import ParseError
from ..http import AuthError
from ..institutions import Capability
from ..models import Turma
from ..parsers._common import fold

# What reading one class's roster can raise. It is recorded against that class,
# so an unreadable roster makes the search incomplete instead of hiding a match.
_CLASS_ERRORS = (AuthError, ParseError, ValueError, httpx.HTTPError)


@dataclass
class ClassmateMatch:
    name: str
    turmas: list[Turma] = field(default_factory=list)


@dataclass
class ClassFailure:
    turma: Turma
    error: str


@dataclass
class ClassmateSearch:
    query: str
    searched: list[Turma] = field(default_factory=list)
    matches: list[ClassmateMatch] = field(default_factory=list)
    failures: list[ClassFailure] = field(default_factory=list)

    @property
    def complete(self) -> bool:
        """False when a roster could not be read, so a missing match proves nothing."""
        return not self.failures


def find_classmates(client: SigaaClient, query: str) -> ClassmateSearch:
    """Classmates whose name matches ``query``, with the classes shared with them.

    Every word of the query must start a word of the name, ignoring case and
    accents: 'romulo' and 'rom' find 'RÔMULO', 'ana' does not find 'MARIANA'.
    """
    client.profile.require(Capability.CLASSMATES)
    words = fold(query).split()
    if not words:
        raise ValueError("classmate name is empty")
    search = ClassmateSearch(query=query)
    matches: dict[str, ClassmateMatch] = {}
    for turma in client.list_turmas():
        try:
            roster = client.list_classmates(turma)
        except _CLASS_ERRORS as exc:
            search.failures.append(ClassFailure(turma, str(exc)))
            continue
        search.searched.append(turma)
        for classmate in roster:
            if _name_matches(classmate.name, words):
                matches.setdefault(classmate.name, ClassmateMatch(classmate.name)).turmas.append(turma)
    search.matches = sorted(matches.values(), key=lambda match: fold(match.name))
    return search


def _name_matches(name: str, words: list[str]) -> bool:
    name_words = fold(name).split()
    return all(any(part.startswith(word) for part in name_words) for word in words)


def search_to_dict(search: ClassmateSearch) -> dict:
    """The JSON contract shared by ``sigaa classmates --json`` and the MCP tool."""
    return {
        "query": search.query,
        "complete": search.complete,
        "classes_searched": len(search.searched),
        "matches": [
            {"name": match.name, "classes": [_turma_dict(t) for t in match.turmas]}
            for match in search.matches
        ],
        "errors": [{**_turma_dict(f.turma), "error": f.error} for f in search.failures],
    }


def _turma_dict(turma: Turma) -> dict:
    return {"class_id": turma.id_turma, "code": turma.code, "name": turma.name}
