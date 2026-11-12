"""Source-independent pension timeline. No inferred dates, beneficiary or nil amounts."""
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP, ROUND_CEILING
from copy import deepcopy
import calendar
import re

D = lambda x: Decimal(str(x))
DAY = timedelta(days=1)

def day(x):
    return x if isinstance(x, date) else date.fromisoformat(str(x))

def end_month(x):
    return x.replace(day=calendar.monthrange(x.year, x.month)[1])

def quantum(dob, on):
    age = on.year - dob.year - (on.month < dob.month)
    return D(0 if age < 80 else '.2' if age < 85 else '.3' if age < 90 else '.4' if age < 95 else '.5' if age < 100 else 1)

def validate(model):
    if not re.fullmatch(r'\d{15}', str(model.get('ppo', ''))):
        raise ValueError('Enter the matching 15-digit PPO.')
    if day(model['start']) > day(model['end']):
        raise ValueError('Start must not be after end.')
    stages = model.get('stages', [])
    if not stages:
        raise ValueError('No verified pension stage. Review the saved authorities.')
    dates = [day(x['effective']) for x in stages]
    if len(set(dates)) != len(dates):
        raise ValueError('Conflicting pension stages have the same effective date.')
    if min(dates) > day(model['start']):
        raise ValueError('A verified pension stage must cover the starting date.')
    for stage in stages:
        if not stage.get('name') or stage.get('category') not in ('IDA', 'CDA'):
            raise ValueError('Verify each stage beneficiary and IDA/CDA category.')
        if day(stage['dob']) > day(stage['effective']):
            raise ValueError('Beneficiary DOB cannot follow their stage effective date.')
        for key in ('basic', 'commuted', 'fma'):
            value = D(stage[key])
            if not value.is_finite() or value < 0:
                raise ValueError(f'{key}: enter a verified non-negative amount, not blank.')
        if D(stage['commuted']) > D(stage['basic']):
            raise ValueError('Monthly commutation exceeds basic pension.')
        if stage.get('kind') == 'Family' and D(stage['commuted']):
            raise ValueError('Family pension cannot carry original pension commutation.')
        if D(stage['commuted']) and not stage.get('restore') and not model.get('parts'):
            raise ValueError('Verify the commutation restoration date or portion schedule.')
    for part in model.get('parts', []):
        if not D(part['amount']).is_finite() or D(part['amount']) < 0:
            raise ValueError('Invalid commutation portion.')
        day(part['restore'])

def allocate(payments, start, end):
    """Explicit reviewer allocation wins; March monthly paid in April is exceptional."""
    groups = {}; seen = set(); totals = {}; notes = []
    for p in payments:
        if not isinstance(p.get('include', True), bool):
            raise ValueError('Payment include must be true or false.')
        amount, arrear = D(p['gross']), D(p.get('separate_arrear', 0))
        if not amount.is_finite() or not arrear.is_finite():
            raise ValueError('Payment amounts must be finite.')
        key = str(p['paid_on']), p['bill_type'], amount, arrear
        if key in seen:
            raise ValueError('Duplicate payment rows need review; remove or reconcile copies.')
        seen.add(key)
        groups.setdefault(day(p['paid_on']).strftime('%Y-%m'), []).append(p)
    for month, group in groups.items():
        regular = sorted([p for p in group if p['bill_type'].strip().upper() == 'MONTHLY BILL'], key=lambda p: str(p['paid_on']))
        april = month.endswith('-04')
        pair = april and len(regular) == 2 and str(regular[0]['paid_on']) != str(regular[1]['paid_on'])
        if april and regular and not pair and not all(p.get('allocated_month') for p in regular):
            raise ValueError(f'{month}: review ambiguous April Monthly Bills and assign their months.')
        for p in group:
            assigned = p.get('allocated_month') or (month[:4]+'-03' if pair and p is regular[0] else month)
            if not re.fullmatch(r'\d{4}-(0[1-9]|1[0-2])', assigned):
                raise ValueError('Assigned month must be YYYY-MM.')
            if p.get('include', True) and str(start)[:7] <= assigned <= str(end)[:7]:
                totals[assigned] = totals.get(assigned, D(0)) + D(p['gross']) + D(p.get('separate_arrear', 0))
            if 'SUPPLEMENT' in p['bill_type'].upper() or 'ARREAR' in p['bill_type'].upper():
                notes.append(f"Review: {p['bill_type']} paid {p['paid_on']} assigned {assigned}.")
            p['_assigned_month'] = assigned
    return totals, notes

