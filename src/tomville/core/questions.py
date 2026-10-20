"""Find question-bearing prose lines without interpreting code/quotes as requests."""
import re


def question_lines(text):
    def mask(value):
        return re.sub(r'[^\n]', ' ', value)

    lines, fence = [], None
    for line in text.splitlines():
        marker = re.match(r'^\s*(`{3,}|~{3,})', line)
        if fence:
            if marker and marker[1][0] == fence[0] and len(marker[1]) >= len(fence) and not line[marker.end():].strip():
                fence = None
            lines.append(mask(line))
        elif marker:
            fence = marker[1]
            if re.search(re.escape(fence), line[marker.end():]):
                fence = None
            lines.append(mask(line))
        elif re.match(r'^(?: {4}|\t|\s*>+)', line):
            lines.append(mask(line))
        else:
            lines.append(line)
    prose = '\n'.join(lines)
    # Preserve newlines while masking so the same indexes can drive highlighting.
    patterns = [r'(?<!`)(`+)(?!`)[\s\S]*?(?<!`)\1(?!`)',
                r'"[^"\n]*"|“[^”]*”|‘[^’]*’|(?<!\w)\x27[^\x27\n]*\x27(?!\w)',
                r'https?://[^\s<>]+|www\.[^\s<>]+|(?<=\]\()[^)\n]+(?=\))']
    for pattern in patterns:
        prose = re.sub(pattern, lambda m: mask(m[0]), prose)
    return {i for i, line in enumerate(prose.split('\n')) if re.search(r'？|\?(?=$|\s|[*_~)\]])', line)}
