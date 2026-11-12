from .conversions import separate_conversions
from .revisions import pay_revision, previous_month_check, regular_gross_from_history
from pathlib import Path
from datetime import date
from dataclasses import asdict
import json,os,re,subprocess,threading,queue,traceback,sys,shutil
import tkinter as tk
from tkinter import ttk,filedialog,messagebox,simpledialog
from .engine import Case,Payment,D,dt,previous_month,calculate,load_rates
from .extract import read_pdf,parse_text,merge_candidates
from .exporter import export
from .death_review import reconcile,signature_key,PREFIX
from .diagnostics import Recorder
from . import __version__

ROOT=Path(sys.executable).resolve().parent if getattr(sys,'frozen',False) else Path(__file__).resolve().parent.parent
FIELDS=[('ppo','PPO number (15 digits)'),('category','IDA / CDA'),('pensioner','Original pensioner name'),('family','Family pensioner name'),('pensioner_dob','Original date of birth'),('family_dob','Family date of birth'),('death','Date of death'),('effective','Conversion effective date'),('basic','Original basic before pay revisions'),('commuted','Monthly commuted portion before pay revisions'),('commutation_restore','Commutation restoration date'),('fma_before','Medical allowance before'),('enhanced','Enhanced family pension'),('enhanced_until','Enhanced rate up to'),('normal','Normal family pension'),('normal_from','Normal rate from'),('fma_after','Medical allowance after'),('account','Family bank account number'),('ifsc','IFSC code')]

def json_default(value):return str(value)
def payment_dict(p):return {k:str(v) if k not in ('include',) else v for k,v in asdict(p).items()}

