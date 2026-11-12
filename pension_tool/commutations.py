"""Progressive migrated amounts are totals, never amounts to add together."""
from .engine import D, dt


def progressive_parts(rows, source='Migrated One-Pager'):
    parts=[]; previous=D(0); last=None
    for amount, restoration in rows:
        total=D(str(amount).replace(',', '').strip()); day=dt(restoration)
        if not total.is_finite() or total < previous or (last and day <= last):
            raise ValueError('Review migrated commutations: progressive totals must not decrease and restoration dates must increase.')
        parts.append(dict(amount=str(total-previous), progressive=str(total), restore=day.isoformat(), source=source))
        previous=total; last=day
    return parts


def remaining(parts, on):
    total=D(0)
    for part in parts:
        amount=D(part['amount']); restored=dt(part['restore'])
        if not amount.is_finite() or amount < 0:
            raise ValueError('Commutation portion must be a non-negative amount.')
        if dt(on) < restored and (not part.get('effective') or dt(on)>=dt(part['effective'])): total+=amount
    return total


def original_rates(case, on):
    """Manual basic/deduction values explicitly supersede collected timelines."""
    basic, deduction=case.basic,case.commuted
    for revision in sorted(case.pay_revisions,key=lambda item: item['effective']):
        if dt(revision['effective']) > on: break
        if 'basic' not in case.manual_overrides: basic=D(revision.get('basic',basic))
        if 'commuted' not in case.manual_overrides: deduction=D(revision.get('commuted',deduction))
    if case.commutation_parts and not ({'commuted','commutation_restore'} & case.manual_overrides.keys()):
        deduction=remaining(case.commutation_parts,on)
    elif case.commutation_restore and on >= case.commutation_restore:
        deduction=D(0)
    return basic,deduction
