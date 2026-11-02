from pathlib import Path
from datetime import date
from dataclasses import asdict
import json,os,re,subprocess,threading,queue,traceback,sys
import tkinter as tk
from tkinter import ttk,filedialog,messagebox
from .engine import Case,Payment,D,dt,previous_month,calculate,load_rates
from .extract import read_pdf,parse_text,merge_candidates
from .exporter import export
from .death_review import reconcile,signature_key,PREFIX

ROOT=Path(sys.executable).resolve().parent if getattr(sys,'frozen',False) else Path(__file__).resolve().parent.parent
FIELDS=[('ppo','PPO number (15 digits)'),('category','IDA / CDA'),('pensioner','Original pensioner name'),('family','Family pensioner name'),('pensioner_dob','Original date of birth'),('family_dob','Family date of birth'),('death','Date of death'),('effective','Conversion effective date'),('basic','Original basic pension'),('commuted','Monthly commuted portion'),('commutation_restore','Commutation restoration date'),('fma_before','Medical allowance before'),('enhanced','Enhanced family pension'),('enhanced_until','Enhanced rate up to'),('normal','Normal family pension'),('normal_from','Normal rate from'),('fma_after','Medical allowance after'),('account','Family bank account number'),('ifsc','IFSC code')]

def json_default(value):return str(value)
def payment_dict(p):return {k:str(v) if k not in ('include',) else v for k,v in asdict(p).items()}

