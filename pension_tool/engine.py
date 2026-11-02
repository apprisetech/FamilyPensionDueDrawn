"""Deterministic due/drawn engine. No browser, OCR or network access here."""
from dataclasses import dataclass, field, asdict
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP, ROUND_CEILING
import calendar, re

D = lambda v: Decimal(str(v))
def dt(v):
    if isinstance(v, datetime): return v.date()
    if isinstance(v, date): return v
    for fmt in ('%Y-%m-%d','%d/%m/%Y','%d-%m-%Y'):
        try: return datetime.strptime(str(v).strip(),fmt).date()
        except ValueError: pass
    raise ValueError(f'Invalid date: {v}. Use YYYY-MM-DD.')
def previous_month(today=None): return (today or date.today()).replace(day=1)-timedelta(days=1)
def month_end(d): return d.replace(day=calendar.monthrange(d.year,d.month)[1])
def next_month(d): return month_end(d)+timedelta(days=1)
def quantum(dob, on):
    # Age slab starts on the first day of the month of the completed birthday.
    age=on.year-dob.year-(on.month<dob.month)
    return D(0 if age<80 else '.2' if age<85 else '.3' if age<90 else '.4' if age<95 else '.5' if age<100 else 1)

@dataclass
class Rate:
    start: date
    end: date
    percent: Decimal
    category: str

@dataclass
class Payment:
    paid_on: date
    bill_type: str
    gross: Decimal
    separate_arrear: Decimal=D(0)
    allocated_month: str=''
    include: bool=True

@dataclass
class Case:
    ppo: str
    pensioner: str
    family: str
    pensioner_dob: date
    family_dob: date
    death: date
    effective: date
    category: str
    basic: Decimal
    enhanced: Decimal
    enhanced_until: date
    normal: Decimal
    normal_from: date
    commuted: Decimal
    fma_before: Decimal
    fma_after: Decimal
    account: str
    ifsc: str
    commutation_restore: date|None=None
    fma_overrides: dict=field(default_factory=dict)
    notes: list=field(default_factory=list)

    @classmethod
    def from_dict(cls, values):
        data=dict(values)
        for key in ('pensioner_dob','family_dob','death','effective','enhanced_until','normal_from'):
            data[key]=dt(data[key])
        data['commutation_restore']=dt(data['commutation_restore']) if data.get('commutation_restore') else None
        for key in ('basic','enhanced','normal','commuted','fma_before','fma_after'): data[key]=D(data[key])
        c=cls(**{k:v for k,v in data.items() if k in cls.__dataclass_fields__});c.validate();return c

    def validate(self):
        if not re.fullmatch(r'\d{15}',self.ppo): raise ValueError('PPO must contain exactly 15 digits.')
        if not self.pensioner.strip() or not self.family.strip(): raise ValueError('Both names are required.')
        if self.category not in ('IDA','CDA'): raise ValueError('Select IDA or CDA explicitly.')
        if not re.fullmatch(r'[A-Z]{4}0[A-Z0-9]{6}',self.ifsc): raise ValueError('IFSC must be 11 characters, including zero at position 5.')
        if not re.fullmatch(r'\d{6,25}',self.account): raise ValueError('Verify the complete bank account number.')
        if self.effective<=self.death: raise ValueError('Conversion effective date must be after the recorded death date; review order.')
        if self.normal_from!=self.enhanced_until+timedelta(days=1): raise ValueError('Enhanced end and normal start must be consecutive dates.')
        if self.pensioner_dob>self.death or self.family_dob>self.effective: raise ValueError('Invalid date of birth.')
        for key in ('basic','enhanced','normal','commuted','fma_before','fma_after'):
            if getattr(self,key)<0: raise ValueError(f'{key} cannot be negative.')
        if self.commuted>self.basic: raise ValueError('Commuted portion exceeds original basic pension.')
        if self.commuted and not self.commutation_restore and self.effective.day>1:
            raise ValueError('Commutation restoration date required for the original-pension part of the conversion month.')

def allocate(payments, start, end):
    """First of exactly two April regular bills belongs to March; other payments keep paid month."""
    # Duplicate rows must be reviewed, never silently deduplicated.
    groups={}; notes=[]; totals={}; seen=set()
    for p in payments:
        if not isinstance(p.include,bool):raise ValueError('Payment include must be JSON true or false.')
        if p.gross<0:raise ValueError('Negative payment gross needs manual reconciliation; do not silently treat it as Drawn.')
        key=(p.paid_on,p.bill_type,p.gross,p.separate_arrear)
        if key in seen: raise ValueError('Duplicate payment rows found. Review the payment report before export.')
        seen.add(key);groups.setdefault((p.paid_on.year,p.paid_on.month),[]).append(p)
    for (y,m),group in sorted(groups.items()):
        regular=sorted([p for p in group if p.bill_type.upper().strip()=='MONTHLY BILL'],key=lambda p:p.paid_on)
        april_pair=m==4 and len(regular)==2 and regular[0].paid_on!=regular[1].paid_on
        if m==4 and regular and not april_pair:
            if not all(p.allocated_month for p in regular):
                raise ValueError(f'{y}-04: expected two April Monthly Bills. Set explicit allocated_month for each regular bill.')
        if len(group)>1 and not (april_pair and len(group)==2):
            notes.append(f'Manual review: {y}-{m:02d} has {len(group)} payments: '+ '; '.join(f'{p.paid_on:%d-%m-%Y} {p.bill_type} Rs {p.gross}' for p in group))
        for p in group:
            assigned=p.allocated_month or (f'{y}-03' if april_pair and p is regular[0] else f'{y}-{m:02d}')
            if not re.fullmatch(r'\d{4}-(0[1-9]|1[0-2])',assigned): raise ValueError('allocated_month must be YYYY-MM.')
            if p.separate_arrear:
                notes.append(f'Pending for manual review: separate arrear Rs {p.separate_arrear} paid on {p.paid_on:%d-%m-%Y}; covered period not allocated; excluded from Drawn.')
            if 'SUPPLEMENT' in p.bill_type.upper() or 'ARREAR' in p.bill_type.upper():
                notes.append(f'Manual review: {p.paid_on:%d-%m-%Y} {p.bill_type}, Rs {p.gross}, included in {assigned} Drawn.' if p.include else f'Manual review: {p.paid_on:%d-%m-%Y} {p.bill_type} excluded by reviewer.')
            if p.include and start.strftime('%Y-%m')<=assigned<=end.strftime('%Y-%m'):
                totals[assigned]=totals.get(assigned,D(0))+p.gross
    return totals,notes

