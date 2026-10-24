"""Source layer shared plumbing: async GET, errors.
Clients accept an injected httpx.AsyncClient (tests use MockTransport).
"""
import httpx


class SourceError(Exception):
    """External source failure (network / bad payload / paid-tier limit)."""


class TokenUnknown(SourceError):
    """Source HEALTHY but has no record of this token (valid answer, not a
    failure). v0.4: drives unknown-token rule, NOT data_limited."""


async def get_json(url, params, client, timeout=8.0):
    headers = dict()
    headers["User-Agent"] = "atg/0.1"
    try:
        r = await client.get(url, params=params, headers=headers, timeout=timeout)
        r.raise_for_status()
        return r.json()
    except httpx.HTTPError as e:
        raise SourceError("http failed: %s %s" % (url, str(e)[:120])) from e
