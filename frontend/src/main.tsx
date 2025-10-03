import React, { useCallback, useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { listDocuments, uploadPDF, getDocument, addHighlight, updateProfile, clearHighlights, startAuto, pollAuto, fetchAutoDoc, cancelAuto, AnnotationDocument, Rect, API_BASE } from './api';
import * as pdfjsLib from 'pdfjs-dist';
import 'pdfjs-dist/build/pdf.worker.mjs';

(pdfjsLib as any).GlobalWorkerOptions.workerSrc = 'pdfjs-dist/build/pdf.worker.mjs';

interface DragRect { x:number; y:number; w:number; h:number; }

const App: React.FC = () => {
  const [docs,setDocs]=useState<AnnotationDocument[]>([]);
  const [current,setCurrent]=useState<AnnotationDocument|undefined>();
  const [runId,setRunId]=useState<string|undefined>();
  const [autoState,setAutoState]=useState<string>('idle');
  const fileInputRef = useRef<HTMLInputElement|null>(null);
  const [showProfile,setShowProfile]=useState(false);
  const [profileGP,setProfileGP]=useState('');
  const [profileGoal,setProfileGoal]=useState('');
  const [profileDensity,setProfileDensity]=useState(0.10);
  const pdfContainerRef = useRef<HTMLDivElement|null>(null);
  const [pdfDoc,setPdfDoc]=useState<any>();
  const [drag,setDrag]=useState<DragRect|null>(null);
  const dragStart = useRef<{x:number;y:number}|null>(null);

  const refreshDocs = async()=>{ setDocs(await listDocuments()); };
  useEffect(()=>{ refreshDocs(); },[]);

  useEffect(()=>{ if(current){ setProfileGP(current.global_profile||''); setProfileGoal(current.document_goal||''); setProfileDensity(current.highlight_density_target); loadPDF(); }},[current?.id]);

  const onUpload = async(e:React.ChangeEvent<HTMLInputElement>)=>{
    const f = e.target.files?.[0];
    if(!f) return;
    const res = await uploadPDF(f);
    await refreshDocs();
    const doc = (await listDocuments()).find(d=>d.id===res.document_id);
    setCurrent(doc);
  };

  const loadPDF = async()=>{
    if(!current) return;
    // Use backend static mount /pdfs/<filename>
    const pdfUrl = `${API_BASE}/pdfs/${current.filename}`;
    const loadingTask = (pdfjsLib as any).getDocument(pdfUrl);
    const pdf = await loadingTask.promise; setPdfDoc(pdf);
  };

  const drawPages = async()=>{
    if(!pdfDoc || !pdfContainerRef.current) return;
    const container = pdfContainerRef.current; container.innerHTML='';
    for(let i=0;i<pdfDoc.numPages;i++){
      const page = await pdfDoc.getPage(i+1);
      const viewport = page.getViewport({scale:1.3});
      const canvas = document.createElement('canvas');
      canvas.width = viewport.width; canvas.height = viewport.height;
      const ctx = canvas.getContext('2d')!;
      await page.render({canvasContext:ctx, viewport}).promise;
      const wrapper = document.createElement('div'); wrapper.className='page-wrapper'; wrapper.style.width=viewport.width+'px';
      wrapper.dataset['pageIndex'] = String(i);
      wrapper.appendChild(canvas);
      const overlay = document.createElement('div'); overlay.className='overlay';
      wrapper.appendChild(overlay);
      container.appendChild(wrapper);
    }
    renderHighlights();
  };
  // Render pages only when PDF changes (avoid page order shuffle/flicker on highlight updates)
  useEffect(()=>{ drawPages(); },[pdfDoc]);

  // Separate effect to (re)draw highlights when highlight set changes
  useEffect(()=>{ renderHighlights(); },[current?.highlights]);

  const renderHighlights = ()=>{
    if(!current || !pdfContainerRef.current) return;
    // Clear old highlight nodes only (preserve canvases)
    pdfContainerRef.current.querySelectorAll('.overlay').forEach(ov=>{ (ov as HTMLElement).innerHTML=''; });
    current.highlights.forEach(h=>{
      const wrapper = pdfContainerRef.current?.querySelector(`.page-wrapper[data-page-index='${h.page_index}']`) as HTMLElement;
      if(!wrapper) return;
      const overlay = wrapper.querySelector('.overlay') as HTMLElement;
      h.rects.forEach(r=>{
        const d = document.createElement('div');
        d.className = 'rect'+(h.auto_generated?' auto':'');
        d.style.left = r.x1*1.3 + 'px';
        d.style.top = r.y1*1.3 + 'px';
        d.style.width = (r.x2-r.x1)*1.3 + 'px';
        d.style.height = (r.y2-r.y1)*1.3 + 'px';
        d.title = h.note||'';
        overlay.appendChild(d);
      });
    });
  };

  const handleMouseDown = (e:React.MouseEvent)=>{
    const target = (e.target as HTMLElement).closest('.page-wrapper') as HTMLElement|null;
    if(!target) return;
    const rect = target.getBoundingClientRect();
    dragStart.current = {x:e.clientX-rect.left, y:e.clientY-rect.top};
    setDrag({x:dragStart.current.x,y:dragStart.current.y,w:0,h:0});
  };
  const handleMouseMove = (e:React.MouseEvent)=>{
    if(!dragStart.current) return;
    const target = (e.target as HTMLElement).closest('.page-wrapper') as HTMLElement|null;
    if(!target) return;
    const rect = target.getBoundingClientRect();
    const x = e.clientX-rect.left; const y = e.clientY-rect.top;
    setDrag({x:Math.min(x,dragStart.current.x), y:Math.min(y,dragStart.current.y), w:Math.abs(x-dragStart.current.x), h:Math.abs(y-dragStart.current.y)});
  };
  const handleMouseUp = async(e:React.MouseEvent)=>{
    if(!dragStart.current || !drag) { setDrag(null); return; }
    const target = (e.target as HTMLElement).closest('.page-wrapper') as HTMLElement|null;
    if(!target || !current) { setDrag(null); return; }
    const pageIndex = parseInt(target.dataset['pageIndex']||'0',10);
    // Convert back to PDF point coordinates dividing by scale
    const scale = 1.3;
    const rect: Rect = { x1: drag.x/scale, y1: drag.y/scale, x2:(drag.x+drag.w)/scale, y2:(drag.y+drag.h)/scale };
    const updated = await addHighlight(current.id, pageIndex, [rect]);
    setCurrent(updated);
    setDrag(null); dragStart.current=null;
  };

  const saveProfile = async()=>{
    if(!current) return;
    const updated = await updateProfile(current.id, profileGP, profileGoal, profileDensity);
    setCurrent(updated); setShowProfile(false);
  };

  const triggerAuto = async()=>{
    if(!current) return;
    if(autoState==='running') return;
    const st = await startAuto(current.id, profileDensity);
    setRunId(st.run_id); setAutoState(st.state); pollLoop(current.id, st.run_id);
  };
  const doCancel = async()=>{
    if(!current || !runId) return;
    await cancelAuto(current.id, runId);
    setAutoState('cancelling');
  };
  const pollLoop = async(docId:string, run:string)=>{
    let active=true; while(active){
      await new Promise(r=>setTimeout(r, 1200));
      const st = await pollAuto(docId, run); setAutoState(st.state);
      const doc = await getDocument(docId); setCurrent(doc);
      if(st.state !== 'running'){ active=false; }
    }
  };

  const scrollToHighlight = (h: any)=>{
    if(!pdfContainerRef.current) return;
    const wrapper = pdfContainerRef.current.querySelector(`.page-wrapper[data-page-index='${h.page_index}']`) as HTMLElement;
    if(wrapper){
      wrapper.scrollIntoView({behavior:'smooth', block:'center'});
      // Flash the first rect
      const firstRect = wrapper.querySelector('.overlay .rect');
      if(firstRect){
        firstRect.classList.add('flash');
        setTimeout(()=>firstRect.classList.remove('flash'), 1400);
      }
    }
  };

  return <div style={{display:'flex',flexDirection:'column',height:'100%'}}>
    <div className='toolbar'>
      <button onClick={()=>fileInputRef.current?.click()}>Upload PDF</button>
      <input ref={fileInputRef} type='file' style={{display:'none'}} onChange={onUpload} />
      <select value={current?.id||''} onChange={e=>{ const d=docs.find(x=>x.id===e.target.value); setCurrent(d); }}>
        <option value=''>--Select Document--</option>
        {docs.map(d=> <option key={d.id} value={d.id}>{d.filename}</option>)}
      </select>
      <button disabled={!current} onClick={()=>setShowProfile(true)}>Profile/Goal</button>
      <div className='run-actions'>
        <button disabled={!current || autoState==='running' || autoState==='cancelling'} onClick={triggerAuto}>LLM Auto Highlight {autoState==='running' && <span className='badge'>Running</span>}</button>
        {autoState==='running' && <button onClick={doCancel}>Cancel</button>}
        {autoState==='cancelling' && <span style={{fontStyle:'italic'}}>Cancelling…</span>}
      </div>
      <button disabled={!current} onClick={async()=>{ if(!current) return; await clearHighlights(current.id); const refreshed = await getDocument(current.id); setCurrent(refreshed); }}>Clear HLs</button>
    </div>
    <div className='layout' onMouseDown={handleMouseDown} onMouseMove={handleMouseMove} onMouseUp={handleMouseUp}>
      <div className='pdf-container' ref={pdfContainerRef} style={{flex:1,position:'relative',overflow:'auto'}}>
        {drag && <div className='drag-rect' style={{left:drag.x,top:drag.y,width:drag.w,height:drag.h}} />}
      </div>
      <div className='sidepanel'>
        <div style={{padding:'8px',borderBottom:'1px solid #ddd',fontWeight:'bold'}}>Highlights ({current?.highlights.length||0})</div>
        <div style={{flex:1,overflow:'auto'}}>
          {current?.highlights.slice().sort((a,b)=> a.page_index - b.page_index).map(h=> <div className='highlight-item' key={h.id} onClick={()=>scrollToHighlight(h)}>{`Pg ${h.page_index+1}`} {h.note && <span style={{flex:1}}>- {h.note.slice(0,60)}</span>}</div>)}
        </div>
        <div className='status-bar'>State: {autoState}</div>
      </div>
    </div>
    {showProfile && <div className='profile-dialog'>
      <h3>Profile & Goal</h3>
      <label>Global Profile<br/><textarea value={profileGP} onChange={e=>setProfileGP(e.target.value)} rows={4} style={{width:'100%'}} /></label>
      <label>Document Goal<br/><textarea value={profileGoal} onChange={e=>setProfileGoal(e.target.value)} rows={4} style={{width:'100%'}} /></label>
      <label>Density {Math.round(profileDensity*100)}%<br/><input type='range' min={1} max={50} value={Math.round(profileDensity*100)} onChange={e=>setProfileDensity(parseInt(e.target.value,10)/100)} /></label>
      <div style={{display:'flex',gap:8,justifyContent:'flex-end'}}>
        <button onClick={()=>setShowProfile(false)}>Cancel</button>
        <button onClick={saveProfile}>Save</button>
      </div>
    </div>}
  </div>;
};

createRoot(document.getElementById('root')!).render(<App />);
