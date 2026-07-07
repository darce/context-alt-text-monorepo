"""Reflow realizers: turn 1:1 name↔phrase associations into a named draft.

``ReflowRealizer`` is the LLM-ready seam (Approach D drops a constrained
on-box LLM behind the same Protocol later; no LLM ships in v1). The two v1
implementations are deterministic:

- ``DeterministicNlgRealizer`` — grammar-aware span replacement with the four
  enumerated, individually-tested rules (R1 article elision + case, R2
  possessive form, R3 list aggregation, R4 repeated-mention coreference).
- ``PositionalFallbackRealizer`` — Approach B: when phrase grounding is
  absent, order confirmed faces left→right and append one naming sentence.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from scene.application.identity_merge.merge import ConfirmedFace, IdentityAssociation

_ARTICLES = ("a ", "an ", "the ")


@runtime_checkable
class ReflowRealizer(Protocol):
    """Realizes the named draft from the caption plus naming evidence."""

    def realize(
        self,
        *,
        caption: str,
        associations: Sequence[IdentityAssociation],
        confirmed_faces: Sequence[ConfirmedFace],
    ) -> str: ...


class DeterministicNlgRealizer:
    """Span replacement with enumerated grammar rules R1–R4 (PA-03)."""

    def realize(
        self,
        *,
        caption: str,
        associations: Sequence[IdentityAssociation],
        confirmed_faces: Sequence[ConfirmedFace],
    ) -> str:
        ordered = sorted(associations, key=lambda a: a.phrase_box.span_start)
        seen_labels: set[str] = set()
        replacements: list[tuple[int, int, str]] = []
        for assoc in ordered:
            phrase = assoc.phrase_box.phrase
            start, end = assoc.phrase_box.span_start, assoc.phrase_box.span_end
            if caption[start:end] != phrase:
                continue  # stale span: never replace text we cannot verify
            if assoc.face.label in seen_labels:
                text, end = self._coreference(caption, end, capitalize=phrase[:1].isupper())  # R4
            else:
                seen_labels.add(assoc.face.label)
                text = self._name_phrase(phrase, assoc.face.label)  # R1/R2
            replacements.append((start, end, text))

        named = caption
        for start, end, text in sorted(replacements, reverse=True):
            named = named[:start] + text + named[end:]
        return named

    @staticmethod
    def aggregate_names(names: Sequence[str]) -> str:
        """R3: 'Daniel' / 'Daniel and Sarah' / 'Daniel, Sarah and Tom'."""
        names = list(names)
        if not names:
            return ""
        if len(names) == 1:
            return names[0]
        return ", ".join(names[:-1]) + " and " + names[-1]

    def _name_phrase(self, phrase: str, name: str) -> str:
        """R1 article elision + case; R2 possessive/object form."""
        stripped = phrase
        lowered = stripped.lower()
        for article in _ARTICLES:
            if lowered.startswith(article):
                stripped = stripped[len(article) :]
                break
        # R2: keep everything from the possessive marker on ("man's hat" →
        # "Daniel's hat"); otherwise the proper name replaces the whole phrase.
        marker = stripped.find("'s")
        if marker != -1:
            return name + stripped[marker:]
        return name

    def _coreference(self, caption: str, end: int, *, capitalize: bool) -> tuple[str, int]:
        """R4: pronoun on later mentions of an already-named identity.

        Uses singular-they (no gender inference), with naive subject-verb
        agreement: an immediately following third-person-singular verb loses
        its trailing 's' ("waves" → "wave").
        """
        pronoun = "They" if capitalize else "they"
        rest = caption[end:]
        verb_start = len(rest) - len(rest.lstrip())
        verb_end = verb_start
        while verb_end < len(rest) and rest[verb_end].isalpha():
            verb_end += 1
        verb = rest[verb_start:verb_end]
        if len(verb) > 2 and verb.endswith("s") and not verb.endswith("ss"):
            new_end = end + verb_end
            return pronoun + rest[:verb_start] + verb[:-1], new_end
        return pronoun, end


class PositionalFallbackRealizer:
    """Approach B: no grounding — order faces left→right, append one sentence."""

    def realize(
        self,
        *,
        caption: str,
        associations: Sequence[IdentityAssociation],
        confirmed_faces: Sequence[ConfirmedFace],
    ) -> str:
        if not confirmed_faces:
            return caption
        ordered = sorted(confirmed_faces, key=lambda f: f.box.center[0])
        names = DeterministicNlgRealizer.aggregate_names([f.label for f in ordered])
        base = caption.rstrip()
        if base and base[-1] not in ".!?":
            base += "."
        return f"{base} Pictured from left: {names}."
