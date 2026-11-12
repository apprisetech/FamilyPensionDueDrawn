"""Resolve only source disagreements explained by an explicit dated revision."""
from .engine import D, dt
from .commutations import remaining


def resolve_timelines(data, sources, conflicts, candidates):
    events=[fields['_commutation_event'] for _,fields in candidates if fields.get('_commutation_event')]
    if events:
        from .history import portions
        try:
            computed=portions(events)
            if computed:candidates=list(candidates)+[('Verified commutation sanctions',{'_commutation_parts':computed})]
        except ValueError as error:conflicts.append(str(error))
    parts=[(name,fields['_commutation_parts']) for name,fields in candidates if fields.get('_commutation_parts')]
    if len(parts)==1:
        name,values=parts[0]
        data['commutation_parts']=[dict(p,source=name) for p in values]
        if data.get('effective'):
            from datetime import timedelta
            on=dt(data['effective'])-timedelta(days=1)
            data['commuted']=str(remaining(values,on))
            active=[p for p in values if D(p['amount']) and dt(p['restore'])>on]
            data['commutation_restore']=max((p['restore'] for p in active),default='')
            conflicts=[n for n in conflicts if not n.startswith(('Conflicting commuted:', 'Conflicting commutation_restore:'))]
    elif len(parts)>1:
        raise ValueError('Multiple migrated commutation tables found. Review the matching One-Pager.')
    if not data.get('basic') and data.get('effective'):
        profile={D(f['basic']) for _,f in candidates if f.get('_commutation_parts') and f.get('basic')}
        originals={D(f['basic']) for name,f in candidates if name.lower().endswith('.pdf') and f.get('basic') and not f.get('_pay_revision')}
        revisions=sorted((r for r in data.get('pay_revisions',[]) if dt(r['effective'])<dt(data['effective'])),key=lambda r:r['effective'])
        if len(profile)==len(originals)==1 and revisions and D(revisions[-1]['basic']) in profile:
            known=profile|originals
            if all(D(value) in known for value,_ in sources.get('basic',[])):
                data['basic']=str(next(iter(originals)))
                conflicts=[n for n in conflicts if not n.startswith('Conflicting basic:')]
    return conflicts
