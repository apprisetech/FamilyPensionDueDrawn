"""Section-based parsing of the HTML reports observed in SAMPANN."""
import re
from decimal import Decimal
from .engine import dt


def norm(value):
    return re.sub(r'[^a-z0-9]', '', str(value).lower())


def clean_name(value):
    return re.sub(r'\s+', ' ', re.sub(r'^(?:(?:late|mrs|mr|ms)\b\.?\s*)+', '', value.strip(), flags=re.I)).strip()


def tables_to_fields(tables, kind, ppo):
    """Input tables are visible rendered rows, including cells without labels."""
    out = {'ppo': ppo}
    notes = []
    for table in tables:
        rows = table['rows']
        if not rows:
            continue
        heading = norm(' '.join(rows[0]))
        if kind == 'form14':
            for row in rows:
                if len(row) == 2 and 'nameof' in norm(row[0]) and 'governmentservant' in norm(row[0]):
                    out['pensioner'] = clean_name(row[-1])
                if len(row) == 2 and 'dateofdeath' in norm(row[0]) and row[-1].strip():
                    out['death'] = dt(row[-1]).isoformat()
            if heading.startswith('namedateofbirthrelationshipwiththedeceased'):
                candidates = [r for r in rows[1:] if len(r) >= 3 and r[0].strip()]
                if len(candidates) != 1:
                    raise ValueError('Form 14 has no unique claimant. Review the claimant table.')
                r = candidates[0]
                out.update(family=clean_name(r[0]), family_dob=dt(r[1]).isoformat(), relationship=r[2].strip())
        elif kind == 'profile':
            labels = {norm(r[1]): r[2].strip() for r in rows[1:] if len(r) >= 3}
            if 'personaldetails' in heading:
                if labels.get('pponumber') != ppo:
                    raise ValueError('Migrated profile PPO does not match the requested case.')
                for label, key in [('pensionername','pensioner'), ('dateofbirth','pensioner_dob'), ('dateofdeathonlyincaseoffamilypension','death')]:
                    if labels.get(label):
                        out[key] = dt(labels[label]).isoformat() if key != 'pensioner' else clean_name(labels[label])
                _category(labels.get('paycommission'), out)
            elif 'familydetails' in heading:
                if labels.get('name'): out['family'] = clean_name(labels['name'])
                if labels.get('dateofbirth'): out['family_dob'] = dt(labels['dateofbirth']).isoformat()
                if labels.get('relationship'): out['relationship'] = labels['relationship']
            elif 'fmadetails' in heading:
                if labels.get('isfmaopted') == 'NO': out['fma_before'] = '0'
            elif 'pensiondetails' in heading:
                _category(labels.get('paycommission'), out)
                if labels.get('basicpension'): out['basic'] = labels['basicpension'].replace(',', '')
            elif heading.endswith('commutations'):
                amounts = {r[1].replace(',', '').strip() for r in rows[2:] if len(r) >= 3 and r[1].strip()}
                dates = {dt(r[2]).isoformat() for r in rows[2:] if len(r) >= 3 and r[2].strip()}
                if len(amounts) == 1: out['commuted'] = str(Decimal(next(iter(amounts))))
                if len(dates) == 1: out['commutation_restore'] = next(iter(dates))
                elif len(dates) > 1: notes.append('Conflicting migrated commutation restoration dates: ' + ', '.join(sorted(dates)))
    required = ('pensioner','death','family','family_dob') if kind == 'form14' else ('pensioner','pensioner_dob')
    missing = [key for key in required if not out.get(key)]
    if missing:
        raise ValueError(f'{kind}: required labelled fields not found: ' + ', '.join(missing))
    return out, notes


def _category(value, out):
    if value and value.strip().upper() in ('IDA', 'CDA'):
        if out.get('category') and out['category'] != value.strip().upper():
            raise ValueError('Conflicting explicit IDA/CDA fields in the same source.')
        out['category'] = value.strip().upper()


def gc_fields(headers, rows, ppo):
    indexes = {norm(h): i for i, h in enumerate(headers)}
    if 'ppono' not in indexes:
        raise ValueError('Commutation report PPO header is missing.')
    matches = [r for r in rows if len(r) == len(headers) and r[indexes['ppono']].strip() == ppo]
    if len(matches) != 1:
        raise ValueError('No unique matching commutation report row; review category/restoration.')
    row = matches[0]
    out = {'ppo': ppo}
    if 'pensiontype' in indexes: _category(row[indexes['pensiontype']], out)
    if 'dateofrestoration' in indexes and row[indexes['dateofrestoration']].strip():
        out['commutation_restore'] = dt(row[indexes['dateofrestoration']]).isoformat()
        if 'commutationpaymentdate' in indexes and row[indexes['commutationpaymentdate']].strip():
            paid=dt(row[indexes['commutationpaymentdate']])
            try:anniversary=paid.replace(year=paid.year+15)
            except ValueError:anniversary=paid.replace(year=paid.year+15,day=28)
            if out['commutation_restore']!=anniversary.isoformat():
                out['_notes']=[f'Manual review: report restoration {out["commutation_restore"]} differs from payment date {paid} + 15 years. Verify the authority; reported date retained without correction.']
    return out
