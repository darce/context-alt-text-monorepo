"""Labeling helpers for recognition workflows."""

from recognition.application.labeling.auto_labeler import allocate_person_label, should_auto_label

__all__ = ["allocate_person_label", "should_auto_label"]
