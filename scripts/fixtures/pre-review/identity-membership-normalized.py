def owns_identity(ident, owned):
    return normalize_label(ident.get("label")) in owned
