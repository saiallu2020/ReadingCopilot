import axios from 'axios';

export const API_BASE = (import.meta as any).env?.VITE_API_BASE || 'http://localhost:8000';

export interface Rect { x1:number; y1:number; x2:number; y2:number; }
export interface Highlight { id:string; page_index:number; rects:Rect[]; note?:string; auto_generated?:boolean; profile_score?:number; }
export interface AnnotationDocument { id:string; filename:string; pdf_path:string; highlights:Highlight[]; global_profile?:string; document_goal?:string; highlight_density_target:number; }
export interface UploadResponse { document_id:string; filename:string; }
export interface AutoHLStatus { run_id:string; state:string; emitted:number; }

export async function listDocuments(){ const r = await axios.get<AnnotationDocument[]>(`${API_BASE}/api/docs/`); return r.data; }
export async function uploadPDF(file:File){ const fd=new FormData(); fd.append('file', file); const r= await axios.post<UploadResponse>(`${API_BASE}/api/docs/`, fd); return r.data; }
export async function getDocument(id:string){ const r= await axios.get<AnnotationDocument>(`${API_BASE}/api/docs/${id}`); return r.data; }
export async function updateProfile(id:string, global_profile:string, document_goal:string, density:number){ const r= await axios.put<AnnotationDocument>(`${API_BASE}/api/docs/${id}/profile`, {global_profile, document_goal, highlight_density_target:density}); return r.data; }
export async function addHighlight(id:string, page_index:number, rects:Rect[], note?:string){ const r= await axios.post<AnnotationDocument>(`${API_BASE}/api/docs/${id}/highlights`, {page_index, rects, note}); return r.data; }
export async function clearHighlights(id:string){ await axios.delete(`${API_BASE}/api/docs/${id}/highlights`); }
export async function startAuto(id:string, density?:number, min_threshold?:number){ const r= await axios.post<AutoHLStatus>(`${API_BASE}/api/docs/${id}/auto`, {density, min_threshold}); return r.data; }
export async function cancelAuto(id:string, run_id:string){ const r = await axios.delete<AutoHLStatus>(`${API_BASE}/api/docs/${id}/auto/${run_id}`); return r.data; }
export async function pollAuto(id:string, run_id:string){ const r= await axios.get<AutoHLStatus>(`${API_BASE}/api/docs/${id}/auto/${run_id}`); return r.data; }
export async function fetchAutoDoc(id:string, run_id:string){ const r= await axios.get<AnnotationDocument>(`${API_BASE}/api/docs/${id}/auto/${run_id}/highlights`); return r.data; }
