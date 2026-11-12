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
    pay_revisions: list=field(default_factory=list)
    conversion_history: list=field(default_factory=list)
    previous_family_dob: str=""
    commutation_parts: list=field(default_factory=list)
    manual_overrides: dict=field(default_factory=dict)

    @classmethod
    def from_dict(cls, values):
        data=dict(values)
        for key in ('pensioner_dob','family_dob','death','effective','enhanced_until','normal_from'):
            try: data[key]=dt(data.get(key,''))
            except ValueError: raise ValueError(f'{key.replace("_", " ").title()}: enter a valid date (YYYY-MM-DD).') from None
        data['commutation_restore']=dt(data['commutation_restore']) if data.get('commutation_restore') else None
        for key in ('basic','enhanced','normal','commuted','fma_before','fma_after'):
            try:
                data[key]=D(data.get(key,''))
                if not data[key].is_finite(): raise ValueError()
            except (ValueError,ArithmeticError):
                raise ValueError(f'{key.replace("_", " ").title()}: enter a valid amount; use 0 only when verified as zero.') from None
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
        if self.commutation_parts:
            from .commutations import remaining
            remaining(self.commutation_parts,self.death)
        if self.commuted and not self.commutation_restore and self.effective.day>1 and not self.commutation_parts:
            raise ValueError('Commutation restoration date required for the original-pension part of the conversion month.')

def allocate(payments, start, end):
    """First of exactly two April regular bills belongs to March; other payments keep paid month."""
    # Duplicate rows must be reviewed, never silently deduplicated.
    groups={}; notes=[]; totals={}; seen=set()
    for p in payments:
        if not isinstance(p.include,bool):raise ValueError('Payment include must be JSON true or false.')
        if not D(p.gross).is_finite() or not D(p.separate_arrear).is_finite():raise ValueError('Payment amounts must be finite.')
        if p.gross<0 or p.separate_arrear<0:notes.append('Review signed payment/recovery adjustment: '+str(p.paid_on))
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
            amount = p.gross + p.separate_arrear
            if 'SUPPLEMENT' in p.bill_type.upper() or 'ARREAR' in p.bill_type.upper():
                notes.append(f'Manual review: {p.paid_on:%d-%m-%Y} {p.bill_type}, Rs {p.gross}, included in {assigned} Drawn.' if p.include else f'Manual review: {p.paid_on:%d-%m-%Y} {p.bill_type} excluded by reviewer.')
            if p.include and start.strftime('%Y-%m')<=assigned<=end.strftime('%Y-%m'):
                totals[assigned]=totals.get(assigned,D(0))+amount
    return totals,notes

