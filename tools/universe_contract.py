"""Public UniverseJSONv1 metadata validation, independent of filesystem policy.

Single-market subsets are valid acquisition batches. A complete native frozen
snapshot additionally requires both US and KR; that is the loader's boundary.
"""
import datetime as dt
import json
import re


SLUG = re.compile(r'[a-z0-9][a-z0-9_-]{0,63}')


def validate_universe(raw: bytes) -> dict:
    """Return literal catalog metadata; invalid catalogs raise ValueError."""
    def unique_object(pairs):
        result = {}
        for key, item in pairs:
            if key in result:
                raise ValueError('duplicate_universe_json_key')
            result[key] = item
        return result

    def invalid_constant(_):
        raise ValueError('invalid_universe_json_constant')

    value = json.loads(raw.decode('utf-8'), object_pairs_hook=unique_object,
                       parse_constant=invalid_constant)
    fields = {'schema_version', 'universe_id', 'classification_as_of',
              'point_in_time', 'selection_policy', 'limitations', 'instruments'}
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError('invalid_universe_fields')
    if type(value['schema_version']) is not int or value['schema_version'] != 1:
        raise ValueError('invalid_universe_version')
    if value['point_in_time'] is not False:
        raise ValueError('invalid_universe_point_in_time')
    policy, limits = value['selection_policy'], value['limitations']
    if not isinstance(policy, str) or not policy.strip():
        raise ValueError('invalid_universe_selection_policy')
    if (not isinstance(limits, list) or not limits
            or any(not isinstance(s, str) or not s.strip() for s in limits)):
        raise ValueError('invalid_universe_limitations')
    # Python's JSON parser accepts unpaired escaped surrogates; native JSON
    # strings do not. Encoding validates scalar values without normalizing them.
    for text in [policy, *limits]:
        text.encode('utf-8')
    if (not isinstance(value['instruments'], list)
            or not 1 <= len(value['instruments']) <= 512):
        raise ValueError('invalid_universe_instruments')
    slug, date = value['universe_id'], value['classification_as_of']
    if not isinstance(slug, str) or not SLUG.fullmatch(slug):
        raise ValueError('invalid_universe_id')
    if not isinstance(date, str) or not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}', date):
        raise ValueError('invalid_universe_date')
    dt.date.fromisoformat(date)
    identities, sources = set(), set()
    for item in value['instruments']:
        if not isinstance(item, dict) or set(item) != {'market', 'ticker', 'source_symbol', 'themes'}:
            raise ValueError('invalid_universe_instrument_fields')
        market = item['market']
        if market not in ('US', 'KR'):
            raise ValueError('invalid_universe_market')
        pattern = r'[A-Z0-9][A-Z0-9.-]{0,23}' if market == 'US' else r'[A-Z0-9]{6}'
        for field in ('ticker', 'source_symbol'):
            if not isinstance(item[field], str) or not re.fullmatch(pattern, item[field]):
                raise ValueError('invalid_universe_symbol')
        identity, source = (market, item['ticker']), (market, item['source_symbol'])
        if identity in identities or source in sources:
            raise ValueError('duplicate_universe_identity')
        identities.add(identity)
        sources.add(source)
        themes = item['themes']
        if (not isinstance(themes, list) or not themes
                or any(not isinstance(s, str) or not SLUG.fullmatch(s) for s in themes)
                or len(set(themes)) != len(themes)):
            raise ValueError('invalid_universe_themes')
    return value
