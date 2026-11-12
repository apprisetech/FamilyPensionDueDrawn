"""Approved 12-column portrait statement with editable, formula-linked schedules.

Uses the application's existing openpyxl dependency. Never writes the source workbook.
"""
from datetime import timedelta
from pathlib import Path
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
from openpyxl.workbook.properties import CalcProperties
from timeline import calculate, day, end_month

def words(n):
    units=['','One','Two','Three','Four','Five','Six','Seven','Eight','Nine','Ten','Eleven','Twelve','Thirteen','Fourteen','Fifteen','Sixteen','Seventeen','Eighteen','Nineteen']
    tens=['','','Twenty','Thirty','Forty','Fifty','Sixty','Seventy','Eighty','Ninety']
    if not n:return 'Zero'
    if n<20:return units[n]
    if n<100:return tens[n//10]+(' '+units[n%10] if n%10 else '')
    for size,label in [(10000000,'Crore'),(100000,'Lakh'),(1000,'Thousand'),(100,'Hundred')]:
        if n>=size:return words(n//size)+' '+label+(' '+words(n%size) if n%size else '')

def export(model, rates, filename, title='Due / Drawn Statement', overrides=None):
    calculate(model,rates)  # Verify coverage and record automatic payment allocations first.
    book=Workbook(); s=book.active;s.title='Due Drawn'
    stages=book.create_sheet('Pension stages');dr=book.create_sheet('DR rates');pay=book.create_sheet('Payments');build=book.create_sheet('Period calculations')
    stages.append(['Effective','Beneficiary','DOB','Basic','Commuted','Restore from','FMA','Category','Kind','Source','Manual commutation'])
    for stage in sorted(model['stages'],key=lambda x:x['effective']):
        stages.append([day(stage['effective']),stage['name'],day(stage['dob']),float(stage['basic']),float(stage['commuted']),day(stage['restore']) if stage.get('restore') else None,float(stage['fma']),stage['category'],stage.get('kind','Original'),stage.get('source','Reviewed input'),int(stage.get('commutation_override',False))])
    dr.append(['From','To','DR percent','Category'])
    for r in rates:dr.append([day(r['start']),day(r['end']),float(r['percent']),r['category']])
    parts=book.create_sheet('Commutation portions');parts.append(['Effective from','Monthly portion','Restore from','Source'])
    for part in model.get('parts',[]):parts.append([day(part.get('effective') or model['start']),float(part['amount']),day(part['restore']),part.get('source','Reviewed input')])
    pay.append(['Paid on','Bill type','Gross','Separate arrear','Month override','Include (1/0)','Automatic month','Assigned month','Drawn amount'])
    for p in model.get('payments',[]):
        i=pay.max_row+1
        pay.append([day(p['paid_on']),' '.join(p['bill_type'].upper().split()),float(p['gross']),float(p.get('separate_arrear',0)),p.get('allocated_month') or None,int(p.get('include',True)),None,None,None])
        # Initial inferred March mapping remains formula driven when payment dates change.
        pay[f'G{i}']=f'=IF(AND(MONTH(A{i})=4,B{i}="MONTHLY BILL",COUNTIFS(B$2:B${len(model["payments"])+1},"MONTHLY BILL",A$2:A${len(model["payments"])+1},">="&DATE(YEAR(A{i}),4,1),A$2:A${len(model["payments"])+1},"<"&DATE(YEAR(A{i}),5,1))=2,COUNTIFS(B$2:B${len(model["payments"])+1},"MONTHLY BILL",A$2:A${len(model["payments"])+1},">="&DATE(YEAR(A{i}),4,1),A$2:A${len(model["payments"])+1},"<"&A{i})=0),TEXT(EDATE(A{i},-1),"yyyy-mm"),TEXT(A{i},"yyyy-mm"))'
        pay[f'H{i}']=f'=IF(E{i}="",G{i},E{i})';pay[f'I{i}']=f'=IF(F{i}=1,C{i}+D{i},0)'
    def merge(area,value):s.merge_cells(area);s[area.split(':')[0]]=value
    merge('A1:L1',title);merge('A3:C3','PPO Number:');merge('D3:H3',model['ppo']);s['D3'].number_format='@'
    merge('A4:C4','Original Pensioner:');merge('D4:L4',model.get('original_name',''))
    merge('A7:C7','Current Beneficiary:');merge('D7:L7',"='Pension stages'!B"+str(stages.max_row))
    merge('A8:C8','Beneficiary DOB:');s['D8']="='Pension stages'!C"+str(stages.max_row)
    s.merge_cells('D8:F8')
    merge('A9:C9','Calculation from:');s['D9']=day(model['start']);merge('F9:H9','Calculation through:');s['I9']=day(model['end'])
    s.merge_cells('D9:E9')
    merge('A11:D11','PENSIONARY BENEFITS')
    for r,label,column in [(13,'Applicable Pension:','D'),(15,'Medical Allowance (FMA):','G'),(16,'Commuted Portion:','E')]:
        merge(f'A{r}:C{r}',label);s[f'D{r}']=f"='Pension stages'!{column}{stages.max_row}"
    merge('F13:H13','Account:');s['I13']=model.get('account','');s['I13'].number_format='@'
    merge('F15:H15','IFSC:');s['I15']=model.get('ifsc','')
    current=model['stages'][max(range(len(model['stages'])),key=lambda i:model['stages'][i]['effective'])]
    for addr,key,col in [('D13','basic','D'),('D15','fma','G'),('D16','commuted','E')]:
        s[addr]=float(current[key]);stages[f'{col}{stages.max_row}']=f"='Due Drawn'!${addr[0]}${addr[1:]}"
    s['D8']=day(current['dob']);stages[f'C{stages.max_row}']="='Due Drawn'!$D$8"
    merge('A18:L18','Edit Pension stages / DR rates / Payments / Commutation portions to recalculate. Blue cells are inputs.')
    merge('A19:L19','Rate-date edits recalculate existing months. Changing the overall calendar range requires a fresh export.')
    merge('A21:B21','Period')
    for col,label in zip('CDEFGHIJKL',['Basic\nAmount','Commuted','Reduced','Additional\nQuantum','DR Rate','DR Amount','Due incl.\nFMA','Total Due','Drawn','Difference']):s[f'{col}21']=label
    s['A22']='FROM';s['B22']='TO'
    n=stages.max_row; nr=dr.max_row;np=parts.max_row; nt=max(2,pay.max_row)
    boundaries=book.create_sheet('Boundaries');boundaries.append(['Month','Clamped interval boundary'])
    build.append(['From','To','Stage row','Days','Basic','Commuted','Reduced','Additional quantum','DR percent','DR amount','FMA','Unrounded due','Total due','Month','Rate matches'])
    cursor=day(model['start']).replace(day=1); row=23
    while cursor<=day(model['end']):
        last=end_month(cursor);month=cursor.strftime('%Y-%m');first_boundary=boundaries.max_row+1
        source_dates=[f"'Pension stages'!A{i}" for i in range(2,n+1)]+[f"'Pension stages'!F{i}" for i in range(2,n+1)]+[f"'Commutation portions'!{c}{i}" for i in range(2,np+1) for c in ('A','C')]+[f"'DR rates'!A{i}" for i in range(2,nr+1)]+[f"'DR rates'!B{i}+1" for i in range(2,nr+1)]
        start_expr=f'MAX(DATE({cursor.year},{cursor.month},1),\'Due Drawn\'!$D$9)'
        stop_expr=f'MIN(DATE({last.year},{last.month},{last.day})+1,\'Due Drawn\'!$I$9+1)'
        boundaries.append([cursor,'='+start_expr]);boundaries.append([cursor,'='+stop_expr])
        for ref in source_dates:boundaries.append([cursor,f'=MAX({start_expr},MIN({stop_expr},IF({ref}=0,{start_expr},{ref})))'])
        last_boundary=boundaries.max_row; bstart=build.max_row+1
        for j in range(1,last_boundary-first_boundary+1):
            i=build.max_row+1;br=f"Boundaries!$B${first_boundary}:$B${last_boundary}"
            build.append([f'=SMALL({br},{j})',f'=SMALL({br},{j+1})-1',None,None,None,None,None,None,None,None,None,None,None,month,None])
            build[f'C{i}']=f'=MATCH(_xlfn.AGGREGATE(14,6,\'Pension stages\'!$A$2:$A${n}/(\'Pension stages\'!$A$2:$A${n}<=A{i}),1),\'Pension stages\'!$A$2:$A${n},0)+1'
            build[f'D{i}']=f'=MAX(0,B{i}-A{i}+1)'
            lookup=lambda col:f"INDEX('Pension stages'!{col}:{col},C{i})"
            build[f'E{i}']=f'=IF(D{i}=0,0,ROUND({lookup("D")}*D{i}/DAY(EOMONTH(A{i},0)),0))'
            deduction=f'IF(OR({lookup("F")}=0,A{i}<{lookup("F")}),{lookup("E")},0)'
            if np>1:deduction=f'IF(AND({lookup("I")}<>"Family",{lookup("K")}=0),SUMIFS(\'Commutation portions\'!$B$2:$B${np},\'Commutation portions\'!$A$2:$A${np},"<="&A{i},\'Commutation portions\'!$C$2:$C${np},">"&A{i}),{deduction})'
            build[f'F{i}']=f'=IF(D{i}=0,0,{deduction}*D{i}/DAY(EOMONTH(A{i},0)))'
            build[f'G{i}']=f'=E{i}-F{i}'
            age=f'(YEAR(A{i})-YEAR({lookup("C")})-(MONTH(A{i})<MONTH({lookup("C")})))'
            build[f'H{i}']=f'=E{i}*IF({age}<80,0,IF({age}<85,0.2,IF({age}<90,0.3,IF({age}<95,0.4,IF({age}<100,0.5,1)))))'
            conditions=f'\'DR rates\'!$A$2:$A${nr},"<="&A{i},\'DR rates\'!$B$2:$B${nr},">="&B{i},\'DR rates\'!$D$2:$D${nr},{lookup("H")}'
            build[f'O{i}']=f'=IF(D{i}=0,1,COUNTIFS({conditions}))'
            build[f'I{i}']=f'=IF(D{i}=0,0,IF(O{i}=1,SUMIFS(\'DR rates\'!$C$2:$C${nr},{conditions}),NA()))'
            build[f'J{i}']=f'=(E{i}+H{i})*I{i}/100';build[f'K{i}']=f'=IF(D{i}=0,0,{lookup("G")}*D{i}/DAY(EOMONTH(A{i},0)))'
            build[f'L{i}']=f'=G{i}+H{i}+J{i}+K{i}';build[f'M{i}']=f'=ROUNDUP(L{i},0)'
        bend=build.max_row
        s[f'A{row}']=f'=MAX(DATE({cursor.year},{cursor.month},1),$D$9)';s[f'B{row}']=f'=MIN(EOMONTH(A{row},0),$I$9)'
        for col,source in [('C','E'),('D','F'),('E','G'),('F','H'),('H','J'),('I','L'),('J','M')]:s[f'{col}{row}']=f"=SUM('Period calculations'!{source}{bstart}:{source}{bend})"
        s[f'G{row}']=f'=IF(C{row}+F{row}=0,0,H{row}/(C{row}+F{row})*100)'
        s[f'K{row}']=f'=SUMIF(Payments!$H$2:$H${nt},TEXT(A{row},"yyyy-mm"),Payments!$I$2:$I${nt})'
        s[f'L{row}']=f'=J{row}-K{row}'
        if month in (overrides or {}):
            s[f'J{row}']=float(overrides[month])
        cursor=last+timedelta(days=1);row+=1
    total=row;merge(f'A{row}:B{row}','Total')
    for col in 'CDEFHIJKL':s[f'{col}{row}']=f'=SUM({col}23:{col}{row-1})'
    merge(f'B{row+3}:F{row+3}','Net arrear / recovery for the above period =');s[f'G{row+3}']=f'=L{row}'
    w=book.create_sheet('Amount words');w.sheet_state='hidden'
    for v in range(1000):w.cell(v+1,1,words(v))
    w['B1']=f"=ROUND(ABS('Due Drawn'!L{row}),0)"
    for i,(div,mod,label) in enumerate([(10000000,1000,'Crore'),(100000,100,'Lakh'),(1000,100,'Thousand'),(1,1000,'')],2):
        w[f'B{i}']=f'=MOD(INT($B$1/{div}),{mod})';w[f'C{i}']=f'=IF(B{i}=0,"",INDEX($A$1:$A$1000,B{i}+1)&" {label} ")'
    w['C6']='=IF(B1>=10000000000,"Amount exceeds words range",IF(B1=0,"Rupees Zero Only","Rupees "&TRIM(C2&C3&C4&C5)&" Only"))'
    merge(f'A{row+4}:L{row+4}',"='Amount words'!C6")
    for region,label in [(f'A{row+8}:C{row+8}','SA'),(f'E{row+8}:G{row+8}','AAO'),(f'I{row+8}:L{row+8}','Sr. Accounts Officer')]:merge(region,label)
    from openpyxl.utils import get_column_letter
    for i,width in enumerate([12,12,10,10,10,10,9,12,12,11,11,12],1):s.column_dimensions[get_column_letter(i)].width=width
    for r in s:
        for c in r:c.font=Font(name='Times New Roman',size=11);c.alignment=Alignment(vertical='center',wrap_text=c.row in (18,19,21))
    s['A1'].font=Font(name='Times New Roman',size=16,bold=True);s['A1'].alignment=Alignment(horizontal='center')
    for i in (18,19,21):s.row_dimensions[i].height=30
    thin=Side(style='thin')
    for r in s.iter_rows(min_row=21,max_row=total,max_col=12):
        for c in r:
            c.border=Border(left=thin,right=thin,top=thin,bottom=thin);c.font=Font(name='Arial',size=9,bold=c.row in (21,22,total));c.number_format='0.00' if c.column in (4,5,6,8,9) else '0'
    for r in range(23,total):
        for col in 'AB':s[f'{col}{r}'].number_format='dd-mm-yy'
    for a in ('D8','D9','I9'):s[a].number_format='dd-mm-yyyy'
    for sheet in (stages,dr,pay,parts,build,boundaries):
        sheet.freeze_panes='A2';sheet.auto_filter.ref=sheet.dimensions
        for col in range(1,sheet.max_column+1):sheet.column_dimensions[get_column_letter(col)].width=22
        for r in sheet:
            for cell in r:
                cell.font=Font(name='Arial',size=10,color='0000FF' if cell.row>1 and cell.data_type!='f' else '000000')
                if isinstance(cell.value,__import__('datetime').date):cell.number_format='dd-mm-yyyy'
    for r in build.iter_rows(min_row=2):
        r[0].number_format=r[1].number_format='dd-mm-yyyy'
    boundaries.sheet_state='hidden'
    notes=book.create_sheet('Review notes');notes.append(['Review / evidence'])
    for note in model.get('notes',[]):notes.append([str(note)])
    notes.append(['Period calculations contains formula-driven splits, including changing revision/restoration dates. Re-export after changing the overall calendar range or adding stages/rows.'])
    notes.append(['A manual monthly Due override replaces that month total; delete the override in the app and export to restore its formula.'])
    notes.column_dimensions['A'].width=110
    for sheet in book:
        sheet.page_setup.orientation='portrait';sheet.page_setup.paperSize=sheet.PAPERSIZE_A4;sheet.page_setup.fitToWidth=1;sheet.page_setup.fitToHeight=0;sheet.sheet_properties.pageSetUpPr.fitToPage=True
    s.print_area=f'A1:L{row+8}';s.print_title_rows='21:22';s.freeze_panes='C23'
    book.calculation=CalcProperties(calcId=0,fullCalcOnLoad=True,forceFullCalc=True)
    Path(filename).parent.mkdir(parents=True,exist_ok=True);book.save(filename)
    return Path(filename)
