"""Keep successive conversion sanctions separate from ordinary source merging."""
import re
from .engine import dt
from .sources import clean_name

BENEFIT_FIELDS = ('effective', 'family', 'enhanced', 'enhanced_until', 'normal',
                  'normal_from', 'fma_after', 'account', 'ifsc')


def beneficiary_key(name):
    return re.sub(r"^miss\b\.?\s*", "", clean_name(name), flags=re.I).casefold()


def separate_conversions(candidates):
    orders = [(name, fields) for name, fields in candidates if fields.get('_conversion_order')]
    if len(orders) < 2:
        return candidates, []
    for name, fields in orders:
        if any(not fields.get(key) for key in BENEFIT_FIELDS[:7]):
            raise ValueError(f'{name}: review incomplete conversion sanction fields.')
    orders.sort(key=lambda entry: dt(entry[1]['effective']))
    if len({fields['effective'] for _, fields in orders}) != len(orders):
        raise ValueError('Multiple conversion sanctions have the same effective date. Review applicability.')
    if len({beneficiary_key(fields['family']) for _, fields in orders}) != len(orders):
        raise ValueError('Repeated beneficiary across conversion sanctions. Review whether an order is a correction.')
    timeline = []
    for name, fields in orders:
        order = {key: fields[key] for key in BENEFIT_FIELDS[:7]}
        order['source'] = name
        dobs = {dt(candidate['family_dob']).isoformat() for _, candidate in candidates
                if candidate.get('family_dob') and candidate.get('family')
                and beneficiary_key(candidate['family']) == beneficiary_key(order['family'])}
        if len(dobs) == 1:
            order['dob'] = dobs.pop()
        timeline.append(order)
    latest = orders[-1]
    current = []
    for name, fields in candidates:
        if fields.get('_conversion_order'):
            if name != latest[0]:
                continue
        elif fields.get('family') and beneficiary_key(fields['family']) != beneficiary_key(latest[1]['family']):
            fields = {key: value for key, value in fields.items()
                      if key not in (*BENEFIT_FIELDS, 'family_dob', 'relationship')}
        fields = dict(fields)
        if fields.get('family') and beneficiary_key(fields['family']) == beneficiary_key(latest[1]['family']):
            fields['family'] = beneficiary_key(latest[1]['family']).upper()
        elif 'family_dob' in fields:
            fields.pop('family_dob')
        current.append((name, fields))
    return current, timeline
