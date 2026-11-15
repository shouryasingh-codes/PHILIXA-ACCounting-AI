"""Compatibility entry point: preparation only, never a native import."""
async def create_missing_masters_in_tally(db,principal,draft_id,create_supplier=True,create_items=True,unit_definitions=None):
    from app.services.master_creation_service import prepare
    return await prepare(db,principal,draft_id,create_supplier,create_items,unit_definitions)
