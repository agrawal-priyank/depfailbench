"""Author-approved source handling; no model calls, repairs or source execution."""
import re
POLICY='single-unambiguous-python-fence-2026-10-20'
WHOLE=re.compile(r'\s*```(?:python)?\s*\n(.*?)\n```\s*',re.I|re.S)
SINGLE=re.compile(r'^[ \t]*```(?:python)?[ \t]*\r?\n(.*?)^[ \t]*```[ \t]*$',re.M|re.S|re.I)

def process(text):
    if not isinstance(text,str):raise TypeError('response must be text')
    whole=WHOLE.fullmatch(text)
    strict=(whole.group(1) if whole else text).strip()
    strict=strict+'\n' if strict else ''
    blocks=list(SINGLE.finditer(text));fences=re.findall(r'^[ \t]*```[^\n]*$',text,re.M)
    unambiguous=len(blocks)==1 and len(fences)==2
    extracted=blocks[0].group(1).strip() if unambiguous else strict.strip()
    source=extracted+'\n' if extracted else ''
    kind=('empty' if not text.strip() else 'whole_response_python_fence' if unambiguous and whole
          else 'single_python_fence_with_surrounding_text' if unambiguous
          else 'ambiguous_or_unfinished_fences' if fences else 'raw_source_text')
    return {'source':source,'policy':POLICY,'method':kind,
            'structural_format_compliant_under_original_rule':kind in {'whole_response_python_fence','raw_source_text'},
            'surrounding_text_removed':unambiguous and not bool(whole),'original_strict_source':strict}
