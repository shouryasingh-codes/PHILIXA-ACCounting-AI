"""Deterministic supplier classification from exported Tally masters."""
from app.services.tally_connector import name, value


def supplier_rows(catalog):
    parents = {name(g).casefold(): value(g, 'PARENT').casefold() for g in catalog.get('groups', [])}
    def creditor(parent):
        seen = set()
        while parent and parent not in seen:
            if parent == 'sundry creditors':
                return True
            seen.add(parent)
            parent = parents.get(parent, '')
        return False
    return [l for l in catalog['ledgers'] if creditor(value(l, 'PARENT').casefold())]
