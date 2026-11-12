"""Read labelled revision tables and compare independent regular bills."""
import re
from .engine import D, dt

def pay_revision(text):
    """Return a dated original-pension change, or None for other orders."""
    if not re.search(r'revision on account of change in pay|authority for pay related correction\s*/\s*revision', ' '.join(text.split()), re.I):
        return None
    dates = set(re.findall(r'\bw\s*\.\s*e\s*\.\s*f\s*\.?\s*(\d{1,2}[/-]\d{1,2}[/-]\d{4})', text, re.I))
    if len(dates) != 1:
        raise ValueError('Pay revision needs one verified effective date.')
    header = re.search(r'(revised\s+amount)\s+(previous\s+amount|amount\s+already\s+authorized)|(previous\s+amount|amount\s+already\s+authorized)\s+(revised\s+amount)', text, re.I)
    if header:
        column = 0 if header.group(1) else 1
    else:
        # Some authorities wrap all column titles before the Amount labels.
        split_header = re.search(
            r'\b(previous|revised)\s+(previous|revised)\s+difference'
            r'[^\d]{0,100}\bamount\s+amount\s+amount\b',
            ' '.join(text.split()), re.I)
        if not split_header or split_header.group(1).lower() == split_header.group(2).lower():
            raise ValueError('Review pay revision amount columns.')
        column = 0 if split_header.group(1).lower() == 'revised' else 1

    def amount(label, required=False):
        matches = re.findall(label + r'\s+([\d,]+(?:\.\d+)?)\s+([\d,]+(?:\.\d+)?)', text, re.I)
        if len(matches) > 1 or (required and not matches):
            raise ValueError('Review ambiguous or missing revised pension row.')
        return D(matches[0][column].replace(',', '')) if matches else None

    basic = amount(r'\b(?:gross\s+pension|revised\s+pension)', True)
    reduced = amount(r'\breduced\s+pension\s+after\s+commutation')
    if basic <= 0 or (reduced is not None and not 0 <= reduced <= basic):
        raise ValueError('Review inconsistent revision amounts.')
    result = {'effective': dt(next(iter(dates))).isoformat(), 'basic': str(basic)}
    if reduced is not None:
        result['commuted'] = str(basic - reduced)
    return result


def compare_regular_gross(expected, verified_regular_gross):
    """Caller must verify the pension month and exclude mixed/partial bills."""
    if verified_regular_gross is None:
        return {'status': 'unavailable'}
    expected, actual = D(expected), D(verified_regular_gross)
    return {'status': 'match' if expected == actual else 'review',
            'expected': str(expected), 'actual': str(actual),
            'difference': str(actual - expected)}


def previous_month_check(case, rates, verified_gross):
    from .engine import calculate, previous_month
    end = previous_month(case.effective if case.conversion_history else case.death)
    month = end.strftime('%Y-%m')
    if verified_gross is None:
        return f'{month}: Cross-check unavailable. No verified full regular bill supplied.'
    if not verified_gross.is_finite() or verified_gross < 0:
        raise ValueError('Enter a valid non-negative gross amount.')
    expected = calculate(case, rates, [], end, verification_month=end.replace(day=1))['due']
    result = compare_regular_gross(expected, verified_gross)
    return (f"{month}: Gross cross-check {result['status']}. Expected {result['expected']}, "
            f"verified regular gross {result['actual']}, difference (actual minus expected) {result['difference']}.")


def regular_gross_from_history(payments, month):
    """Use the same regular-bill allocation convention as Drawn."""
    from datetime import date
    from .engine import month_end
    target = month.strftime('%Y-%m')
    matches = []
    april = sorted((p for p in payments if p.paid_on.year == month.year
                    and p.paid_on.month == 4 and p.bill_type.strip().upper() == 'MONTHLY BILL'),
                   key=lambda p: p.paid_on)
    if month.month in (3, 4) and april and not all(p.allocated_month for p in april):
        if len(april) != 2 or april[0].paid_on == april[1].paid_on:
            return None
    for payment in payments:
        if payment.bill_type.strip().upper() != 'MONTHLY BILL':
            continue
        assigned = payment.allocated_month or payment.paid_on.strftime('%Y-%m')
        if len(april) == 2 and payment is april[0] and not payment.allocated_month:
            assigned = f'{month.year}-03'
        if assigned == target:
            matches.append(payment)
    if len(matches) != 1 or not matches[0].include or matches[0].separate_arrear:
        return None
    return matches[0].gross
