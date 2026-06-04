from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import re

from subtitle_forge.bidi import LTR_EMBEDDING, POP_DIRECTIONAL_FORMATTING, RTL_EMBEDDING
from subtitle_forge.models import SubtitleCue
from subtitle_forge.normalization import (
    BIDI_OR_INVISIBLE_RE,
    PERSIAN_RE,
    TAG_RE,
    strip_allowed_latin_names,
    strip_bidi_and_invisible,
    strip_tags,
)


LATIN_RE = re.compile(r"[A-Za-z]")
MOJIBAKE_TOKENS = ("Ã", "Â", "â€", "Ø", "Ù", "Ú", "Û")


@dataclass(frozen=True)
class CueIssue:
    cue_id: str
    code: str
    message: str
    line: str | None = None

    def to_dict(self) -> dict[str, str]:
        data = {"cue_id": self.cue_id, "code": self.code, "message": self.message}
        if self.line is not None:
            data["line"] = self.line
        return data


@dataclass(frozen=True)
class ValidationReport:
    source_cue_count: int
    output_cue_count: int
    cue_ids_match: bool
    timestamps_match: bool
    contains_persian_text: bool
    replacement_character_count: int
    mojibake_count: int
    disallowed_latin_dialogue_line_count: int
    unwrapped_dialogue_line_count: int
    tag_mismatch_count: int
    cue_id_lines_with_bidi_or_invisible_marks: list[str]
    timestamp_lines_with_bidi_or_invisible_marks: list[str]
    unicode_controls: dict[str, int]
    suspicious_cue_ids: list[str]
    issues: list[CueIssue]

    def to_dict(self) -> dict:
        return {
            "source_cue_count": self.source_cue_count,
            "output_cue_count": self.output_cue_count,
            "cue_ids_match": self.cue_ids_match,
            "timestamps_match": self.timestamps_match,
            "contains_persian_text": self.contains_persian_text,
            "replacement_character_count": self.replacement_character_count,
            "mojibake_count": self.mojibake_count,
            "disallowed_latin_dialogue_line_count": self.disallowed_latin_dialogue_line_count,
            "unwrapped_dialogue_line_count": self.unwrapped_dialogue_line_count,
            "tag_mismatch_count": self.tag_mismatch_count,
            "cue_id_lines_with_bidi_or_invisible_marks": self.cue_id_lines_with_bidi_or_invisible_marks,
            "timestamp_lines_with_bidi_or_invisible_marks": self.timestamp_lines_with_bidi_or_invisible_marks,
            "unicode_controls": self.unicode_controls,
            "suspicious_cue_count": len(self.suspicious_cue_ids),
            "suspicious_cue_ids": self.suspicious_cue_ids,
            "issues": [issue.to_dict() for issue in self.issues],
        }