def calculate(c, rates, payments, end=None, *, verification_month=None):
    from .commutations import original_rates
    c.validate();end=dt(end) if end else previous_month()
    if end>previous_month(): raise ValueError('Calculation cannot include the current or a future month.')
    if end!=month_end(end): raise ValueError('End date must be a month-end date.')
    first=verification_month or c.effective.replace(day=1)
    if first>end: raise ValueError('No completed month to calculate yet.')
    drawn,notes=allocate(payments,first,end);notes=list(c.notes)+notes;rows=[]
    revisions={}
    for change in c.pay_revisions:
        day=dt(change["effective"])
        amounts={k:D(change[k]) for k in ("basic","commuted") if k in change}
        if day in revisions and revisions[day]!=amounts:
            raise ValueError("Conflicting pay revisions on the same effective date.")
        revisions[day]=amounts
    earlier = c.conversion_history[:-1]
    if c.conversion_history:
        dates = [dt(order['effective']) for order in c.conversion_history]
        if dates != sorted(set(dates)) or dates[-1] != c.effective:
            raise ValueError('Review conversion history and latest effective date.')
        if first < dates[0].replace(day=1):
            raise ValueError('No family sanction covers the requested verification month.')
    def preceding_order(day):
        return next((order for order in reversed(earlier) if dt(order['effective']) <= day), None)

    cursor=first
    while cursor<=end:
        last=month_end(cursor);stop=last+timedelta(days=1)
        cuts={cursor,stop}
        if not ({'commuted','commutation_restore'} & c.manual_overrides.keys()):
            cuts.update(dt(p[key]) for p in c.commutation_parts for key in ('effective','restore') if p.get(key) and cursor<dt(p[key])<min(stop,c.effective))
        restoration = c.commutation_restore if c.commuted and c.commutation_restore and c.commutation_restore < c.effective else None
        for boundary in (c.effective,c.normal_from,restoration):
            if boundary and cursor<boundary<stop:cuts.add(boundary)
        for r in rates:
            if r.category==c.category:
                for boundary in (r.start,r.end+timedelta(days=1)):
                    if cursor<boundary<stop:cuts.add(boundary)
        cuts.update(day for day in revisions if cursor<day<min(stop,c.effective))
        for order in earlier:
            for boundary in (dt(order['effective']), dt(order['normal_from'])):
                if cursor < boundary < min(stop, c.effective):
                    cuts.add(boundary)
        cuts=sorted(cuts);month_rows=[]
        death_month = cursor == c.death.replace(day=1)
        before_fma = death_month or cursor < c.effective
        fma = c.fma_before if before_fma else c.fma_after
        month_order = preceding_order(cursor) if cursor < c.effective else None
        if month_order:
            fma = D(month_order['fma_after'])
        for a,b_excl in zip(cuts,cuts[1:]):
            b=b_excl-timedelta(days=1);original=a<c.effective
            prior = preceding_order(a) if original else None
            original = original and prior is None
            dob = c.pensioner_dob if original else c.family_dob
            base=c.basic if original else c.enhanced if a<=c.enhanced_until else c.normal
            if prior:
                source_dob = (c.previous_family_dob if prior is earlier[-1] else '') or prior.get('dob')
                if not source_dob:
                    raise ValueError(f"Verify the DOB of preceding family pensioner {prior['family']} before calculating {a}.")
                dob = dt(source_dob)
                if dob > dt(prior['effective']):
                    raise ValueError('Preceding family pensioner DOB is after their sanction effective date.')
                base = D(prior['enhanced'] if a < dt(prior['normal_from']) else prior['normal'])

            deduction=c.commuted
            if original:
                base,deduction=original_rates(c,a)
                if not 0<=deduction<=base:
                    raise ValueError("Revised commutation exceeds basic pension.")
            fraction=D((b-a).days+1)/D(last.day)
            basic=(base*fraction).quantize(D(1),rounding=ROUND_HALF_UP)
            comm=deduction*fraction if original else D(0)
            addl=basic*quantum(dob,a)
            match=[r for r in rates if r.category==c.category and r.start<=a and r.end>=b]
            if len(match)!=1: raise ValueError(f'{c.category} DR missing or overlapping for {a} to {b}. Update DR_Master.')
            rate=match[0].percent;dr=(basic+addl)*rate/100
            due=basic-comm+addl+dr
            monthly_fma = D(prior['fma_after']) if prior else c.fma_before if original else c.fma_after
            monthly_fma = D(c.fma_overrides.get(a.strftime('%Y-%m'), monthly_fma))
            full_fma=monthly_fma*fraction
            due += full_fma
            total=due.quantize(D(1),rounding=ROUND_CEILING)
            month_rows.append(dict(start=a,end=b,original=original,prior=prior,dob=dob,prior_fma=prior,base=base,deduction=deduction,basic=basic,comm=comm,reduced=basic-comm,quantum=addl,rate=rate,dr=dr,due=due,fma=full_fma,fma_monthly=monthly_fma,fma_cell=17 if original else 22,total=total,drawn=None,difference=None))
        month_drawn=drawn.get(cursor.strftime('%Y-%m'),D(0))
        month_rows[0]['drawn']=month_drawn;month_rows[0]['difference']=sum(x['total'] for x in month_rows)-month_drawn
        rows.extend(month_rows);cursor=next_month(cursor)
    total=sum(x['total'] for x in rows);paid=sum((x['drawn'] or D(0)) for x in rows)
    return dict(payments=payments,rows=rows,due=total,drawn=paid,difference=total-paid,notes=list(dict.fromkeys(notes)),end=end)

def load_rates(path):
    from openpyxl import load_workbook
    wb=load_workbook(path,data_only=True);result=[]
    aliases={'start':('from','fromdate','start','startdate','effectivefrom'),'end':('to','todate','end','enddate','effectiveto'),'rate':('rate','drrate','dr','percentage','drpercentage','idr','cdr'),'category':('category','type','regime')}
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
