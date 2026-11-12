from decimal import Decimal
"""Local Excel exporter; standard library/openpyxl produce valid Office XML."""
from pathlib import Path
from copy import copy
from datetime import datetime
from zipfile import ZipFile,ZIP_DEFLATED
import re
from xml.etree import ElementTree as ET
from openpyxl import Workbook,load_workbook
from openpyxl.styles import Font,Alignment,PatternFill,Border,Side
from openpyxl.formatting.rule import CellIsRule
from openpyxl.utils.datetime import to_excel
from .engine import quantum

def in_words(n):
    n=abs(int(n));u=['','One','Two','Three','Four','Five','Six','Seven','Eight','Nine','Ten','Eleven','Twelve','Thirteen','Fourteen','Fifteen','Sixteen','Seventeen','Eighteen','Nineteen'];t=['','','Twenty','Thirty','Forty','Fifty','Sixty','Seventy','Eighty','Ninety']
    if not n:return 'Zero'
    if n<20:return u[n]
    if n<100:return t[n//10]+(' '+u[n%10] if n%10 else '')
    for size,label in [(10000000,'Crore'),(100000,'Lakh'),(1000,'Thousand'),(100,'Hundred')]:
        if n>=size:return in_words(n//size)+' '+label+(' '+in_words(n%size) if n%size else '')

def export(c,result,directory):
    wb=Workbook();s=wb.active;s.title='Sheet3';cache={}
    widths=[10.42578125,10.42578125,9,10.42578125,9.42578125,7.140625,7.85546875,9.5703125,9.5703125,8.5703125,7.42578125,7]
    from openpyxl.utils import get_column_letter
    for i,width in enumerate(widths,1):s.column_dimensions[get_column_letter(i)].width=width
    total=26+len(result['rows']);footer=total+3;sign=total+9
    for row in s.iter_rows(min_row=1,max_row=sign,max_col=12):
        for cell in row:cell.font=Font(name='Times New Roman',size=12);cell.alignment=Alignment(vertical='center')
    for r in range(1,sign+1):s.row_dimensions[r].height=15.75
    s.row_dimensions[1].height=20.25;s.row_dimensions[24].height=31.5;s.row_dimensions[25].height=16.5
    def merged(region,value,bold=False,align='left',underline=None):
        s.merge_cells(region);cell=s[region.split(':')[0]];cell.value=value;cell.font=Font(name='Times New Roman',size=12,bold=bold,underline=underline);cell.alignment=Alignment(horizontal=align,vertical='center');return cell
    merged('A1:L1','Conversion to Family Pension',True,'center','single').font=Font(name='Times New Roman',size=16,bold=True,underline='single')
    for r,label,value in [(3,'PPO Number:',c.ppo),(4,'Pensioner Name:',c.pensioner),(5,'Date of Death:',c.death),(6,'Date of Birth',c.pensioner_dob)]:
        merged(f'A{r}:B{r}',label,True,'right');merged(f'C{r}:'+('E' if r<5 else 'D')+str(r),value,r==3)
    s['C3'].number_format='@'
    merged('F4:G4','A/C DETAILS',True,underline='single');s['F5']='IFSC:';s['F6']='NO.:'
    for a in ('F5','F6'):s[a].font=Font(name='Times New Roman',size=12,bold=True)
    merged('G5:I5',c.ifsc);merged('G6:I6',c.account);s['G6'].number_format='@'
    s['B7']='Age';s['B7'].font=Font(name='Times New Roman',size=12,bold=True);s['B7'].alignment=Alignment(horizontal='right')
    s['C7']=f'=ROUND((DATE({result["end"].year},{result["end"].month},{result["end"].day})-C6)/365.25,2)';s['C7'].number_format='0.00';s['C7'].font=Font(name='Times New Roman',size=12,italic=True)
    merged('A9:C9','Family Pensioner Name:',True,'right');merged('D9:F9',c.family)
    merged('A10:C10','Date of Birth:',True,'right');merged('D10:E10',c.family_dob)
    merged('A11:C11','Age:',True,'right');s['D11']=f'=ROUND((DATE({result["end"].year},{result["end"].month},{result["end"].day})-D10)/365.25,2)';s['D11'].number_format='0.00';s['D11'].font=Font(name='Times New Roman',size=12,italic=True)
    merged('A13:C13','PENSIONARY BENEFITS',True,underline='single')
    from .commutations import original_rates
    summary_basic, summary_comm = original_rates(c,c.death)
    if c.manual_overrides:
        audit=wb.create_sheet('Manual overrides')
        audit.append(['Field','Collected value','Selected value'])
        for key,change in c.manual_overrides.items():
            audit.append([key,str(change.get('automatic','')),str(change.get('selected',''))])
    if c.commutation_parts:
        portions=wb.create_sheet('Commutation portions')
        portions.append(['Monthly portion','Progressive total','Restoration date','Source','Effective from'])
        for part in c.commutation_parts:
            portions.append([float(part['amount']),part.get('progressive',''),__import__('datetime').date.fromisoformat(part['restore']),part.get('source',''),__import__('datetime').date.fromisoformat(part['effective']) if part.get('effective') else None])
    history = None
    rate_refs = {}
    def pension_ref(value, summary, address, label):
        nonlocal history
        if value == summary:
            return address
        key = label, value
        if key not in rate_refs:
            if history is None:
                history = s.parent.create_sheet('Earlier pension rates')
                history.append(['Rate used before conversion', 'Monthly amount'])
                history.column_dimensions['A'].width = 40
                history.column_dimensions['B'].width = 20
            history.append([label, value if hasattr(value, "isoformat") else float(value)])
            if hasattr(value, "isoformat"):
                history.cell(history.max_row, 2).number_format = "dd-mm-yyyy"
            rate_refs[key] = f"'Earlier pension rates'!$B${history.max_row}"
        return rate_refs[key]
    for r,label,value in [(15,'Normal Pension Amount:',summary_basic),(16,'Additional Quantum Amount:',summary_basic*quantum(c.pensioner_dob,c.death)),(17,'Medical Allowance Amount:',c.fma_before),(18,'Commuted Portion Amount:',summary_comm),(20,'Enhanced Family Pension:',c.enhanced),(21,'Normal Family Pension:',c.normal),(22,'Medical Allowance (after):',c.fma_after)]:
        merged(f'A{r}:C{r}',label,True);s[f'D{r}']=float(value);s[f'D{r}'].number_format='0'
    s['D16']='=$D$15*IF(YEAR($C$5)-YEAR($C$6)-(MONTH($C$5)<MONTH($C$6))<80,0,IF(YEAR($C$5)-YEAR($C$6)-(MONTH($C$5)<MONTH($C$6))<85,0.2,IF(YEAR($C$5)-YEAR($C$6)-(MONTH($C$5)<MONTH($C$6))<90,0.3,IF(YEAR($C$5)-YEAR($C$6)-(MONTH($C$5)<MONTH($C$6))<95,0.4,IF(YEAR($C$5)-YEAR($C$6)-(MONTH($C$5)<MONTH($C$6))<100,0.5,1)))))'
    s['F18']='Restore:'
    merged('G18:H18',c.commutation_restore);s['G18'].number_format='dd-mm-yy'
    s['F16']='w.e.f.:';s['F20']='upto:';s['F21']='w.e.f.:'
    merged('G20:H20',c.enhanced_until);merged('G21:H21',c.normal_from)
    for a in ('C5','C6','D10','G20','G21'):s[a].number_format='dd-mm-yy'
    merged('A24:B24','Period',True,'center');s['A25']='FROM';s['B25']='TO'
    for col,label in zip('CDEFGHIJKL',['Basic\nAmount','Com\nmuted','Reduced','Addl\nQuant','DR\nRate','DR\nAmount','Due','Total\nDue','Drawn','Diff']):s[f'{col}24']=label
    thin=Side(style='thin',color='000000')
    for row in s.iter_rows(min_row=24,max_row=total,max_col=12):
        for cell in row:cell.border=Border(left=thin,right=thin,top=thin,bottom=thin);cell.font=Font(name='Arial',size=10,bold=cell.row<=25 or cell.row==total);cell.alignment=Alignment(horizontal='center' if cell.row<=25 else 'right',vertical='center',wrap_text=cell.row<=25)
    def fx(addr,formula,value):s[addr]=formula;cache[addr]=value
    groups={}
    for r,row in enumerate(result['rows'],26):
        groups.setdefault(row['start'].strftime('%Y-%m'),[]).append(r)
        s[f'A{r}']=row['start'];s[f'B{r}']=row['end']
        for col in 'AB':s[f'{col}{r}'].number_format='dd-mm-yy'
        base=pension_ref(row['base'], summary_basic, '$D$15', 'Basic pension') if row['original'] and c.pay_revisions else '$D$15' if row['original'] else f'IF(A{r}<=$G$20,$D$20,$D$21)'
        prior = row.get('prior')
        if prior:
            base = pension_ref(row['base'], None, '', prior['family'] + ' basic')
        fx(f'C{r}',f'=ROUND({base}/DAY(EOMONTH(A{r},0))*(B{r}-A{r}+1),0)',row['basic'])
        comm_base=pension_ref(row['deduction'], summary_comm, '$D$18', 'Commuted portion') if row['comm'] else '$D$18'
        if row['original']:
            if c.commutation_parts and not ({'commuted','commutation_restore'} & c.manual_overrides.keys()):
                terms=[f"'Commutation portions'!$A${i}*MAX(0,MIN(B{r},'Commutation portions'!$C${i}-1)-MAX(A{r},'Commutation portions'!$E${i})+1)/DAY(EOMONTH(A{r},0))" for i in range(2,len(c.commutation_parts)+2)]
                comm_formula='='+'+'.join(terms)
            else:
                comm_formula=f'={comm_base}*MAX(0,MIN(B{r},IF($G$18="",B{r},$G$18-1))-A{r}+1)/DAY(EOMONTH(A{r},0))'
        else:comm_formula='=0'
        fx(f'D{r}',comm_formula,row['comm'])
        fx(f'E{r}',f'=C{r}-D{r}',row['reduced'])
        dob='$C$6' if row['original'] else '$D$10'
        if prior:
            dob = pension_ref(row['dob'], None, '', prior['family'] + ' DOB')
        age=f'(YEAR(A{r})-YEAR({dob})-IF(MONTH(A{r})<MONTH({dob}),1,0))'
        fx(f'F{r}',f'=C{r}*IF({age}<80,0,IF({age}<85,0.2,IF({age}<90,0.3,IF({age}<95,0.4,IF({age}<100,0.5,1)))))',row['quantum'])
        s[f'G{r}']=float(row['rate']);s[f'G{r}'].number_format='0.0'
        fx(f'H{r}',f'=(C{r}+F{r})*G{r}/100',row['dr'])
        monthly_fma_ref = f'$D${row["fma_cell"]}'
        if row.get('prior_fma') or row['start'].strftime('%Y-%m') in c.fma_overrides:
            monthly_fma_ref = pension_ref(row['fma_monthly'], None, '', 'Reviewed FMA '+row['start'].strftime('%Y-%m'))
        fma_ref = f'+{monthly_fma_ref}/DAY(EOMONTH(A{r},0))*(B{r}-A{r}+1)'
        fx(f'I{r}',f'=E{r}+F{r}+H{r}{fma_ref}',row['due'])
        fx(f'J{r}',f'=ROUNDUP(I{r},0)',row['total'])
        for col in 'CDEFHI':s[f'{col}{r}'].number_format='0.00'
        for col in 'CJF':s[f'{col}{r}'].number_format='0'
    payment_sheet=wb.create_sheet('Payments')
    payment_sheet.append(['Paid on','Bill type','Gross','Separate arrear','Month override','Include 1/0','Automatic month','Assigned month','Drawn'])
    items=result.get('payments',[])
    n=max(2,len(items)+1)
    for index,payment in enumerate(items,2):
        payment_sheet.append([payment.paid_on,' '.join(payment.bill_type.upper().split()),float(payment.gross),float(payment.separate_arrear),payment.allocated_month or None,int(payment.include)])
        payment_sheet[f'G{index}']=f'=IF(AND(MONTH(A{index})=4,B{index}="MONTHLY BILL",COUNTIFS(B$2:B${n},"MONTHLY BILL",A$2:A${n},">="&DATE(YEAR(A{index}),4,1),A$2:A${n},"<"&DATE(YEAR(A{index}),5,1))=2,COUNTIFS(B$2:B${n},"MONTHLY BILL",A$2:A${n},">="&DATE(YEAR(A{index}),4,1),A$2:A${n},"<"&A{index})=0),TEXT(EDATE(A{index},-1),"yyyy-mm"),TEXT(A{index},"yyyy-mm"))'
        payment_sheet[f'H{index}']=f'=IF(E{index}="",G{index},E{index})'
        payment_sheet[f'I{index}']=f'=IF(F{index}=1,C{index}+D{index},0)'
        payment_sheet[f'A{index}'].number_format='dd-mm-yyyy'
    for col in 'ABCDEFGHI':payment_sheet.column_dimensions[col].width=22
    for rr in groups.values():
        first,last=rr[0],rr[-1];row=result['rows'][first-26]
        if first!=last:
            for col in 'KL':s.merge_cells(f'{col}{first}:{col}{last}')
        fx(f'K{first}',f'=SUMIF(Payments!$H$2:$H${n},TEXT(A{first},"yyyy-mm"),Payments!$I$2:$I${n})',row['drawn']);s[f'K{first}'].number_format='0'
        fx(f'L{first}',f'=SUM(J{first}:J{last})-K{first}',row['difference']);s[f'L{first}'].font=Font(name='Arial',size=10,bold=True);s[f'L{first}'].number_format='0'
    merged(f'A{total}:B{total}','Total',True,'center')
    keys=dict(C='basic',D='comm',E='reduced',F='quantum',H='dr',I='due',J='total',K='drawn',L='difference')
    for col,key in keys.items():
        value=sum((r[key] or 0) for r in result['rows']);fx(f'{col}{total}',f'=SUM({col}26:{col}{total-1})',value);s[f'{col}{total}'].number_format='0';s[f'{col}{total}'].font=Font(name='Arial',size=9,bold=True)
    label='Recovery to be done' if result['difference']<0 else 'Arrear to be paid' if result['difference']>0 else 'No difference'
    merged(f'B{footer}:C{footer}',label);fx(f'B{footer}',f'=IF(G{footer}<0,"Recovery to be done",IF(G{footer}>0,"Arrear to be paid","No difference"))',label)
    merged(f'D{footer}:F{footer}',f'in {(result["end"].replace(day=1)+__import__("datetime").timedelta(days=32)):%B %Y} =')
    merged(f'G{footer}:I{footer}',None,True);fx(f'G{footer}',f'=J{total}-K{total}',result['difference']);s[f'G{footer}'].number_format='0'
    s.conditional_formatting.add(f'G{footer}:I{footer}',CellIsRule(operator='greaterThan',formula=['0'],fill=PatternFill('solid',fgColor='C6EFCE')))
    s.conditional_formatting.add(f'G{footer}:I{footer}',CellIsRule(operator='lessThan',formula=['0'],fill=PatternFill('solid',fgColor='FFC7CE')))
    words = wb.create_sheet('Amount words')
    words.sheet_state = 'hidden'
    for number in range(1000):
        words.cell(number + 1, 1, in_words(number))
    words['B1'] = f"=ROUND(ABS('Sheet3'!G{footer}),0)"
    for row, (divisor, modulus, label) in enumerate(
            [(10000000, 1000, 'Crore'), (100000, 100, 'Lakh'),
             (1000, 100, 'Thousand'), (1, 1000, '')], 2):
        words.cell(row, 2, f'=MOD(INT($B$1/{divisor}),{modulus})')
        suffix = ' ' + label if label else ''
        words.cell(row, 3, f'=IF(B{row}=0,"",INDEX($A$1:$A$1000,B{row}+1)&"{suffix} ")')
    words['C6'] = '=IF(B1>=10000000000,"Amount exceeds words range",IF(B1=0,"(Rupees Zero Only)","(Rupees "&C2&C3&C4&C5&"Only)"))'
    merged(f'B{footer+1}:I{footer+1}',None,'','center')
    fx(f'B{footer+1}',"='Amount words'!C6",
       '(Rupees '+in_words(result['difference'])+' Only)')
    for region,text in [(f'A{sign}:B{sign}','SA'),(f'D{sign}:E{sign}','AAO'),(f'H{sign}:K{sign}','Sr. Accounts Officer')]:merged(region,text,False,'center')
    end=sign
    for i,note in enumerate(result['notes']):
        r=sign+3+i*2;merged(f'A{r}:L{r+1}',note);s[f'A{r}'].font=Font(name='Times New Roman',size=10);s[f'A{r}'].alignment=Alignment(wrap_text=True,vertical='center');end=r+1
    s.sheet_view.showGridLines=True;s.sheet_properties.pageSetUpPr.fitToPage=True;s.page_setup.orientation='portrait';s.page_setup.paperSize=s.PAPERSIZE_A4;s.page_setup.fitToWidth=1;s.page_setup.fitToHeight=0;s.print_area=f'A1:L{end}';s.print_title_rows='24:25'
    from datetime import datetime
    name = re.sub(r'[^A-Za-z0-9]+', '_', c.family.upper()).strip('_')
    stem = f'{datetime.now():%Y%m%d_%H%M%S}_{c.ppo}_{name}'
    folder = Path(directory)
    folder.mkdir(parents=True, exist_ok=True)
    dest = folder / f'{stem}.xlsx'
    suffix = 2
    while dest.exists():
        dest = folder / f'{stem}_{suffix:02d}.xlsx'
        suffix += 1
    from openpyxl.workbook.properties import CalcProperties
    wb.calculation=CalcProperties(calcId=0,fullCalcOnLoad=True,forceFullCalc=True)
    wb.save(dest)
    # Set formula caches without round-tripping styles. Element order/namespace retained.
    with ZipFile(dest) as z:parts={n:z.read(n) for n in z.namelist()}
    from lxml import etree as E
    ns='http://schemas.openxmlformats.org/spreadsheetml/2006/main';root=E.fromstring(parts['xl/worksheets/sheet1.xml'])
    for cell in root.findall(f'.//{{{ns}}}c'):
        addr=cell.get('r')
        if addr not in cache:continue
        value=cache[addr];v=cell.find(f'{{{ns}}}v')
        if v is None:v=E.SubElement(cell,f'{{{ns}}}v')
        if isinstance(value,str):cell.set('t','str');v.text=value
        else:v.text=str(float(value))
    parts['xl/worksheets/sheet1.xml']=E.tostring(root,encoding='utf-8')
    with ZipFile(dest,'w',ZIP_DEFLATED) as z:
        for n,data in parts.items():z.writestr(n,data)
    check=load_workbook(dest,data_only=True)
    assert check.active[f'G{footer}'].value==float(result['difference'])
    return dest