def calculate(model, rates):
    validate(model)
    start, end = day(model['start']), day(model['end'])
    stages = sorted(model['stages'], key=lambda s: day(s['effective']))
    paid, notes = allocate(model.get('payments', []), start, end)
    cursor = start; rows = []
    while cursor <= end:
        last = min(end_month(cursor), end); stop = last + DAY
        cuts = {cursor, stop}
        for stage in stages:
            for value in (stage['effective'], stage.get('restore')):
                if value and cursor < day(value) < stop:
                    cuts.add(day(value))
        for part in model.get('parts', []):
            for value in (part.get('effective'), part['restore']):
                if value and cursor < day(value) < stop: cuts.add(day(value))
        for rate in rates:
            for value in (day(rate['start']), day(rate['end']) + DAY):
                if cursor < value < stop: cuts.add(value)
        bounds = sorted(cuts)
        month_rows = []
        for first, following in zip(bounds, bounds[1:]):
            stage = next(s for s in reversed(stages) if day(s['effective']) <= first)
            matches = [r for r in rates if r['category'] == stage['category'] and day(r['start']) <= first and day(r['end']) >= following-DAY]
            if len(matches) != 1: raise ValueError(f"Missing/overlapping {stage['category']} DR for {first}.")
            fraction = D((following-first).days)/end_month(first).day
            basic = (D(stage['basic'])*fraction).quantize(D(1), rounding=ROUND_HALF_UP)
            comm = D(stage['commuted']) if not stage.get('restore') or first < day(stage['restore']) else D(0)
            if model.get('parts') and stage.get('kind') != 'Family' and not stage.get('commutation_override'):
                comm = sum((D(p['amount']) for p in model['parts'] if first < day(p['restore']) and (not p.get('effective') or first >= day(p['effective']))), D(0))
            if comm > D(stage['basic']): raise ValueError(f'Commutation exceeds basic on {first}.')
            comm *= fraction; extra = basic*quantum(day(stage['dob']), first)
            fma = D(stage['fma'])*fraction; rate = D(matches[0]['percent']); dr=(basic+extra)*rate/100
            due = basic-comm+extra+dr+fma
            month_rows.append(dict(start=first,end=following-DAY,basic=basic,comm=comm,reduced=basic-comm,quantum=extra,rate=rate,dr=dr,fma=fma,due=due,total=due.quantize(D(1),rounding=ROUND_CEILING),stage=stage,drawn=None,difference=None))
        month_rows[-1]['drawn'] = paid.get(cursor.strftime('%Y-%m'),D(0))
        month_rows[-1]['difference'] = sum(r['total'] for r in month_rows)-month_rows[-1]['drawn']
        rows += month_rows; cursor = stop
    return dict(rows=rows, due=sum(r['total'] for r in rows), drawn=sum((r['drawn'] or 0) for r in rows), notes=notes)

def previous_month_check(model,rates):
    """Only compare an independently identified full regular payment and covered baseline."""
    end=day(model['start']).replace(day=1)-DAY;start=end.replace(day=1)
    month=start.strftime('%Y-%m')
    payments=deepcopy(model.get('payments',[]))
    try:
        allocate(payments,start,end)
        matches=[p for p in payments if p.get('include',True) and p['bill_type'].strip().upper()=='MONTHLY BILL' and p['_assigned_month']==month]
        if len(matches)!=1 or D(matches[0].get('separate_arrear',0)):
            return f'{month}: gross cross-check unavailable; no unique full regular bill without separate arrear.'
        prior=deepcopy(model);prior.update(start=str(start),end=str(end),payments=[])
        expected=calculate(prior,rates)['due'];actual=D(matches[0]['gross'])
        return f'{month}: gross cross-check {"match" if actual==expected else "REVIEW"}; expected {expected}, actual {actual}, difference {actual-expected}.'
    except (ValueError,KeyError) as error:
        return f'{month}: gross cross-check unavailable: {error}'