class App:
    def __init__(self,root):
        self.root=root;root.title(f'Family Pension Conversion {__version__} â€” Due / Drawn');root.geometry('1130x810');self.q=queue.Queue();self.candidates=[];self.sources={};self.review_notes=[];self.report_complete=False
        self.loading_fields=False;self.automatic_values={};self.manual_overrides={};self.commutation_parts=[];self.pay_revisions=[]
        self.settings_file=ROOT/'settings.json';self.settings=json.loads(self.settings_file.read_text()) if self.settings_file.exists() else {}
        self.vars={k:tk.StringVar() for k,_ in FIELDS};self.rate_path=tk.StringVar(value=self.settings.get('rates',''));self.output=tk.StringVar(value=self.settings.get('output',str(ROOT/'output')));self.end=tk.StringVar(value=str(previous_month()));self.ocr=tk.BooleanVar(value=False);self.approved=tk.BooleanVar(value=False)
        viewport = ttk.Frame(root)
        viewport.pack(fill='both', expand=True)
        viewport.rowconfigure(0, weight=1)
        viewport.columnconfigure(0, weight=1)
        canvas = tk.Canvas(viewport, highlightthickness=0)
        horizontal = ttk.Scrollbar(viewport, orient='horizontal', command=canvas.xview)
        vertical = ttk.Scrollbar(viewport, orient='vertical', command=canvas.yview)
        canvas.configure(xscrollcommand=horizontal.set, yscrollcommand=vertical.set)
        canvas.grid(row=0, column=0, sticky='nsew')
        vertical.grid(row=0, column=1, sticky='ns')
        horizontal.grid(row=1, column=0, sticky='ew')
        content = ttk.Frame(canvas)
        item = canvas.create_window(0, 0, window=content, anchor='nw')

        def resize_content(event=None):
            width = max(canvas.winfo_width(), content.winfo_reqwidth())
            height = max(canvas.winfo_height(), content.winfo_reqheight())
            canvas.itemconfigure(item, width=width, height=height)
            canvas.configure(scrollregion=(0, 0, width, height))

        content.bind('<Configure>', resize_content)
        canvas.bind('<Configure>', resize_content)

        def scroll_window(event):
            if isinstance(event.widget, (tk.Text, ttk.Combobox)):
                return
            if event.delta:
                canvas.yview_scroll(-int(event.delta / 120) or (-1 if event.delta > 0 else 1), 'units')
                return 'break'

        root.bind('<MouseWheel>', scroll_window, add='+')
        top=ttk.Frame(content,padding=10);top.pack(fill='x')
        ttk.Label(top,text='Family Pension Conversion',font=('Segoe UI',17,'bold')).grid(row=0,column=0,columnspan=5,sticky='w',pady=(0,10))
        ttk.Button(top,text='1. Open Chrome / Login',command=self.open_chrome).grid(row=1,column=0,padx=4)
        ttk.Label(top,text='PPO:').grid(row=1,column=1);ttk.Entry(top,textvariable=self.vars['ppo'],width=20).grid(row=1,column=2)
        ttk.Button(top,text='2. Collect case',command=lambda:self.worker(self.collect)).grid(row=1,column=3,padx=4)
        ttk.Button(top,text='Import PDF / profile text',command=self.import_pdf).grid(row=1,column=4,padx=4)
        ttk.Checkbutton(top,text='Local OCR for scanned PDFs',variable=self.ocr).grid(row=1,column=5)
        tabs=ttk.Notebook(content);tabs.pack(fill='both',expand=True,padx=10)
        form=ttk.Frame(tabs,padding=10);tabs.add(form,text='Case fields / review')
        ttk.Label(form,text='All fields can be edited. Manual changes override collected values and are saved. Dates: YYYY-MM-DD.').grid(row=0,column=0,columnspan=4,sticky='w',pady=8)
        for i,(key,label) in enumerate(FIELDS):
            r=i%10+1;col=(i//10)*2
            ttk.Label(form,text=label).grid(row=r,column=col,sticky='w',padx=5,pady=5)
            if key=='category':box=ttk.Combobox(form,textvariable=self.vars[key],values=['IDA','CDA'],state='readonly',width=30)
            else:box=ttk.Entry(form,textvariable=self.vars[key],width=33)
            box.grid(row=r,column=col+1,sticky='ew',padx=6);self.vars[key].trace_add('write',lambda *args,k=key:self.field_changed(k))
        for col in (1,3):form.columnconfigure(col,weight=1)
        ttk.Button(form,text='Show downloaded sources',command=self.open_sources).grid(row=12,column=0,pady=10)
        ttk.Button(form,text='Load saved case JSON',command=self.load_case).grid(row=12,column=1)
        ttk.Button(form,text='Save case JSON',command=self.save_case).grid(row=12,column=2)
        ttk.Button(form,text='Show saved steps / diagnostics',command=self.open_diagnostics).grid(row=12,column=3)
        self.previous_family_dob=tk.StringVar()
        self.previous_family_dob.trace_add('write', lambda *_: self.approved.set(False))
        self.previous_dob_panel=ttk.Frame(form)
        ttk.Label(self.previous_dob_panel,text='Verified DOB of preceding family pensioner (YYYY-MM-DD)').pack(side='left')
        ttk.Entry(self.previous_dob_panel,textvariable=self.previous_family_dob,width=15).pack(side='left',padx=6)
        self.previous_dob_panel.grid(row=17,column=0,columnspan=4,sticky='w')
        self.previous_dob_panel.grid_remove()
        self.conversion_history=[]
        self.revised_display=tk.StringVar()
        ttk.Label(form,textvariable=self.revised_display,wraplength=1000).grid(row=15,column=0,columnspan=4,sticky='w')
        self.death_status=tk.StringVar(value='Date of Death: awaiting conversion order and recorded date.')
        ttk.Label(form,textvariable=self.death_status,wraplength=1020).grid(row=13,column=0,columnspan=4,sticky='w',pady=6)
        ttk.Button(form,text='Confirm reviewed death date',command=self.confirm_death).grid(row=14,column=0,columnspan=2,sticky='w')
        ttk.Button(form,text='Check previous-month gross',command=self.check_previous_gross).grid(row=16,column=0,columnspan=2,sticky='w')
        ttk.Button(form,text='Review / edit commutation portions',command=self.edit_commutation_parts).grid(row=18,column=0,columnspan=2,sticky='w',pady=5)
        ttk.Button(form,text='Show manual overrides',command=self.show_overrides).grid(row=18,column=2,sticky='w')
        ttk.Button(form,text='Restore collected inputs',command=self.restore_automatic).grid(row=18,column=3,sticky='w')
        ttk.Button(form,text='Review / edit all pension histories',command=self.edit_histories).grid(row=19,column=0,columnspan=3,sticky='w',pady=5)
        pay=ttk.Frame(tabs,padding=10);tabs.add(pay,text='Payments / allocation')
        ttk.Label(pay,text='Each entry: paid_on, bill_type, gross, separate_arrear. Optional allocated_month: YYYY-MM; include: true/false.').pack(anchor='w')
        ttk.Label(pay,text='Two April regular bills map to March and April. Supplementary/arrear bills go to paid month and a review note. Gross and separate arrear are added. Reviewer allocations take priority.').pack(anchor='w',pady=5)
        ttk.Button(pay,text='Fetch / refresh payment report',command=lambda:self.worker(self.fetch_payments)).pack(anchor='w',pady=5)
        self.payment_text=tk.Text(pay,font=('Consolas',10),wrap='none');self.payment_text.pack(fill='both',expand=True);self.payment_text.insert('1.0','[]')
        notes=ttk.Frame(tabs,padding=10);tabs.add(notes,text='Sources / review notes')
        ttk.Label(notes,text='Notes below are copied under the calculation. Edit only after reviewing the source.').pack(anchor='w')
        self.note_text=tk.Text(notes,height=10);self.note_text.pack(fill='x',pady=5)
        self.source_text=tk.Text(notes,state='disabled');self.source_text.pack(fill='both',expand=True)
        bottom=ttk.Frame(content,padding=10);bottom.pack(fill='x')
        for r,label,var,action in [(0,'DR_Master.xlsx',self.rate_path,self.choose_rates),(1,'Output folder',self.output,self.choose_output)]:
            ttk.Label(bottom,text=label).grid(row=r,column=0,sticky='w');ttk.Entry(bottom,textvariable=var,width=75).grid(row=r,column=1,sticky='ew');ttk.Button(bottom,text='Browse',command=action).grid(row=r,column=2,padx=5)
        ttk.Label(bottom,text='Calculate through').grid(row=2,column=0,sticky='w');ttk.Entry(bottom,textvariable=self.end,width=20).grid(row=2,column=1,sticky='w')
        ttk.Checkbutton(bottom,text='I checked order, bank details, dates, rates, commutation and payment allocation.',variable=self.approved).grid(row=3,column=0,columnspan=3,sticky='w',pady=5)
        ttk.Button(bottom,text='3. Calculate and export Excel',command=self.export_case).grid(row=4,column=0,columnspan=3,sticky='ew')
        self.status=tk.StringVar(value='Open the dedicated Chrome window, log in manually, then enter a PPO number.');ttk.Label(content,textvariable=self.status,wraplength=1100).pack(fill='x',padx=12,pady=8)
        self.root.after(100,self.poll)

    def log(self,text):self.q.put(('status',str(text)))
    def field_changed(self,key):
        self.approved.set(False)
        if self.loading_fields:return
        if key!='ppo':
            selected=self.vars[key].get().strip();automatic=self.automatic_values.get(key,'')
            if selected!=str(automatic): self.manual_overrides[key]=dict(automatic=automatic,selected=selected)
            else:self.manual_overrides.pop(key,None)
        if key in ('death','effective'):
            self.death_confirmation=None
            if hasattr(self,'death_status'):self.refresh_death()
        if key=='ppo' and self.vars['ppo'].get()!=getattr(self,'bound_ppo',''):
            self.bound_ppo=self.vars['ppo'].get();self.report_complete=False
            self.loading_fields=True
            for k,v in self.vars.items():
                if k!='ppo':v.set('')
            self.loading_fields=False;self.manual_overrides={};self.automatic_values={};self.commutation_parts=[]
            self.candidates=[];self.sources={};self.review_notes=[];self.pay_revisions=[];self.set_conversion_history({});self.revised_display.set('');self.fma_overrides={};self.death_confirmation=None
            if hasattr(self,'death_status'):self.refresh_death()
            if hasattr(self,'payment_text'):self.payment_text.delete('1.0','end');self.payment_text.insert('1.0','[]')
            if hasattr(self,'note_text'):self.note_text.delete('1.0','end')
        elif key in ('basic','commuted','commutation_restore','effective') and hasattr(self,'revised_display'):
            self.show_revised_pension({k:v.get() for k,v in self.vars.items()})
    def worker(self,fn):
        if getattr(self,'busy',False):return messagebox.showinfo('Working','Please wait for the current collection to finish.')
        # Capture GUI values on the UI thread; Tk variables are never used by workers.
        self.snapshot={k:v.get().strip() for k,v in self.vars.items()};self.snapshot['multiple_conversions']=bool(self.conversion_history);self.snapshot_end=self.end.get();self.snapshot_ocr=self.ocr.get()
        try:
            self.active_record=Recorder(self.case_folder(self.snapshot['ppo']),fn.__name__)
            self.latest_run_path=self.active_record.folder
        except Exception as e:return messagebox.showerror('Cannot start',str(e))
        self.busy=True;self.report_complete=False
        def work():
            try:
                fn();self.active_record.finish()
            except Exception as e:
                self.active_record.finish(e)
                self.q.put(('error',str(e)+'\nSaved steps / diagnostics: '+str(self.active_record.folder)))
            finally:self.q.put(('done',None))
        threading.Thread(target=work,daemon=True).start()
    def poll(self):
        try:
            while True:
                kind,value=self.q.get_nowait()
                if kind=='status':self.status.set(value)
                elif kind=='error':self.status.set(value);messagebox.showerror('Review required',value)
                elif kind=='done':self.busy=False
                elif kind=='fields':
                    if self.vars['ppo'].get().strip()!=self.snapshot['ppo']:continue
                    self.loading_fields=True
                    self.automatic_values={k:value[0].get(k,'') for k in self.vars}
                    for k in self.vars:
                        if k not in ('ppo','death'):self.vars[k].set(self.manual_overrides.get(k,{}).get('selected',value[0].get(k,'')))
                    if 'commutation_parts' not in self.manual_overrides:self.commutation_parts=value[0].get('commutation_parts',[])
                    self.pay_revisions=value[0].get('pay_revisions',[]);self.show_revised_pension(value[0]);self.set_conversion_history(value[0]);self.sources=value[1];self.review_notes=value[2];self.note_text.delete('1.0','end');self.note_text.insert('1.0','\n'.join(self.review_notes));self.source_text.configure(state='normal');self.source_text.delete('1.0','end');self.source_text.insert('1.0',json.dumps(self.sources,indent=2));self.source_text.configure(state='disabled')
                    self.death_confirmation=None;self.refresh_death(auto=True)
                    self.loading_fields=False
                elif kind=='payments':
                    if self.vars['ppo'].get().strip()!=self.snapshot['ppo']:continue
                    self.payment_text.delete('1.0','end');self.payment_text.insert('1.0',json.dumps([payment_dict(p) for p in value],indent=2));self.report_complete=True;self.report_ppo=self.snapshot['ppo'];self.report_range=(self.snapshot.get('effective'),self.snapshot_end);self.approved.set(False)
        except queue.Empty:pass
        self.root.after(100,self.poll)
    def case_folder(self,ppo=None):
        ppo=ppo or self.vars['ppo'].get().strip()
        if not re.fullmatch(r'\d{15}',ppo):raise ValueError('Enter a 15-digit PPO number.')
        return ROOT/'cases'/ppo
    def open_chrome(self):
        candidates=[Path(os.environ.get('PROGRAMFILES','C:/Program Files'))/'Google/Chrome/Application/chrome.exe',Path(os.environ.get('PROGRAMFILES(X86)','C:/Program Files (x86)'))/'Google/Chrome/Application/chrome.exe',Path(os.environ.get('LOCALAPPDATA',''))/'Google/Chrome/Application/chrome.exe']
        chrome=next((p for p in candidates if p.is_file()),None)
        if not chrome and getattr(sys,'frozen',False):
            bundled=Path(getattr(sys,'_MEIPASS',ROOT))/'browser'
            chrome=next(bundled.rglob('chrome.exe'),None) if bundled.exists() else None
        if not chrome:return messagebox.showerror('Browser not found','Bundled browser is missing. Extract the complete portable ZIP.')
        profile=Path(os.environ.get('LOCALAPPDATA',str(ROOT)))/'FamilyPensionTool'/'ChromeProfile';profile.mkdir(parents=True,exist_ok=True)
        subprocess.Popen([str(chrome),'--remote-debugging-address=127.0.0.1','--remote-debugging-port=9222',f'--user-data-dir={profile}','https://dotpension.gov.in/'])
        self.status.set('Complete login and OTP in this dedicated Chrome window. Keep it open.')
    def collect(self):
        from .portal import Portal
        ppo=self.snapshot['ppo'];folder=self.case_folder(ppo);self.report_complete=False;self.candidates=[]
        with Portal(folder,self.log,recorder=self.active_record) as portal:
            docs,branch=portal.documents(ppo);candidates=[];warnings=[]
            self.source_branch=branch;issued=[];conversion_files=[]
            for kind,path in docs:
                with self.active_record.step('extract_source','Required fields with matching PPO and source identity',portal.page,source=path.name):
                    if kind=='structured':
                        saved=json.loads(path.read_text(encoding='utf-8'));fields=saved['fields'];notes=saved.get('notes',[])
                    else:
                        text,ocr=read_pdf(path,self.snapshot_ocr)
                        path.with_name(path.stem+'_extracted.txt').write_text(text,encoding='utf-8')
                        fields,notes=parse_text(text,'conversion' if kind=='revision' else 'original')
                        if kind=='revision' and not fields:
                            # Non-conversion commutation authority is a different source kind.
                            revision=pay_revision(text)
                            if revision:
                                original,_=parse_text(text,'original')
                                fields={'ppo':original.get('ppo'),'_pay_revision':dict(revision,source=path.name)}
                            elif re.search(r'revision\s+on\s+account\s+of\s+commutation',text,re.I):fields,notes=parse_text(text,'original')
                            else:
                                warnings.append(path.name+': not a matching family conversion order; retained for review.');continue
                        elif kind=='revision':
                            fields['_conversion_order']=True
                            conversion_files.append(path)
                        if ocr:warnings.append('OCR used for '+path.name+': verify all digits against the PDF.')
                    if kind!='structured' and branch=='Normal SAMPANN':
                        from .sanction_history import extract_order
                        event,event_notes=extract_order(text,ppo,path.name)
                        warnings.extend(event_notes)
                        if event:fields['_commutation_event']=event
                    if fields.get('ppo')!=ppo:raise ValueError('A source does not positively identify the requested PPO. Collection stopped for review.')
                    if fields.get('_issued_date'):issued.append(dt(fields['_issued_date']))
                    candidates.append((path.name,fields));warnings+=notes
                    self.active_record.checkpoint(candidates=candidates,notes=warnings)
                    self.stage_fields(candidates,warnings,branch)
            data=self.stage_fields(candidates,warnings,branch)
            if 'effective' not in data:raise ValueError('No unambiguous conversion effective date. Import/review the relevant revision PDF before fetching payments.')
            if branch=='Normal SAMPANN':
                if not issued:raise ValueError('Original document issue date unavailable for commutation query. Review retained sources.')
                gc_path=portal.commutation(ppo,min(issued).replace(month=1,day=1))
                gc=json.loads(gc_path.read_text(encoding='utf-8'));candidates.append((gc_path.name,gc['fields']));warnings+=gc.get('notes',[])
                data=self.stage_fields(candidates,warnings,branch)
            if len(conversion_files)==1:
                dest=portal.output/f'family pensioner_{ppo}.pdf'
                shutil.copy2(conversion_files[0],dest)
                self.active_record.event('source_saved',filename=dest.name,actual='Matching family conversion PDF verified')
            self.snapshot['effective']=data['effective'];start=previous_month(dt(data['effective'] if data['conversion_history'] else data.get('death') or data['effective'])).replace(day=1)
            payments=portal.payments(ppo,start,dt(self.snapshot_end));self.q.put(('payments',payments))
            self.report_query=portal.last_query
        self.log(f'{branch}: documents and complete payment report collected. Review missing/conflicting fields, then export.')

    def stage_fields(self,candidates,warnings,branch):
        current,timeline=separate_conversions(candidates)
        data,sources,conflicts=merge_candidates(current);data['ppo']=self.snapshot['ppo'];self.candidates=candidates
        data['pay_revisions']=[f['_pay_revision'] for _,f in candidates if '_pay_revision' in f]
        from .input_review import resolve_timelines
        conflicts=resolve_timelines(data,sources,conflicts,current)
        warnings=list(warnings)+[f"{r['source']}: original basic {r['basic']} effective {r['effective']}" for r in data['pay_revisions']]
        data['conversion_history']=timeline
        if timeline:
            data['previous_family_dob']=timeline[-2].get('dob','')
            warnings += [f"{order['source']}: {order['family']} effective {order['effective']}" for order in timeline]
            warnings.append('Review death-date attribution separately. Calculation switches on the latest sanction effective date.')
        self.q.put(('fields',(data,sources,warnings+conflicts)))
        partial=dict(case=dict(data,notes=warnings+conflicts),payments=[],end=self.snapshot_end,
                     report_complete=False,sources=sources,source_branch=branch)
        (self.active_record.folder/'partial_case.json').write_text(json.dumps(partial,indent=2),encoding='utf-8')
        self.active_record.checkpoint(case=data,sources=sources,notes=warnings+conflicts,source_branch=branch)
        return data
    def fetch_payments(self):
        from .portal import Portal
        start=previous_month(dt(self.snapshot['effective'] if self.snapshot.get('multiple_conversions') else self.snapshot.get('death') or self.snapshot['effective'])).replace(day=1)
        with Portal(self.case_folder(self.snapshot['ppo']),self.log,recorder=self.active_record) as portal:
            payments=portal.payments(self.snapshot['ppo'],start,dt(self.snapshot_end));self.report_query=portal.last_query
        self.q.put(('payments',payments));self.log('Payment report loaded. No returned payment means zero Drawn only after this successful query.')
    def import_pdf(self):
        path=filedialog.askopenfilename(filetypes=[('PDF or extracted text','*.pdf *.txt')])
        if not path:return
        kind='conversion' if messagebox.askyesno('Document type','Is this a conversion/updation/absorption sanction order?\nChoose No for original EPPO, Form14 or migrated profile.') else 'original'
        try:
            text,used=read_pdf(path,self.ocr.get()) if path.lower().endswith('.pdf') else (Path(path).read_text(encoding='utf-8'),False)
            fields,notes=parse_text(text,kind)
            if fields.get('ppo') and self.vars['ppo'].get() and fields['ppo']!=self.vars['ppo'].get():raise ValueError('Document PPO does not match the current case.')
            self.loading_fields=True
            for k,v in fields.items():
                if k in self.vars and k!='death' and not self.vars[k].get():
                    self.vars[k].set(v);self.automatic_values[k]=v
            incoming=fields.get('_death_dates',([fields['death']] if fields.get('death') else []))
            if incoming:
                source=str(Path(path).resolve());old=[r for r in self.sources.get('death',[]) if r[1]!=source]
                self.sources['death']=old+[(v,source) for v in incoming]
                self.death_confirmation=None
            self.refresh_death(auto=True)
            self.loading_fields=False
            self.note_text.insert('end','\n'+'\n'.join(notes+(['OCR used: verify digits in '+Path(path).name] if used else [])))
            self.source_text.configure(state='normal');self.source_text.insert('end','\n'+str(path)+'\n'+json.dumps(fields,indent=2));self.source_text.configure(state='disabled')
            self.status.set('Document read. Existing fields were preserved; compare discrepancies in Sources / review notes.')
        except Exception as e:
            self.loading_fields=False;messagebox.showerror('Import failed',str(e))
    def payments(self):
        data=json.loads(self.payment_text.get('1.0','end'))
        return [Payment(dt(p['paid_on']),p['bill_type'],D(p['gross']),D(p.get('separate_arrear',0)),p.get('allocated_month',''),p.get('include',True)) for p in data]
    def choose_rates(self):
        p=filedialog.askopenfilename(filetypes=[('Excel','*.xlsx')])
        if p:self.rate_path.set(p)
    def choose_output(self):
        p=filedialog.askdirectory()
        if p:self.output.set(p)
    def show_revised_pension(self, case):
        self.revised_display.set('')
        cutoff = case.get('effective')
        if cutoff:
            try:dt(cutoff)
            except ValueError:return
        changes = sorted(self.pay_revisions, key=lambda item: item['effective'])
        applicable = [item for item in changes if cutoff and item['effective'] < cutoff]
        if applicable:
            latest = applicable[-1]
            deduction = next((item['commuted'] for item in reversed(applicable)
                              if 'commuted' in item), case.get('commuted', ''))
            if self.commutation_parts and not ({'commuted','commutation_restore'} & self.manual_overrides.keys()):
                from .commutations import remaining
                from datetime import timedelta
                deduction=str(remaining(self.commutation_parts,dt(cutoff)-timedelta(days=1)))
            basic=self.manual_overrides.get('basic',{}).get('selected',latest['basic'])
            if 'commuted' in self.manual_overrides:deduction=self.manual_overrides['commuted']['selected']
            try:
                if not self.commutation_parts or {'commuted','commutation_restore'} & self.manual_overrides.keys():
                    restoration=self.vars['commutation_restore'].get()
                    if restoration and dt(restoration)<dt(cutoff):deduction='0'
            except ValueError:pass
            self.revised_display.set(
                f"Before conversion: monthly basic {basic}, "
                f"remaining commuted portion {deduction}. "
                f"Basic revision effective {latest['effective']} ({latest['source']}). "
                + ('Manual basic/commutation replaces the automatic rates for original-pension periods.' if {'basic','commuted','commutation_restore'} & self.manual_overrides.keys() else ''))

    def set_conversion_history(self, case):
        self.conversion_history=case.get('conversion_history',[])
        self.previous_family_dob.set(case.get('previous_family_dob',''))
        if self.conversion_history:
            self.previous_dob_panel.grid()
        else:
            self.previous_dob_panel.grid_remove()

    def data(self):
        data={k:v.get().strip() for k,v in self.vars.items()};data['notes']=[x.strip() for x in self.note_text.get('1.0','end').splitlines() if x.strip() and not x.strip().startswith(PREFIX)];data['fma_overrides']=getattr(self,'fma_overrides',{})
        data['conversion_history']=self.conversion_history
        data['previous_family_dob']=self.previous_family_dob.get().strip()
        data['pay_revisions']=getattr(self,'pay_revisions',[])
        data['commutation_parts']=self.commutation_parts
        data['manual_overrides']=self.manual_overrides.copy()
        data['automatic_values']=self.automatic_values.copy()
        data['notes'] += [f'Manual override: {k}: {v.get("automatic", "")} -> {v.get("selected", "")}' for k,v in self.manual_overrides.items()]
        state=self.death_state();data['notes']+=state['notes']
        if not state['accepted'] and getattr(self,'death_confirmation',None)==signature_key(state):
            data['notes']=[n.replace('Pending for manual review','Reviewed manually; discrepancy retained') if n.startswith(PREFIX) else n for n in data['notes']]
            data['notes'].append(f'{PREFIX} Manual review recorded; selected death date: {data["death"]}. Conversion switch remains the sanction w.e.f. date {data["effective"]}.')
        return data
    def death_state(self):
        return reconcile(self.vars['effective'].get().strip(),self.sources.get('death',[]),self.vars['death'].get().strip())
    def refresh_death(self,auto=False):
        try:
            state=self.death_state()
            if auto:
                self.vars['death'].set(self.manual_overrides.get('death',{}).get('selected',state['expected'] if state['status']=='match' else ''))
                if 'death' not in self.manual_overrides:self.automatic_values['death']=self.vars['death'].get()
                state=self.death_state()
            self.death_status.set(f'Death-date check: {state["status"].replace("_"," ")} | Expected: {state["expected"] or "awaiting w.e.f."} | Recorded: {state["details"]}')
        except ValueError:self.death_status.set('Death-date check: enter valid YYYY-MM-DD dates.')
    def confirm_death(self):
        try:
            state=self.death_state();selected=self.vars['death'].get().strip()
            if not state['expected']:raise ValueError('Enter the conversion order effective date first.')
            if not selected:raise ValueError('Review the original documents and enter the selected death date first. The expected date is a suggestion, not automatic proof.')
            if dt(selected)>=dt(self.vars['effective'].get()):raise ValueError('Selected death date must precede conversion w.e.f.; review the order and source.')
            if state['accepted']:self.status.set('Death date matches conversion w.e.f. minus one day.');return
            if messagebox.askyesno('Confirm date after manual review',f'Expected: {state["expected"]}\nRecorded: {state["details"]}\nSelected: {selected}\n\nConfirm that you checked the sources. A discrepancy note will remain in Excel.'):
                self.death_confirmation=signature_key(state);self.approved.set(False);self.status.set('Death-date manual review recorded. Complete the overall review before export.')
        except ValueError as e:messagebox.showerror('Death-date review',str(e))
    def save_case(self):
        try:
            folder=self.case_folder();folder.mkdir(parents=True,exist_ok=True);p=folder/'reviewed_case.json'
            p.write_text(json.dumps(dict(case=self.data(),payments=[payment_dict(x) for x in self.payments()],end=self.end.get(),report_complete=self.report_complete,report_ppo=getattr(self,'report_ppo',''),report_range=getattr(self,'report_range',None),report_query=getattr(self,'report_query',None),source_branch=getattr(self,'source_branch',''),sources=self.sources,death_confirmation=getattr(self,'death_confirmation',None)),indent=2),encoding='utf-8');self.status.set('Saved '+str(p))
        except Exception as e:messagebox.showerror('Save failed',str(e))
    def load_case(self):
        p=filedialog.askopenfilename(filetypes=[('Case JSON','*.json')])
        if not p:return
        try:
            data=json.loads(Path(p).read_text());c=data['case']
            self.loading_fields=True
            for k in self.vars:self.vars[k].set(c.get(k,''))
            self.bound_ppo=c.get('ppo','');self.automatic_values=c.get('automatic_values',{k:c.get(k,'') for k in self.vars});self.manual_overrides=c.get('manual_overrides',{});self.commutation_parts=c.get('commutation_parts',[])
            self.loading_fields=False
            self.note_text.delete('1.0','end');self.note_text.insert('1.0','\n'.join(c.get('notes',[])));self.fma_overrides=c.get('fma_overrides',{});self.pay_revisions=c.get('pay_revisions',[]);self.show_revised_pension(c);self.set_conversion_history(c)
            self.payment_text.delete('1.0','end');self.payment_text.insert('1.0',json.dumps(data['payments'],indent=2));self.end.set(data['end']);self.report_complete=data.get('report_complete',False);self.report_ppo=data.get('report_ppo','');self.report_range=data.get('report_range');self.sources=data.get('sources',{});self.approved.set(False)
            self.death_confirmation=data.get('death_confirmation');self.refresh_death()
            self.source_branch=data.get('source_branch','');self.report_query=data.get('report_query')
        except Exception as e:
            self.loading_fields=False
            messagebox.showerror('Load failed',str(e))
    def show_overrides(self):
        messagebox.showinfo('Manual overrides', '\n'.join(f'{k}: {v.get("automatic", "")} -> {v.get("selected", "")}' for k,v in self.manual_overrides.items()) or 'No manual overrides recorded.')

    def restore_automatic(self):
        self.loading_fields=True
        try:
            for key,change in self.manual_overrides.items():
                if key in self.vars:self.vars[key].set(change.get('automatic',''))
                elif key in ('pay_revisions','conversion_history','commutation_parts','fma_overrides'):setattr(self,key,change.get('automatic',{} if key=='fma_overrides' else []))
            self.manual_overrides.clear();self.approved.set(False)
        finally:self.loading_fields=False
        self.refresh_death()

    def edit_histories(self):
        window=tk.Toplevel(self.root);window.title('Pension histories / monthly FMA overrides');window.geometry('950x600')
        before={key:getattr(self,key,{} if key=='fma_overrides' else []) for key in ('pay_revisions','conversion_history','commutation_parts','fma_overrides')}
        text=tk.Text(window,wrap='none',font=('Consolas',10),undo=True);text.pack(fill='both',expand=True);text.insert('1.0',json.dumps(before,indent=2))
        ttk.Label(window,text='Edit/add/remove dated records. FMA overrides use YYYY-MM and monthly amount.').pack()
        def save():
            try:
                selected=json.loads(text.get('1.0','end'))
                for key,value in selected.items():
                    if key not in before:raise ValueError('Unknown history field: '+key)
                    setattr(self,key,value);self.manual_overrides[key]=dict(automatic=before[key],selected=value)
                self.approved.set(False);window.destroy()
            except Exception as error:messagebox.showerror('Review',str(error),parent=window)
        ttk.Button(window,text='Save reviewed histories',command=save).pack(pady=8)

    def edit_commutation_parts(self):
        window=tk.Toplevel(self.root);window.title('Commutation portions â€” monthly deduction, not lump sum')
        parts=[dict(p) for p in self.commutation_parts]
        tree=ttk.Treeview(window,columns=('amount','restore','source'),show='headings',height=10)
        for key,label in [('amount','Monthly portion'),('restore','Restoration date'),('source','Source')]:
            tree.heading(key,text=label);tree.column(key,width=180)
        tree.pack(fill='both',expand=True)
        def refresh():
            tree.delete(*tree.get_children())
            for i,p in enumerate(parts):tree.insert('', 'end', iid=str(i),values=(p['amount'],p['restore'],p.get('source','Manual entry')))
        def edit(add=False):
            selected=tree.selection()
            if not add and not selected:return
            index=int(selected[0]) if selected and not add else len(parts)
            item=parts[index] if index<len(parts) else {}
            amount=simpledialog.askstring('Monthly commutation portion','Monthly portion amount (not progressive total):',initialvalue=item.get('amount',''),parent=window)
            if amount is None:return
            restore=simpledialog.askstring('Restoration date','YYYY-MM-DD:',initialvalue=item.get('restore',''),parent=window)
            if restore is None:return
            try:
                from .commutations import remaining
                value=dict(amount=str(D(amount)),restore=dt(restore).isoformat(),source='Manual entry / review')
                remaining([value],date.today())
                if index==len(parts):parts.append(value)
                else:parts[index]=value
                refresh()
            except Exception as error:messagebox.showerror('Review portion',str(error),parent=window)
        def remove():
            if tree.selection():parts.pop(int(tree.selection()[0]));refresh()
        buttons=ttk.Frame(window);buttons.pack(fill='x')
        ttk.Button(buttons,text='Add portion',command=lambda:edit(True)).pack(side='left')
        ttk.Button(buttons,text='Edit selected',command=edit).pack(side='left')
        ttk.Button(buttons,text='Remove selected',command=remove).pack(side='left')
        ttk.Label(window,text='Each row is an individual monthly portion. Editing the main commutation amount/date replaces this schedule.').pack(padx=10,pady=6)
        refresh()
        def save():
            try:
                from .commutations import remaining
                remaining(parts,date.today())
                before=self.commutation_parts
                self.commutation_parts=parts
                self.manual_overrides['commutation_parts']=dict(automatic=before,selected=parts)
                if self.vars['effective'].get():
                    from datetime import timedelta
                    self.loading_fields=True
                    self.vars['commuted'].set(str(remaining(parts,dt(self.vars['effective'].get())-timedelta(days=1))))
                    active=[p['restore'] for p in parts if D(p['amount']) and dt(p['restore'])>dt(self.vars['effective'].get())-timedelta(days=1)]
                    self.vars['commutation_restore'].set(max(active,default=''))
                    self.loading_fields=False
                    self.manual_overrides.pop('commuted',None);self.manual_overrides.pop('commutation_restore',None)
                self.approved.set(False);window.destroy()
            except Exception as error:
                self.loading_fields=False;messagebox.showerror('Review portions',str(error))
        ttk.Button(window,text='Save reviewed portions',command=save).pack(pady=8)
    def open_sources(self):
        try:
            path=self.case_folder();path.mkdir(parents=True,exist_ok=True)
            if os.name=='nt':os.startfile(path)
        except Exception as e:messagebox.showerror('Sources',str(e))
    def open_diagnostics(self):
        path=getattr(self,'latest_run_path',None)
        if path and path.is_dir() and os.name=='nt':os.startfile(path)
        else:messagebox.showinfo('Saved steps','No collection run recorded in this session yet.')
    def check_previous_gross(self):
        try:
            case = Case.from_dict(self.data())
            month = previous_month(case.effective if case.conversion_history else case.death).strftime('%Y-%m')
            if not self.report_complete or getattr(self, 'report_ppo', '') != case.ppo:
                raise ValueError('Collect or refresh the payment report first.')
            gross = regular_gross_from_history(self.payments(), previous_month(case.effective if case.conversion_history else case.death))
            rates = load_rates(self.rate_path.get()) if gross is not None else []
            note = previous_month_check(case, rates, gross)
            self.note_text.insert('end', '\n' + note + '\n')
            self.approved.set(False)
            messagebox.showinfo('Previous-month gross', note)
        except Exception as error:
            messagebox.showerror('Cross-check unavailable', str(error))

    def export_case(self):
        record=None
        try:
            if getattr(self,'busy',False):raise ValueError('Wait for collection to finish.')
            record=Recorder(self.case_folder(),'calculate_export');self.latest_run_path=record.folder
            record.checkpoint(case=self.data(),end=self.end.get(),report_query=getattr(self,'report_query',None))
            c=Case.from_dict(self.data())
            state=self.death_state()
            if not state['accepted'] and getattr(self,'death_confirmation',None)!=signature_key(state):raise ValueError('Death date needs manual review. Compare expected/recorded dates, enter the verified date, and click Confirm reviewed death date. The discrepancy note will be retained.')
            if not self.approved.get():raise ValueError('Review the source fields and tick the review checkbox.')
            if not self.report_complete or getattr(self,'report_ppo','')!=c.ppo:raise ValueError('A complete successful payment report query is required. Fetch the report first.')
            if tuple(self.report_range or ())!=(str(c.effective),self.end.get()):raise ValueError('Effective/end date changed after payment collection. Fetch the report again.')
            with record.step('calculate','Validated category/rates, existing payment allocation and arithmetic'):
                rates=load_rates(self.rate_path.get());result=calculate(c,rates,self.payments(),self.end.get())
            try:
                gross = regular_gross_from_history(self.payments(), previous_month(c.effective if c.conversion_history else c.death))
                result['notes'].append(previous_month_check(c, rates, gross))
            except ValueError as error:
                result['notes'].append(f'Previous-month gross cross-check unavailable: {error}')
            with record.step('export_excel','Standard-format workbook saved'):
                dest=export(c,result,self.output.get())
                record.checkpoint(output=str(dest),due=str(result['due']),drawn=str(result['drawn']),difference=str(result['difference']))
            self.save_case();record.finish()
            self.settings_file.write_text(json.dumps({'rates':self.rate_path.get(),'output':self.output.get()},indent=2));self.status.set(f'Saved {dest.name} | Due {result["due"]:,.0f} | Drawn {result["drawn"]:,.0f} | Difference {result["difference"]:,.0f}')
            messagebox.showinfo('Excel saved',str(dest))
        except Exception as e:
            if record:record.finish(e)
            messagebox.showerror('Export stopped',str(e)+(('\nSaved steps / diagnostics: '+str(record.folder)) if record else ''))

def main():
    root=tk.Tk();ttk.Style().theme_use('clam');App(root);root.mainloop()
