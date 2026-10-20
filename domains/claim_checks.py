"""Targeted checks for known source-to-note distortions; not a fact checker."""

import re
from urllib.parse import urlparse


def validate_claim_wording(claim, evidence_text, source_url=""):
    """Return reviewable issues; never rewrite claims or infer missing facts.

    Callers bind each fact paragraph to its own cited source. These narrow
    checks catch the observed unit/metric/attribution errors, not all falsehoods.
    """
    issues = []
    evidence_text = evidence_text or ""
    token_counts = set(re.findall(r'\b(\d+)[\s\-‐‑–]+tokens?\b', evidence_text, re.I))
    for count in token_counts:
        # If the source itself contains this word/character count, the unit is
        # ambiguous: a string check must not decide which measurement was meant.
        if re.search(r'\b' + count + r'[\s\-]+(?:words?|characters?)\b', evidence_text, re.I):
            continue
        if re.search(r'(?<![\d.])' + count + r'\s*(?:个)?\s*(?:单词|词|字符|字)', claim):
            issues.append(f"Claim unit mismatch: source says {count} tokens; retain that unit")

    odds = [float(value) for value in re.findall(
        r'(?:\bOR\s*[=＝:：]|odds[\s-]+ratio\s*(?:of|=|:)?|优势比\s*[=＝:：]?)\s*(\d+(?:\.\d+)?)',
        evidence_text, re.I)]
    for sentence in re.split(r'[。！？；;\n]', claim):
        if not odds or not re.search(r'概率|可能性', sentence):
            continue
        if re.search(r'(?:不能|不可|不应|不代表|不等于|并非|不是).{0,18}(?:概率|可能性)', sentence):
            continue
        for multiplier in re.findall(r'(\d+(?:\.\d+)?)\s*倍', sentence):
            precision = len(multiplier.split('.')[1]) if '.' in multiplier else 0
            if any(abs(float(multiplier) - value) <= 0.5 * 10 ** -precision for value in odds):
                issues.append("Claim metric mismatch: odds ratio is not a probability multiplier")
                break

    host = (urlparse(source_url).hostname or "").lower()
    if host == "reddit.com" or host.endswith(".reddit.com"):
        for sentence in re.split(r'[。！？；;\n]', claim):
            if not re.search(r'(?:条款|政策|官方规则).{0,16}(?:禁止|允许|规定|要求|必须)', sentence):
                continue
            if re.search(r'(?:帖子|发帖人|作者|用户)(?:声称|称|表示)|据.{0,12}(?:帖子|转述)|'
                         r'(?:条款|政策|适用范围).{0,12}(?:未核实|待核验|尚待核实)', sentence):
                continue
            issues.append("Claim attribution missing: a community account cannot establish official policy")
    return list(dict.fromkeys(issues))
