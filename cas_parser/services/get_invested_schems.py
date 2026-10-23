from cas_parser.models import CASSchemeHolding


def get_invested_schemes(user):
    """
    Return the unique set of mutual-fund schemes a user has invested in.

    A user can hold the same scheme across multiple folios / CAS statements,
    so duplicates are collapsed:
      * resolved holdings are de-duped by MutualFundsScheme.id
      * unresolved holdings are de-duped by (isin, amfi_code, scheme_name)
      * unresolved holdings whose ISIN / AMFI already appear on a resolved
        holding are dropped entirely (the resolved row wins).
    """
    holdings = (
        CASSchemeHolding.objects
        .filter(folio__statement__user=user)
        .select_related("scheme")
        .only(
            "id",
            "scheme_id",
            "scheme_name",
            "isin",
            "amfi_code",
            "scheme__id",
            "scheme__scheme_name",
            "scheme__isin_code",
            "scheme__amfi_code",
        )
    )

    schemes = []
    seen_scheme_ids = set()
    seen_raw = set()
    resolved_isins = set()
    resolved_amfis = set()

    # 1st pass — holdings linked to a MutualFundsScheme
    for h in holdings:
        if not h.scheme_id or h.scheme_id in seen_scheme_ids:
            continue
        seen_scheme_ids.add(h.scheme_id)

        isin = (h.scheme.isin_code or h.isin or "").strip()
        amfi = (h.scheme.amfi_code or h.amfi_code or "").strip()

        if isin:
            resolved_isins.add(isin.upper())
        if amfi:
            resolved_amfis.add(amfi)

        schemes.append(
            {
                "scheme_id":  h.scheme_id,
                "scheme_name": h.scheme.scheme_name,
                "isin":       isin,
                "amfi_code":  amfi,
            }
        )

    # 2nd pass — unresolved holdings
    for h in holdings:
        if h.scheme_id:
            continue

        isin = (h.isin or "").strip()
        amfi = (h.amfi_code or "").strip()
        name = (h.scheme_name or "").strip()

        if isin and isin.upper() in resolved_isins:
            continue
        if amfi and amfi in resolved_amfis:
            continue

        key = (isin.upper(), amfi, name.lower())
        if key in seen_raw:
            continue
        seen_raw.add(key)

        schemes.append(
            {
                "scheme_id":  None,
                "scheme_name": name,
                "isin":       isin,
                "amfi_code":  amfi,
            }
        )

    schemes.sort(key=lambda s: (s["scheme_name"] or "").lower())
    return schemes