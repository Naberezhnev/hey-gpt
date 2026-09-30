"""Normalize the empty editor hint only when the UI has no send action."""
def composer_text(raw, placeholder, send_visible):
    normalized = raw.strip("\r\n \t\u200b\ufeff")
    if placeholder and normalized == placeholder.strip() and not send_visible:
        return ""
    return raw
