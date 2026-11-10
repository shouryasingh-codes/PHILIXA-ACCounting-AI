"""Recover full explicitly supplied master names; never fuzzy identity guesses."""
import copy,re


def explicit_master_names(content, message, suppliers, items):
    result=copy.deepcopy(content)
    def resolve(label,names):
        if not label or label in names:return label
        candidates=[n for n in names if label.casefold() in n.casefold() and
            re.search(r'(?<!\w)'+re.escape(n)+r'(?!\w)',message,re.I)]
        return candidates[0] if len(candidates)==1 else label
    result['party_name']=resolve(result.get('party_name'),suppliers)
    for line in result.get('lines') or []:
        line['item_name']=resolve(line.get('item_name'),items)
    return result