class App:
    def __init__(self,root):
        self.root=root;root.title('Family Pension Conversion — Due / Drawn');root.geometry('1130x810');self.q=queue.Queue();self.candidates=[];self.sources={};self.review_notes=[];self.report_complete=False
        self.settings_file=ROOT/'settings.json';self.settings=json.loads(self.settings_file.read_text()) if self.settings_file.exists() else {}
        self.vars={k:tk.StringVar() for k,_ in FIELDS};self.rate_path=tk.StringVar(value=self.settings.get('rates',''));self.output=tk.StringVar(value=self.settings.get('output',str(ROOT/'output')));self.end=tk.StringVar(value=str(previous_month()));self.ocr=tk.BooleanVar(value=False);self.approved=tk.BooleanVar(value=False)
        top=ttk.Frame(root,padding=10);top.pack(fill='x')
        ttk.Label(top,text='Family Pension Conversion',font=('Segoe UI',17,'bold')).grid(row=0,column=0,columnspan=5,sticky='w',pady=(0,10))
        ttk.Button(top,text='1. Open Chrome / Login',command=self.open_chrome).grid(row=1,column=0,padx=4)
        ttk.Label(top,text='PPO:').grid(row=1,column=1);ttk.Entry(top,textvariable=self.vars['ppo'],width=20).grid(row=1,column=2)
        ttk.Button(top,text='2. Collect case',command=lambda:self.worker(self.collect)).grid(row=1,column=3,padx=4)
        ttk.Button(top,text='Import PDF / profile text',command=self.import_pdf).grid(row=1,column=4,padx=4)
        ttk.Checkbutton(top,text='Local OCR for scanned PDFs',variable=self.ocr).grid(row=1,column=5)
        tabs=ttk.Notebook(root);tabs.pack(fill='both',expand=True,padx=10)
        form=ttk.Frame(tabs,padding=10);tabs.add(form,text='Case fields / review')
        ttk.Label(form,text='Dates: YYYY-MM-DD. Blank or conflicting fields must be resolved from the source document.').grid(row=0,column=0,columnspan=4,sticky='w',pady=8)
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
        self.death_status=tk.StringVar(value='Date of Death: awaiting conversion order and recorded date.')
        ttk.Label(form,textvariable=self.death_status,wraplength=1020).grid(row=13,column=0,columnspan=4,sticky='w',pady=6)
        ttk.Button(form,text='Confirm reviewed death date',command=self.confirm_death).grid(row=14,column=0,columnspan=2,sticky='w')
        pay=ttk.Frame(tabs,padding=10);tabs.add(pay,text='Payments / allocation')
        ttk.Label(pay,text='Each entry: paid_on, bill_type, gross, separate_arrear. Optional allocated_month: YYYY-MM; include: true/false.').pack(anchor='w')
        ttk.Label(pay,text='Two April regular bills map to March and April. Supplementary/arrear bills go to paid month and a review note. Separate arrear column is excluded.').pack(anchor='w',pady=5)
        ttk.Button(pay,text='Fetch / refresh payment report',command=lambda:self.worker(self.fetch_payments)).pack(anchor='w',pady=5)
        self.payment_text=tk.Text(pay,font=('Consolas',10),wrap='none');self.payment_text.pack(fill='both',expand=True);self.payment_text.insert('1.0','[]')
        notes=ttk.Frame(tabs,padding=10);tabs.add(notes,text='Sources / review notes')
        ttk.Label(notes,text='Notes below are copied under the calculation. Edit only after reviewing the source.').pack(anchor='w')
        self.note_text=tk.Text(notes,height=10);self.note_text.pack(fill='x',pady=5)
        self.source_text=tk.Text(notes,state='disabled');self.source_text.pack(fill='both',expand=True)
        bottom=ttk.Frame(root,padding=10);bottom.pack(fill='x')
        for r,label,var,action in [(0,'DR_Master.xlsx',self.rate_path,self.choose_rates),(1,'Output folder',self.output,self.choose_output)]:
            ttk.Label(bottom,text=label).grid(row=r,column=0,sticky='w');ttk.Entry(bottom,textvariable=var,width=75).grid(row=r,column=1,sticky='ew');ttk.Button(bottom,text='Browse',command=action).grid(row=r,column=2,padx=5)
        ttk.Label(bottom,text='Calculate through').grid(row=2,column=0,sticky='w');ttk.Entry(bottom,textvariable=self.end,width=20).grid(row=2,column=1,sticky='w')
        ttk.Checkbutton(bottom,text='I checked order, bank details, dates, rates, commutation and payment allocation.',variable=self.approved).grid(row=3,column=0,columnspan=3,sticky='w',pady=5)
        ttk.Button(bottom,text='3. Calculate and export Excel',command=self.export_case).grid(row=4,column=0,columnspan=3,sticky='ew')
        self.status=tk.StringVar(value='Open the dedicated Chrome window, log in manually, then enter a PPO number.');ttk.Label(root,textvariable=self.status,wraplength=1100).pack(fill='x',padx=12,pady=8)
        self.root.after(100,self.poll)

    def log(self,text):self.q.put(('status',str(text)))
    def field_changed(self,key):
        self.approved.set(False)
        if key in ('death','effective'):
            self.death_confirmation=None
            if hasattr(self,'death_status'):self.refresh_death()
        if key=='ppo' and self.vars['ppo'].get()!=getattr(self,'bound_ppo',''):
            self.bound_ppo=self.vars['ppo'].get();self.report_complete=False
            for k,v in self.vars.items():
                if k!='ppo':v.set('')
            self.candidates=[];self.sources={};self.review_notes=[];self.fma_overrides={};self.death_confirmation=None
            if hasattr(self,'death_status'):self.refresh_death()
            if hasattr(self,'payment_text'):self.payment_text.delete('1.0','end');self.payment_text.insert('1.0','[]')
            if hasattr(self,'note_text'):self.note_text.delete('1.0','end')
    def worker(self,fn):
        if getattr(self,'busy',False):return messagebox.showinfo('Working','Please wait for the current collection to finish.')
        # Capture GUI values on the UI thread; Tk variables are never used by workers.
        self.snapshot={k:v.get().strip() for k,v in self.vars.items()};self.snapshot_end=self.end.get();self.snapshot_ocr=self.ocr.get();self.busy=True
        def work():
            try:fn()
            except Exception as e:self.q.put(('error',str(e)))
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
                    for k,v in value[0].items():
                        if k in self.vars and k!='death':self.vars[k].set(v)
                    self.sources=value[1];self.review_notes=value[2];self.note_text.delete('1.0','end');self.note_text.insert('1.0','\n'.join(self.review_notes));self.source_text.configure(state='normal');self.source_text.delete('1.0','end');self.source_text.insert('1.0',json.dumps(self.sources,indent=2));self.source_text.configure(state='disabled')
                    self.death_confirmation=None;self.refresh_death(auto=True)
                elif kind=='payments':
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
        subprocess.Popen([str(chrome),'--remote-debugging-address=127.0.0.1','--remote-debugging-port=9222',f'--user-data-dir={profile}','https://dotpension.gov.in/Login/Index'])
        self.status.set('Complete login and OTP in this dedicated Chrome window. Keep it open.')
    def collect(self):
        from .portal import Portal
        ppo=self.snapshot['ppo'];folder=self.case_folder(ppo);self.report_complete=False;self.candidates=[]
        with Portal(folder,self.log) as portal:
            docs,branch=portal.documents(ppo);candidates=[];warnings=[]
            for kind,path in docs:
                text,ocr=read_pdf(path,self.snapshot_ocr) if path.suffix=='.pdf' else (path.read_text(encoding='utf-8'),False)
                (folder/(path.stem+'_extracted.txt')).write_text(text,encoding='utf-8')
                fields,notes=parse_text(text,'conversion' if kind=='conversion' else 'original')
                if fields.get('ppo') and fields['ppo']!=ppo:raise ValueError('A document has a different PPO. Collection stopped.')
                if ocr:warnings.append('OCR used for '+path.name+': verify all digits against the PDF.')
                candidates.append((path.name,fields));warnings+=notes
            data,sources,conflicts=merge_candidates(candidates)
            data['ppo']=ppo;self.candidates=candidates
            self.q.put(('fields',(data,sources,warnings+conflicts)))
            if 'effective' not in data:raise ValueError('No unambiguous conversion effective date. Import/review the relevant revision PDF before fetching payments.')
            self.snapshot['effective']=data['effective'];start=dt(data['effective']).replace(day=1)
            payments=portal.payments(ppo,start,dt(self.snapshot_end));self.q.put(('payments',payments))
        self.log(f'{branch}: documents and complete payment report collected. Review missing/conflicting fields, then export.')
    def fetch_payments(self):
        from .portal import Portal
        start=dt(self.snapshot['effective']).replace(day=1)
        with Portal(self.case_folder(self.snapshot['ppo']),self.log) as portal:payments=portal.payments(self.snapshot['ppo'],start,dt(self.snapshot_end))
        self.q.put(('payments',payments));self.log('Payment report loaded. No returned payment means zero Drawn only after this successful query.')
    def import_pdf(self):
        path=filedialog.askopenfilename(filetypes=[('PDF or extracted text','*.pdf *.txt')])
        if not path:return
        kind='conversion' if messagebox.askyesno('Document type','Is this a conversion/updation/absorption sanction order?\nChoose No for original EPPO, Form14 or migrated profile.') else 'original'
        try:
            text,used=read_pdf(path,self.ocr.get()) if path.lower().endswith('.pdf') else (Path(path).read_text(encoding='utf-8'),False)
            fields,notes=parse_text(text,kind)
            if fields.get('ppo') and self.vars['ppo'].get() and fields['ppo']!=self.vars['ppo'].get():raise ValueError('Document PPO does not match the current case.')
            for k,v in fields.items():
                if k in self.vars and k!='death' and not self.vars[k].get():self.vars[k].set(v)
            incoming=fields.get('_death_dates',([fields['death']] if fields.get('death') else []))
            if incoming:
                source=str(Path(path).resolve());old=[r for r in self.sources.get('death',[]) if r[1]!=source]
                self.sources['death']=old+[(v,source) for v in incoming]
                self.death_confirmation=None
            self.refresh_death(auto=True)
            self.note_text.insert('end','\n'+'\n'.join(notes+(['OCR used: verify digits in '+Path(path).name] if used else [])))
            self.source_text.configure(state='normal');self.source_text.insert('end','\n'+str(path)+'\n'+json.dumps(fields,indent=2));self.source_text.configure(state='disabled')
            self.status.set('Document read. Existing fields were preserved; compare discrepancies in Sources / review notes.')
        except Exception as e:messagebox.showerror('Import failed',str(e))
    def payments(self):
        data=json.loads(self.payment_text.get('1.0','end'))
        return [Payment(dt(p['paid_on']),p['bill_type'],D(p['gross']),D(p.get('separate_arrear',0)),p.get('allocated_month',''),p.get('include',True)) for p in data]
    def choose_rates(self):
        p=filedialog.askopenfilename(filetypes=[('Excel','*.xlsx')])
        if p:self.rate_path.set(p)
    def choose_output(self):
        p=filedialog.askdirectory()
        if p:self.output.set(p)
    def data(self):
        data={k:v.get().strip() for k,v in self.vars.items()};data['notes']=[x.strip() for x in self.note_text.get('1.0','end').splitlines() if x.strip() and not x.strip().startswith(PREFIX)];data['fma_overrides']=getattr(self,'fma_overrides',{})
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
                self.vars['death'].set(state['expected'] if state['status']=='match' else '')
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
            p.write_text(json.dumps(dict(case=self.data(),payments=[payment_dict(x) for x in self.payments()],end=self.end.get(),report_complete=self.report_complete,report_ppo=getattr(self,'report_ppo',''),report_range=getattr(self,'report_range',None),sources=self.sources,death_confirmation=getattr(self,'death_confirmation',None)),indent=2),encoding='utf-8');self.status.set('Saved '+str(p))
        except Exception as e:messagebox.showerror('Save failed',str(e))
    def load_case(self):
        p=filedialog.askopenfilename(filetypes=[('Case JSON','*.json')])
        if not p:return
        try:
            data=json.loads(Path(p).read_text());c=data['case']
            for k in self.vars:self.vars[k].set(c.get(k,''))
            self.note_text.delete('1.0','end');self.note_text.insert('1.0','\n'.join(c.get('notes',[])));self.fma_overrides=c.get('fma_overrides',{})
            self.payment_text.delete('1.0','end');self.payment_text.insert('1.0',json.dumps(data['payments'],indent=2));self.end.set(data['end']);self.report_complete=data.get('report_complete',False);self.report_ppo=data.get('report_ppo','');self.report_range=data.get('report_range');self.sources=data.get('sources',{});self.approved.set(False)
            self.death_confirmation=data.get('death_confirmation');self.refresh_death()
        except Exception as e:messagebox.showerror('Load failed',str(e))
    def open_sources(self):
        try:
            path=self.case_folder();path.mkdir(parents=True,exist_ok=True)
            if os.name=='nt':os.startfile(path)
        except Exception as e:messagebox.showerror('Sources',str(e))
    def export_case(self):
        try:
            if getattr(self,'busy',False):raise ValueError('Wait for collection to finish.')
            c=Case.from_dict(self.data())
            state=self.death_state()
            if not state['accepted'] and getattr(self,'death_confirmation',None)!=signature_key(state):raise ValueError('Death date needs manual review. Compare expected/recorded dates, enter the verified date, and click Confirm reviewed death date. The discrepancy note will be retained.')
            if not self.approved.get():raise ValueError('Review the source fields and tick the review checkbox.')
            if not self.report_complete or getattr(self,'report_ppo','')!=c.ppo:raise ValueError('A complete successful payment report query is required. Fetch the report first.')
            if tuple(self.report_range or ())!=(str(c.effective),self.end.get()):raise ValueError('Effective/end date changed after payment collection. Fetch the report again.')
            rates=load_rates(self.rate_path.get());result=calculate(c,rates,self.payments(),self.end.get());dest=export(c,result,self.output.get());self.save_case()
            self.settings_file.write_text(json.dumps({'rates':self.rate_path.get(),'output':self.output.get()},indent=2));self.status.set(f'Saved {dest.name} | Due {result["due"]:,.0f} | Drawn {result["drawn"]:,.0f} | Difference {result["difference"]:,.0f}')
            messagebox.showinfo('Excel saved',str(dest))
        except Exception as e:messagebox.showerror('Export stopped',str(e))

def main():
    root=tk.Tk();ttk.Style().theme_use('clam');App(root);root.mainloop()
