"""Bounded product-help answers; no model, accounting data or side effects."""
import re


def conversational_body(message: str) -> str:
    """Remove only greeting/address wrappers; retain the complete substantive turn.

    This is compositional: greeting + help uses the same intent as help alone.
    Mixed accounting requests remain intact and cannot match a help-only intent.
    """
    text = message.strip().casefold()
    wrapper = r"(?:h+i+|h+e+y+|h+y+|hello|namaste|नमस्ते|bhai|bro|please|philixa)"
    return re.sub(r'^(?:' + wrapper + r'(?:[\s,!.:]+|$))+', '', text).strip()


def help_answer(message: str) -> str | None:
    text = re.sub(r"[?!.।]+$", "", conversational_body(message)).strip()
    text = re.sub(r"\s+", " ", text)
    # Normalize common Roman-Hindi spellings before matching the whole intent.
    # Whole-message matching keeps mixed help + accounting commands on the agent path.
    aliases = {'tu':'tum','aap':'tum','maire':'mere','merey':'mere',
               'meray':'mere','liyee':'liye','liya':'liye',
               'kiya':'kya','kyaa':'kya','kr':'kar','sakta':'sakte','sakti':'sakte',
               'saktii':'sakte','hai':'ho','hain':'ho'}
    text = ' '.join(aliases.get(word, word) for word in text.split())
    text = re.sub(r'^(?:(?:bhai|bro|please|philixa)[, ]+)+', '', text)
    if not re.fullmatch(
        r"(?:what\s*you can do for me|what can you do(?: for me)?|"
        r"how can you help(?: me)?|"
        r"tum (?:(?:mere liye )?kya(?: kya)?|kya(?: kya)? mere liye) kar sakte ho|"
        r"tum meri (?:kya )?help (?:kaise )?kar sakte ho|"
        r"tum mere liye kya kar sakte ho batao|"
        r"तुम क्या कर सकते हो|आप क्या कर सकते हैं)", text
    ):
        return None
    return (
        "Main Tally ka stock aur supported reports dikha sakti hoon, "
        "purchase ka draft bana sakti hoon aur bill PDF/photo se details nikaalne mein help kar sakti hoon.\n"
        "Try karo: ‘Stock kitna hai?’ ya ‘Sharma se 5 Cement bags ₹350 mein kharide.’\n"
        "Entry se pehle zaroori details aur approval check honge; "
        "Tally se verify hone par hi entry successful bataungi."
    )


def reply(answer: str) -> dict:
    return {'response': answer, 'status': 'completed', 'issues': [],
            'response_kind': 'product_help'}
