"""Aggregate everything unseen across channels into one feed.

The store already flags unread news, materials, deadlines, and posted grade
changes (``is_new``). This collects them into a single view and can mark the
whole batch seen, so the user gets one "what changed" answer per sync.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..models import Deadline, Material, NewsItem, TurmaGrade
from ..store.repository import Repository


@dataclass
class WhatsNew:
    news: list[NewsItem] = field(default_factory=list)
    materials: list[Material] = field(default_factory=list)
    deadlines: list[Deadline] = field(default_factory=list)
    grades: list[TurmaGrade] = field(default_factory=list)

    def total(self) -> int:
        return len(self.news) + len(self.materials) + len(self.deadlines) + len(self.grades)


def collect(repo: Repository) -> WhatsNew:
    return WhatsNew(
        news=repo.get_news(unread_only=True),
        materials=repo.get_materials(unread_only=True),
        deadlines=repo.get_deadlines(unread_only=True),
        grades=repo.get_turma_grades(unread_only=True),
    )


def mark_seen(repo: Repository, feed: WhatsNew) -> None:
    repo.mark_news_seen([n.id for n in feed.news])
    repo.mark_materials_seen([m.id for m in feed.materials])
    repo.mark_deadlines_seen([d.id for d in feed.deadlines])
    repo.mark_turma_grades_seen([g.id_turma for g in feed.grades])
