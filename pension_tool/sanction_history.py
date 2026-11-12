"""Extract dated monthly deductions from labelled SAMPANN sanctions."""
from datetime import datetime
from decimal import Decimal
import re


def iso(raw):
    return datetime.strptime(raw, '%d/%m/%Y').date().isoformat()


def extract_order(text, ppo, source):
    identity = set(re.findall(r'\bP\.?\s*P\.?\s*O\.?\s*(?:NUMBER|NO\.?)\s*[:\-]?\s*(\d{15})', text, re.I))
    if identity != {ppo}:
        return None, [f'{source}: matching PPO is missing or ambiguous.']
    flat = ' '.join(text.split())
    if re.search(r'Conversion into Family Pension|Authority for Pay related Correction', flat, re.I):
        return None, []
    gross = re.findall(r'^\s*(?:\d+\.?\s+)?Gross Pension\s+([\d,.]+)\s+([\d,.]+)(?=\s|$)', text, re.I | re.M)
    reduced = re.findall(r'^\s*(?:\d+\.?\s+)?Reduced Pension after commutation\s+([\d,.]+)\s+([\d,.]+)(?=\s|$)', text, re.I | re.M)
    notes = []
    if len(gross) == len(reduced) == 1:
        header = re.search(r'(Revised Amount)\s+(?:Previous Amount|Amount already authorized)|(?:Previous Amount|Amount already authorized)\s+(Revised Amount)', flat, re.I)
        if not header:
            return None, [f'{source}: monthly deduction columns need review.']
        revised = 0 if header.group(1) else 1
        amounts = [Decimal(g.replace(',', '')) - Decimal(r.replace(',', '')) for g,r in zip(gross[0], reduced[0])]
        if min(amounts) < 0:
            return None, [f'{source}: reduced pension exceeds gross pension.']
        dates = set(re.findall(r'\bw\s*\.\s*e\s*\.\s*f\s*\.?\s*(\d{1,2}/\d{1,2}/\d{4})', text, re.I))
        restoration_rows = re.findall(r'Date of Restoration of (?:commutation|Pension)\s+([^\n]+)', text, re.I)
        restore_dates = set(re.findall(r'\d{1,2}/\d{1,2}/\d{4}', ' '.join(restoration_rows)))
        restore = iso(next(iter(restore_dates))) if len(restore_dates) == 1 else None
        event = dict(source=source, mode='replacement', amount=str(amounts[revised]),
                     previous=str(amounts[1-revised]), effective=iso(next(iter(dates))) if len(dates)==1 else None,
                     restore=restore)
        if re.search(r'additional commutation', flat, re.I):
            event['mode'] = 'additional'
            event['amount'] = str(amounts[revised] - amounts[1-revised])
            if Decimal(event['amount']) <= 0:
                notes.append(f'{source}: additional commutation does not show a positive added portion.')
        if not event['effective']:
            notes.append(f'{source}: monthly deduction {event["previous"]} to {event["amount"]}, but no unique w.e.f. date.')
        if Decimal(event['amount']) and not restore:
            notes.append(f'{source}: restoration date for monthly deduction is unresolved.')
        return event, notes
    # Original PPO uses labelled single amounts and commencement of reduced pension.
    before = re.findall(r'Amount of monthly pension before commutation\s+Rs\.?\s*([\d,.]+)', text, re.I)
    after = re.findall(r'Reduced monthly pension after commutation\s+Rs\.?\s*([\d,.]+)', text, re.I)
    if len(before) == len(after) == 1:
        amount = Decimal(before[0].replace(',', ''))-Decimal(after[0].replace(',', ''))
        label = 'Date of commencement of reduced pension' if amount else 'Date of commencement of pension'
        starts = re.findall(label+r'\s+(\d{1,2}/\d{1,2}/\d{4})', text, re.I)
        restore_dates = re.findall(r'commuted portion shall stand restored[^\n]*\n\s*(\d{1,2}/\d{1,2}/\d{4})', text, re.I)
        event = dict(source=source, mode='replacement', amount=str(amount), previous=None,
                     effective=iso(starts[0]) if len(starts)==1 else None,
                     restore=iso(restore_dates[0]) if len(restore_dates)==1 else None)
        if amount < 0 or not event['effective'] or (amount and not event['restore']):
            notes.append(f'{source}: original monthly deduction needs effective/restoration date review.')
        return event, notes
    if re.search(r'commutation claimed|revision on account of commutation', flat, re.I):
        notes.append(f'{source}: commutation authority has no unique monthly deduction row.')
    return None, notes


def total_on(events, on):
    eligible = [event for event in events if event.get('effective') and event['effective'] <= str(on)]
    replacements = [event for event in eligible if event['mode'] == 'replacement']
    if not replacements:
        raise ValueError(f'No verified commutation baseline for {on}.')
    latest = max(event['effective'] for event in replacements)
    current = [event for event in replacements if event['effective']==latest]
    if len({(event['amount'],event.get('restore')) for event in current}) != 1:
        raise ValueError(f'Conflicting monthly commutation totals effective {latest}.')
    event = current[0]
    amount = Decimal(event['amount']) if not event.get('restore') or str(on)<event['restore'] else Decimal(0)
    additions = [event for event in eligible if event['mode']=='additional' and event['effective'] >= latest]
    # Identical PDF copies are one authority, not repeated deductions.
    seen = set()
    for event in additions:
        key = (event['effective'],event['amount'],event.get('restore'))
        if key in seen:
            continue
        seen.add(key)
        if not event.get('restore') or str(on)<event['restore']:
            amount += Decimal(event['amount'])
    return amount