def calculate(c, rates, payments, end=None):
    c.validate();end=dt(end) if end else previous_month()
    if end>previous_month(): raise ValueError('Calculation cannot include the current or a future month.')
    if end!=month_end(end): raise ValueError('End date must be a month-end date.')
    first=c.effective.replace(day=1)
    if first>end: raise ValueError('No completed month to calculate yet.')
    drawn,notes=allocate(payments,first,end);notes=list(c.notes)+notes;rows=[]
    cursor=first
    while cursor<=end:
        last=month_end(cursor);stop=last+timedelta(days=1)
        cuts={cursor,stop}
        for boundary in (c.effective,c.normal_from,c.commutation_restore):
            if boundary and cursor<boundary<stop:cuts.add(boundary)
        for r in rates:
            if r.category==c.category:
                for boundary in (r.start,r.end+timedelta(days=1)):
                    if cursor<boundary<stop:cuts.add(boundary)
        cuts=sorted(cuts);month_rows=[]
        if cursor<c.effective<=last and c.fma_before!=c.fma_after and cursor.strftime('%Y-%m') not in c.fma_overrides:
            raise ValueError('FMA changes within conversion month. Enter full-month FMA override in case JSON; no partial FMA will be used.')
        fma=D(c.fma_overrides.get(cursor.strftime('%Y-%m'),c.fma_before if cursor<c.effective else c.fma_after))
        for a,b_excl in zip(cuts,cuts[1:]):
            b=b_excl-timedelta(days=1);original=a<c.effective
            base=c.basic if original else c.enhanced if a<=c.enhanced_until else c.normal
            fraction=D((b-a).days+1)/D(last.day)
            basic=(base*fraction).quantize(D(1),rounding=ROUND_HALF_UP)
            comm=c.commuted*fraction if original and (not c.commutation_restore or a<c.commutation_restore) else D(0)
            addl=basic*quantum(c.pensioner_dob if original else c.family_dob,a)
            match=[r for r in rates if r.category==c.category and r.start<=a and r.end>=b]
            if len(match)!=1: raise ValueError(f'{c.category} DR missing or overlapping for {a} to {b}. Update DR_Master.')
            rate=match[0].percent;dr=(basic+addl)*rate/100
            due=basic-comm+addl+dr
            full_fma=fma if not month_rows else D(0)
            total=(due+full_fma).quantize(D(1),rounding=ROUND_CEILING)
            month_rows.append(dict(start=a,end=b,original=original,basic=basic,comm=comm,reduced=basic-comm,quantum=addl,rate=rate,dr=dr,due=due,fma=full_fma,total=total,drawn=None,difference=None))
        month_drawn=drawn.get(cursor.strftime('%Y-%m'),D(0))
        month_rows[0]['drawn']=month_drawn;month_rows[0]['difference']=sum(x['total'] for x in month_rows)-month_drawn
        rows.extend(month_rows);cursor=next_month(cursor)
    total=sum(x['total'] for x in rows);paid=sum((x['drawn'] or D(0)) for x in rows)
    return dict(rows=rows,due=total,drawn=paid,difference=total-paid,notes=list(dict.fromkeys(notes)),end=end)

def load_rates(path):
    from openpyxl import load_workbook
    wb=load_workbook(path,data_only=True);result=[]
    aliases={'start':('from','fromdate','start','startdate','effectivefrom'),'end':('to','todate','end','enddate','effectiveto'),'rate':('rate','drrate','dr','percentage','drpercentage'),'category':('category','type','regime')}
    for s in wb:
        regime='IDA' if 'IDA' in s.title.upper() else 'CDA' if 'CDA' in s.title.upper() else None
        header=None
        for row in s.iter_rows(min_row=1,max_row=min(15,s.max_row)):
            lookup={re.sub(r'[^a-z]','',str(c.value).lower()):c.column for c in row if c.value is not None}
            mapped={key:next((lookup[a] for a in opts if a in lookup),None) for key,opts in aliases.items()}
            if all(mapped[k] for k in ('start','end','rate')):header=(row[0].row,mapped);break
        if not header:continue
        for row in s.iter_rows(min_row=header[0]+1):
            vals=lambda k:row[header[1][k]-1] if header[1][k] else None
            if not vals('start').value:continue
            cat=str(vals('category').value).upper().strip() if vals('category') and vals('category').value else regime
            if cat not in ('IDA','CDA'):raise ValueError(f'{s.title}: category required.')
            cell=vals('rate');raw=cell.value
            percent=D(str(raw).replace('%',''))
            if '%' not in str(raw) and '%' in cell.number_format:percent*=100
            if raw is None or percent<0:raise ValueError('Invalid DR rate.')
            result.append(Rate(dt(vals('start').value),dt(vals('end').value),percent,cat))
    if not result:raise ValueError('DR_Master needs From Date, To Date, Rate headers, with IDA/CDA sheet names or Category column. Use Excel percent cells or explicit whole rates, e.g. 241.7.')
    return result
