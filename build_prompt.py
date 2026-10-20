"""
Build the complete Claude prompt by combining:
- prompt_template.md (analysis rules)
- ai_news_raw_YYYY-MM-DD.json (data)
- Output instructions
"""
import json
import sys
from pathlib import Path

def main():
    if len(sys.argv) < 5:
        print("Usage: build_prompt.py <data_json> <output_prompt> <template_md> <report_file> [max_items]")
        sys.exit(1)

    data_file = Path(sys.argv[1])
    output_file = Path(sys.argv[2])
    template_file = Path(sys.argv[3])
    report_file = sys.argv[4]
    max_items = int(sys.argv[5]) if len(sys.argv) > 5 else 8

    template = template_file.read_text(encoding="utf-8")
    data = json.loads(data_file.read_text(encoding="utf-8"))

    prompt = f"""
# Task: Generate Today's AI Intelligence Daily Report

## Your Role and Rules
{template}

## Raw Data
Below is today's pre-filtered AI news data (JSON).
Only keep the {max_items} most important items.

## Raw Data JSON
```json
{json.dumps(data, ensure_ascii=False, indent=2)}
```

## Output Instructions
- Strictly follow the output format in prompt_template.md
- Each item MUST include all 5 analysis sections
- MUST include the weekly trend summary at the end
- Plain language, no jargon — your reader is NOT an AI professional
- Every item MUST have actionable advice
- Write the complete report to: {report_file}

Generate the report now. Write the full markdown content to {report_file}.
"""
    output_file.write_text(prompt, encoding="utf-8")
    print(f"[OK] Prompt built: {output_file} ({len(prompt)} chars)")

if __name__ == "__main__":
    main()
