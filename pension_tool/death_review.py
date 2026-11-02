"""Compare independent recorded death dates with conversion w.e.f. minus one day."""
from datetime import timedelta
from .engine import dt

PREFIX='Date of Death review:'

def reconcile(effective, records, selected=''):
    clean=[]
    for value,source in records:
        row=(dt(value).isoformat(),str(source))
        if row not in clean:clean.append(row)
    expected=(dt(effective)-timedelta(days=1)).isoformat() if effective else ''
    dates={v for v,_ in clean}
    status='missing_effective' if not expected else 'missing_record' if not clean else 'match' if dates=={expected} else 'conflict' if len(dates)>1 else 'mismatch'
    details='; '.join(f'{v} [{source}]' for v,source in clean) or 'not available'
    notes=[]
    if status not in ('match','missing_effective'):
        reason={'missing_record':'Recorded Date of Death not available','mismatch':'Date of Death mismatch','conflict':'Conflicting recorded death dates'}[status]
        notes=[f'{PREFIX} {reason} — Pending for manual review. Expected (conversion w.e.f. minus 1 day): {expected}; recorded: {details}.']
    if status=='match' and selected and dt(selected).isoformat()!=expected:
        notes=[f'{PREFIX} Selected death date differs from the matching source dates — Pending for manual review. Expected and recorded: {expected}; selected: {selected}.']
    accepted=status=='match' and (not selected or dt(selected).isoformat()==expected)
    signature=(expected,tuple(clean),dt(selected).isoformat() if selected else '')
    return dict(status=status,expected=expected,records=clean,details=details,notes=notes,accepted=accepted,signature=signature)

def signature_key(state):
    import json
    return json.dumps(state['signature'],ensure_ascii=False)
