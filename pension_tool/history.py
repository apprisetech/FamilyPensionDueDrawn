"""Translate verified replacement/additional sanctions into dated deduction portions."""
from decimal import Decimal

def portions(events):
    replacements=sorted({e['effective'] for e in events if e.get('mode')=='replacement' and e.get('effective')})
    for effective in replacements:
        values={(str(Decimal(str(e['amount']))),e.get('restore')) for e in events if e.get('mode')=='replacement' and e.get('effective')==effective}
        if len(values)!=1:raise ValueError('Conflicting commutation replacements on '+effective)
    result=[]
    for event in events:
        if not event.get('effective'):
            raise ValueError('Commutation sanction needs a verified effective date.')
        amount=Decimal(str(event['amount']))
        if event.get('mode')=='additional' and not any(d<=event['effective'] for d in replacements):
            raise ValueError('Additional commutation requires a verified replacement baseline.')
        if amount and not event.get('restore'):
            raise ValueError('Commutation sanction needs a restoration date.')
        if amount<0 or not amount.is_finite():raise ValueError('Invalid sanction monthly deduction.')
        if not amount:continue
        stops=[date for date in replacements if date>event['effective']]
        restored=min([event['restore']]+stops)
        key=(event['effective'],str(amount),restored)
        if key not in {(p['effective'],p['amount'],p['restore']) for p in result}:
            result.append(dict(effective=event['effective'],amount=str(amount),restore=restored,source=event.get('source','Verified commutation sanction')))
    return result
