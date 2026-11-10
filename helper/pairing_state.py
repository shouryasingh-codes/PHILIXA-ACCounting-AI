"""Reuse an existing pairing until the server explicitly rejects it."""


def reuse_saved_pairing(has_secret, saved_origin, selected_origin, rejected=False):
    return bool(has_secret and not rejected and saved_origin.rstrip('/') == selected_origin.strip().rstrip('/'))
