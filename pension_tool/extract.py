"""Text-first local PDF extraction. OCR is an optional local fallback."""
from pathlib import Path
import re
from .engine import dt, D
from .sources import clean_name

def read_pdf(path, ocr=False):
    import fitz
    pages=[];used=False
    with fitz.open(path) as doc:
        for page in doc:
            text=page.get_text('text',sort=True)
            if len(re.sub(r'\s','',text))<50:
                if not ocr: raise ValueError(f'{Path(path).name}, page {page.number+1}: scanned PDF. Enable local OCR or import a readable PDF.')
                try:
                    from rapidocr_onnxruntime import RapidOCR
                    import numpy as np
                    pix=page.get_pixmap(matrix=fitz.Matrix(2,2),alpha=False)
                    img=np.frombuffer(pix.samples,dtype=np.uint8).reshape(pix.height,pix.width,pix.n)
                    result,_=RapidOCR()(img)
                    if not result:raise ValueError('No readable OCR text')
                    text='\n'.join(x[1] for x in result);used=True
                except ImportError as e:raise ValueError('Install optional OCR with INSTALL_OCR.bat first.') from e
            pages.append(text)
    return '\n\n'.join(pages),used

DATE=r'(\d{1,2}[/-]\d{1,2}[/-]\d{4}|\d{4}-\d{2}-\d{2})'
MONEY=r'(?:Rs\.?|INR|₹)?\s*([\d,]+(?:\.\d{1,2})?)'

def parse_text(text, kind='conversion'):
    text=text.replace('\xa0',' ');out={}
    def pick(key,pattern,convert=str):
        matches=list(re.finditer(pattern,text,re.I))
        values=[]
        for m in matches:
            try:v=convert(m.group(1).strip())
            except (ValueError,TypeError):continue
            if v not in values:values.append(v)
        if len(values)==1:out[key]=values[0]
        return values
    pick('ppo',r'P\.?\s*P\.?\s*O\.?\s*(?:NUMBER|NO\.?)\s*[:\-]?\s*(\d{15})')
    issued = re.search(r'\bDATED\s*[:\-]?\s*'+DATE,text,re.I)
    if issued:
        out['_issued_date'] = dt(issued.group(1)).isoformat()
    if kind=='conversion':
        if not re.search(r'conversion\s+(?:in)?to\s+family\s+pension|updation\s+of\s+pensioner|absorption',text,re.I):
            return {},['Not identified as a conversion/updation/absorption order.']
        pick('effective',r'(?:w\.?\s*e\.?\s*f\.?|with\s+effect\s+from)\s*[:\-]?\s*'+DATE,lambda s:dt(s).isoformat())
        # The main effective date may be followed by a separate normal-rate date.
        lead=re.search(r'consequent[\s\S]{0,700}?(?:w\.?\s*e\.?\s*f\.?)\s*[:\-]?\s*'+DATE,text,re.I)
        if lead:out['effective']=dt(lead.group(1)).isoformat()
        pick('family',r'name\s+of\s+family\s+pensioner\s*[:\-]?\s*(?:Mrs\.?|Mr\.?|Ms\.?)?\s*([^\n:]+)')
        pick('enhanced',r'(?:family\s+pension\s+)?enhanced\s*(?:family\s*pension\s*)?rate\s*[:\-]?\s*'+MONEY,lambda x:x.replace(',',''))
        pick('enhanced_until',r'up\s*to\s*[:\-]?\s*'+DATE,lambda s:dt(s).isoformat())
        pick('normal',r'normal\s*(?:family\s*pension\s*)?rate\s*[:\-]?\s*'+MONEY,lambda x:x.replace(',',''))
        # The dedicated labelled normal-rate date in the benefit table.
        pick('normal_from',r'with\s+effect\s+from\s*[:\-]?\s*'+DATE,lambda s:dt(s).isoformat())
        pick('account',r'account\s*(?:number|no\.?)\s*[:\-]?\s*(\d[\d ]{5,28})',lambda x:re.sub(r'\s','',x))
        pick('ifsc',r'IFSC\s*(?:code)?\s*[:\-]?\s*([A-Z]{4}0[A-Z0-9]{6})',str.upper)
        pick('fma_after',r'medical\s+allowance\s*[:\-]?\s*(NIL|NO|[\d,]+(?:\.\d+)?)',lambda x:'0' if x.upper() in ('NIL','NO') else x.replace(',',''))
    else:
        pick('pensioner',r'(?:name\s+of\s+(?:the\s+)?pensioner|pensioner\s+name|name\s+of\s+(?:the\s+)?(?:retiring\s+)?(?:government\s+servant|govt\.?\s*servant))\s*[:\-]?\s*(?:Mr\.?|Mrs\.?|Ms\.?)?\s*([^\n:]+)')
        pick('pensioner_dob',r'(?:pensioner\s+date\s+of\s+birth|date\s+of\s+birth\s+of\s+(?:the\s+)?pensioner|date\s+of\s+birth)\s*[:\-]?\s*'+DATE,lambda s:dt(s).isoformat())
        pick('family_dob',r'(?:family\s+pensioner\s+(?:date\s+of\s+birth|DOB)|date\s+of\s+birth\s+of\s+(?:the\s+)?family\s+pensioner)\s*[:\-]?\s*'+DATE,lambda s:dt(s).isoformat())
        death_dates=pick('death',r'date\s+of\s+death\s*[:\-]?\s*'+DATE,lambda s:dt(s).isoformat())
        if death_dates:out['_death_dates']=death_dates
        pick('basic',r'(?:basic\s+pension|pension\s+basic|gross\s+pension)\s*(?:amount)?\s*[:\-]?\s*'+MONEY,lambda x:x.replace(',',''))
        pick('commuted',r'(?:commuted\s+portion|monthly\s+commutation|commuted\s+pension)\s*(?:amount)?\s*[:\-]?\s*'+MONEY,lambda x:x.replace(',',''))
        pick('commutation_restore',r'(?:date\s+of\s+restoration|restoration\s+date)\s*[:\-]?\s*'+DATE,lambda s:dt(s).isoformat())
        pick('fma_before',r'(?:medical\s+allowance|FMA)\s*(?:amount)?\s*[:\-]?\s*(NIL|NO|[\d,]+(?:\.\d+)?)',lambda x:'0' if x.upper() in ('NIL','NO') else x.replace(',',''))
        pick('basic',r'amount\s+of\s+monthly\s+pension\s+before\s+commutation\s*[:\-]?\s*'+MONEY,lambda x:x.replace(',',''))
        pick('commuted',r'fraction/amount\s+of\s+pension\s+commuted,?\s*if\s+any\s*\d+(?:\.\d+)?\s*%\s*,?\s*'+MONEY,lambda x:x.replace(',',''))
        pick('fma_before',r'grant\s+of\s+medical\s+allowance\s+to\s+be\s+paid\s*[:\-]?\s*(NIL|NO|[\d,]+(?:\.\d+)?)',lambda x:'0' if x.upper() in ('NIL','NO') else x.replace(',',''))
        if re.search(r'revision\s+on\s+account\s+of\s+commutation',text,re.I):
            # Only a dated, identified later commutation authority can supersede
            # an original PPO's zero/previous commuted portion.
            gross=re.search(r'Gross\s+Pension\s+([\d,]+(?:\.\d+)?)\s+([\d,]+(?:\.\d+)?)',text,re.I)
            reduced=re.search(r'Reduced\s+Pension\s+after\s+commutation\s+([\d,]+(?:\.\d+)?)\s+([\d,]+(?:\.\d+)?)',text,re.I)
            if gross and reduced and out.get('ppo') and out.get('_issued_date'):
                from .engine import D
                basic=D(gross.group(2).replace(',',''));net=D(reduced.group(2).replace(',',''))
                if not 0<=net<=basic:raise ValueError('Commutation revision amounts are inconsistent.')
                out.update(basic=str(basic),commuted=str(basic-net),_supersedes=['basic','commuted'])
    # Never infer category from boilerplate such as "Basic + IDA" in a form.
    pick('category',r'(?:pay\s+commission|pension\s+type|pensioner\s+type)\s*[:\-]?\s*(IDA|CDA)\b',str.upper)
    for key in ('pensioner','family'):
        if key in out:out[key]=clean_name(out[key])
    return out,[]

