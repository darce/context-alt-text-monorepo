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

import re
from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from scene.application.identity_merge.merge import (
    ConfirmedFace,
    IdentityAssociation,
    span_replaceable,
)

_ARTICLES = ("a ", "an ", "the ")
# Possessive marker on the head noun only (straight or curly apostrophe):
# "man's hat" → group(1)="man". An embedded possessive ("man holding his
# son's toy") does not match, so the whole phrase degrades to the bare name.
_HEAD_POSSESSIVE = re.compile(r"^([^\s'’]+)('s|’s)(.*)$", re.DOTALL)
# Third-person-singular → plural (for singular-they agreement). None = no
# confident transform; the caller must keep the name instead of a pronoun.
_IRREGULAR_VERBS = {"is": "are", "was": "were", "has": "have", "does": "do", "goes": "go"}
# Common 's'-ending words that are not third-person verbs; seeing one right
# after the mention means we cannot locate the verb — keep the name.
_S_ENDING_NON_VERBS = frozenset(
    {
        "always",
        "perhaps",
        "sometimes",
        "besides",
        "towards",
        "upstairs",
        "downstairs",
        "alas",
        "yes",
        "his",
        "hers",
        "its",
        "this",
        "thus",
    }
)


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
        seen_people: set[tuple[str, str]] = set()
        replacements: list[tuple[int, int, str]] = []
        last_end = 0
        for assoc in ordered:
            phrase = assoc.phrase_box.phrase
            start, end = assoc.phrase_box.span_start, assoc.phrase_box.span_end
            if not span_replaceable(caption, assoc.phrase_box):
                continue  # stale/degenerate span: never replace text we cannot verify
            if start < last_end:
                continue  # overlapping span: replacing both would corrupt the text
            person_key = _person_key(assoc.face)
            if person_key in seen_people:
                coref = self._coreference(caption, end, capitalize=phrase[:1].isupper())  # R4
                if coref is None:
                    text = self._name_phrase(phrase, assoc.face.label)  # no confident pronoun: keep the name
                else:
                    text, end = coref
            else:
                seen_people.add(person_key)
                text = self._name_phrase(phrase, assoc.face.label)  # R1/R2
            replacements.append((start, end, text))
            last_end = end

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
        """R1 article elision + case; R2 possessive form on the head noun only."""
        stripped = phrase
        lowered = stripped.lower()
        for article in _ARTICLES:
            if lowered.startswith(article):
                stripped = stripped[len(article) :]
                break
        # R2: only a possessive marker attached to the head noun transfers to
        # the name ("man's hat" → "Daniel's hat"). Embedded possessives
        # ("man holding his son's toy") degrade to the bare name — attributing
        # someone else's possession to the named person is a wrong draft.
        m = _HEAD_POSSESSIVE.match(stripped)
        if m:
            return name + m.group(2) + m.group(3)
        return name

    @staticmethod
    def _pluralize_verb(verb: str) -> str | None:
        """Third-person-singular → plural, or None when not confident.

        The surface form alone is ambiguous for several -es families
        ("watches" = watch+es but "aches" = ache+s; "focuses" = focus+es but
        "uses" = use+s), so those return None and the caller keeps the name.
        """
        lowered = verb.lower()
        if lowered in _S_ENDING_NON_VERBS:
            return None
        if lowered in _IRREGULAR_VERBS:
            return _IRREGULAR_VERBS[lowered]
        if len(lowered) > 4 and lowered.endswith("ies"):
            return verb[:-3] + "y"
        if len(lowered) > 3 and lowered.endswith(("shes", "sses", "xes", "zzes")):
            return verb[:-2]  # unambiguous sibilant stems: pushes, passes, fixes, buzzes
        if lowered.endswith(("ches", "ses")):
            return None  # ambiguous: watch/ache, focus/use — never risk a garbled stem
        if len(lowered) > 3 and lowered.endswith("s") and not lowered.endswith(("ss", "us", "is")):
            return verb[:-1]  # covers e-final stems too: gazes→gaze, dozes→doze
        return None

    def _coreference(self, caption: str, end: int, *, capitalize: bool) -> tuple[str, int] | None:
        """R4: pronoun on later mentions of an already-named identity.

        Uses singular-they (no gender inference). Subject-verb agreement is
        applied only when the immediately following word has a confident
        plural transform; otherwise returns None and the caller keeps the
        name — a repeated name beats a garbled verb.
        """
        pronoun = "They" if capitalize else "they"
        rest = caption[end:]
        verb_start = len(rest) - len(rest.lstrip())
        verb_end = verb_start
        while verb_end < len(rest) and rest[verb_end].isalpha():
            verb_end += 1
        verb = rest[verb_start:verb_end]
        if verb[:1].isupper():
            # Capitalized word after the mention is a proper noun ("A man
            # Smith waves."), not a verb — keep the name, never mutate it.
            return None
        if not verb.endswith("s") and verb.lower() not in _IRREGULAR_VERBS:
            # Next word needs no agreement change ("waved", "will", ...).
            return pronoun, end
        plural = self._pluralize_verb(verb)
        if plural is None:
            return None
        return pronoun + rest[:verb_start] + plural, end + verb_end


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
        ordered = sorted(_distinct_people(confirmed_faces), key=lambda f: f.box.center[0])
        names = DeterministicNlgRealizer.aggregate_names([f.label for f in ordered])
        base = caption.rstrip()
        if not base:
            return f"Pictured from left: {names}."
        if base[-1] not in ".!?":
            base += "."
        return f"{base} Pictured from left: {names}."


def _person_key(face: ConfirmedFace) -> tuple[str, str]:
    if face.cluster_id is not None:
        return "cluster", str(face.cluster_id)
    return "identity", str(face.identity_id)


def _distinct_people(confirmed_faces: Sequence[ConfirmedFace]) -> list[ConfirmedFace]:
    seen: set[tuple[str, str]] = set()
    distinct: list[ConfirmedFace] = []
    for face in confirmed_faces:
        key = _person_key(face)
        if key in seen:
            continue
        seen.add(key)
        distinct.append(face)
    return distinct