def validate_translation(
    source_cues: list[SubtitleCue],
    output_cues: list[SubtitleCue],
    allowed_latin_names: list[str],
) -> ValidationReport:
    output_text = "\n".join(cue.text for cue in output_cues)
    issues: list[CueIssue] = []
    source_by_id = {cue.id: cue for cue in source_cues}

    if len(source_cues) != len(output_cues):
        issues.append(CueIssue("", "cue_count_mismatch", "Source and output cue counts do not match."))

    source_ids = [cue.id for cue in source_cues]
    output_ids = [cue.id for cue in output_cues]
    cue_ids_match = source_ids == output_ids
    if not cue_ids_match:
        issues.append(CueIssue("", "cue_id_mismatch", "Source and output cue ids do not match."))

    source_times = [(cue.start, cue.end) for cue in source_cues]
    output_times = [(cue.start, cue.end) for cue in output_cues]
    timestamps_match = source_times == output_times
    if not timestamps_match:
        issues.append(CueIssue("", "timestamp_mismatch", "Source and output timestamps do not match."))

    cue_id_marks = [cue.id for cue in output_cues if BIDI_OR_INVISIBLE_RE.search(cue.id)]
    timestamp_marks = [
        cue.id
        for cue in output_cues
        if BIDI_OR_INVISIBLE_RE.search(str(cue.start)) or BIDI_OR_INVISIBLE_RE.search(str(cue.end))
    ]
    for cue_id in cue_id_marks:
        issues.append(CueIssue(cue_id, "structural_bidi_mark", "Cue id contains bidi or invisible marks."))
    for cue_id in timestamp_marks:
        issues.append(CueIssue(cue_id, "timestamp_bidi_mark", "Timestamp contains bidi or invisible marks."))

    disallowed_latin_count = 0
    unwrapped_count = 0
    tag_mismatch_count = 0
    for cue in output_cues:
        source = source_by_id.get(cue.id)
        if source and _tags(source.text) != _tags(cue.text):
            tag_mismatch_count += 1
            issues.append(CueIssue(cue.id, "tag_mismatch", "Output formatting tags differ from source tags."))

        if source and _length_ratio_is_suspicious(source.text, cue.text):
            issues.append(CueIssue(cue.id, "length_ratio", "Output cue length is suspicious compared with source."))

        for line in cue.text.splitlines() or [cue.text]:
            clean_line = strip_bidi_and_invisible(strip_tags(line))
            if clean_line.strip() and not PERSIAN_RE.search(clean_line):
                issues.append(CueIssue(cue.id, "missing_persian", "Dialogue line has no Persian text.", line))
            if _line_has_disallowed_latin(line, allowed_latin_names):
                disallowed_latin_count += 1
                issues.append(CueIssue(cue.id, "disallowed_latin", "Dialogue line contains disallowed Latin text.", line))
            if line and not (line.startswith(RTL_EMBEDDING) and line.endswith(POP_DIRECTIONAL_FORMATTING)):
                unwrapped_count += 1
                issues.append(CueIssue(cue.id, "missing_rtl_wrap", "Dialogue line is missing RTL embedding marks.", line))
            if _line_has_repeated_junk(line):
                issues.append(CueIssue(cue.id, "repeated_junk", "Dialogue line contains suspicious repeated tokens.", line))

    for token in MOJIBAKE_TOKENS:
        for cue in output_cues:
            if token in cue.text:
                issues.append(CueIssue(cue.id, "mojibake", f"Dialogue contains mojibake token {token!r}."))

    suspicious_ids = sorted({issue.cue_id for issue in issues if issue.cue_id}, key=_cue_sort_key)
    return ValidationReport(
        source_cue_count=len(source_cues),
        output_cue_count=len(output_cues),
        cue_ids_match=cue_ids_match,
        timestamps_match=timestamps_match,
        contains_persian_text=bool(PERSIAN_RE.search(output_text)),
        replacement_character_count=output_text.count("\ufffd"),
        mojibake_count=sum(output_text.count(token) for token in MOJIBAKE_TOKENS),
        disallowed_latin_dialogue_line_count=disallowed_latin_count,
        unwrapped_dialogue_line_count=unwrapped_count,
        tag_mismatch_count=tag_mismatch_count,
        cue_id_lines_with_bidi_or_invisible_marks=cue_id_marks,
        timestamp_lines_with_bidi_or_invisible_marks=timestamp_marks,
        unicode_controls={
            "U+202B_RTL_EMBED": output_text.count(RTL_EMBEDDING),
            "U+202C_POP_DIRECTIONAL": output_text.count(POP_DIRECTIONAL_FORMATTING),
            "U+202A_LTR_EMBED": output_text.count(LTR_EMBEDDING),
            "U+200C_ZWNJ": output_text.count("\u200c"),
        },
        suspicious_cue_ids=suspicious_ids,
        issues=issues,
    )


def validation_passed(report: ValidationReport) -> bool:
    return (
        report.source_cue_count == report.output_cue_count
        and report.cue_ids_match
        and report.timestamps_match
        and report.replacement_character_count == 0
        and report.mojibake_count == 0
        and report.disallowed_latin_dialogue_line_count == 0
        and report.unwrapped_dialogue_line_count == 0
        and report.tag_mismatch_count == 0
        and not report.cue_id_lines_with_bidi_or_invisible_marks
        and not report.timestamp_lines_with_bidi_or_invisible_marks
        and not report.suspicious_cue_ids
    )


def _line_has_disallowed_latin(line: str, allowed_latin_names: list[str]) -> bool:
    without_tags = strip_tags(line)
    without_controls = strip_bidi_and_invisible(without_tags)
    without_allowed = strip_allowed_latin_names(without_controls, allowed_latin_names)
    return bool(LATIN_RE.search(without_allowed))


def _line_has_repeated_junk(line: str) -> bool:
    text = strip_bidi_and_invisible(strip_tags(line))
    tokens = re.findall(r"[A-Za-z]+|[\u0600-\u06ff]+", text)
    if len(tokens) < 4:
        return False
    counts = Counter(token.lower() for token in tokens)
    return any(count >= 4 for count in counts.values())


def _length_ratio_is_suspicious(source_text: str, output_text: str) -> bool:
    source_len = len(strip_tags(source_text).strip())
    output_len = len(strip_bidi_and_invisible(strip_tags(output_text)).strip())
    if source_len < 8 or output_len == 0:
        return False
    return output_len > source_len * 4 or output_len < source_len * 0.15


def _tags(text: str) -> list[str]:
    return TAG_RE.findall(text)


def _cue_sort_key(cue_id: str) -> tuple[int, str]:
    try:
        return (int(cue_id), cue_id)
    except ValueError:
        return (10**9, cue_id)