def merge_candidates(candidates):
    """Conflicting sources are left blank, so a reviewer must select a value."""
    values={};sources={};notes=[]
    money={'basic','enhanced','normal','commuted','fma_before','fma_after'}
    def comparable(key,value):
        return format(D(value).normalize(),'f') if key in money else value
    for filename,fields in candidates:
        for k,v in fields.items():
            if k=='_death_dates':
                sources.setdefault('death',[]).extend((value,filename) for value in v)
                continue
            if k=='death' and fields.get('_death_dates'):continue
            if k.startswith('_'):continue
            if v not in (None,''):sources.setdefault(k,[]).append((str(v),filename))
    for k,records in sources.items():
        revisions=[(fields['_issued_date'],str(fields[k]),filename) for filename,fields in candidates
                   if k in fields.get('_supersedes',[]) and fields.get('_issued_date') and k in fields]
        if revisions:
            latest=max(r[0] for r in revisions)
            latest_values={comparable(k,r[1]) for r in revisions if r[0]==latest}
            if len(latest_values)==1:
                values[k]=next(iter(latest_values))
                if any(comparable(k,v)!=values[k] for v,_ in records):notes.append(f'{k}: later dated commutation authority supersedes original value; both sources retained.')
                continue
        unique=set(comparable(k,v) for v,_ in records)
        if len(unique)==1:values[k]=next(iter(unique))
        elif k!='death':notes.append('Conflicting '+k+': '+'; '.join(v+' ['+f+']' for v,f in records))
    return values,sources,notes
