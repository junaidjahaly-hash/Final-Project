import re


def sender_name(question: str, username: str) -> str:
    """Use an explicitly requested signature, otherwise the account username."""
    patterns = [
        r'\b(?:my name is|sender name is|sign(?: it| the email)? off as|sign(?: it| the email)? as|signed by)\s+["\']?([^\n,.!?;"\']+)',
        r'\buse\s+["\']?([^\n,.!?;"\']+?)["\']?\s+as (?:my|the) (?:name|signature|sender name)\b',
    ]
    for pattern in patterns:
        match = re.search(pattern, question, re.I)
        if match:
            name = re.split(r'\s+and\s+', match.group(1), maxsplit=1, flags=re.I)[0].strip()
            if name and len(name) <= 100:
                return name
    return username


def sign_email(body: str, name: str) -> str:
    """Replace sender placeholders and make the closing use the chosen name."""
    body = re.sub(r'\[\s*(?:your|sender(?:\'s)?|employee(?:\'s)?|full|my)\s+name\s*\]', lambda _: name, body, flags=re.I).rstrip()
    closing = re.search(
        r'(?:^|\n|(?<=  ))((?:best|kind|warm) regards|regards|sincerely|best wishes|yours sincerely|thank you|thanks)[,!]?\s*([^\n]*(?:\n[^\n]*){0,3})$',
        body, re.I,
    )
    if closing and len(closing.group(2)) <= 150:
        return body[:closing.start(1)] + closing.group(1).rstrip(',!') + ',\n' + name
    if body.endswith(name):
        return body
    return f'{body}\n\nBest regards,\n{name}'
