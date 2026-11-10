"""Source pagination evidence only. No absence is inferred without printed markers."""
import re


def pagination_issues(page_texts):
    markers=[re.findall(r'^\s*Page[ \t]+(\d+)[ \t]*(?:of|/)[ \t]*(\d+)[ \t]*$',text,re.I|re.M) for text in page_texts]
    if not any(markers):return []
    if any(len(m)!=1 for m in markers):return ['Printed invoice pagination is incomplete or ambiguous; upload all pages before posting.']
    numbers=[int(m[0][0]) for m in markers];totals=[int(m[0][1]) for m in markers]
    if len(set(totals))!=1 or totals[0]!=len(page_texts) or numbers!=list(range(1,len(page_texts)+1)):
        return ['Printed invoice pagination is missing, duplicated or out of order; upload all pages before posting.']
    return []
