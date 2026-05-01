import { useEffect, useState, useRef } from 'react';
import { useParams, useNavigate, useLocation } from 'react-router-dom';
import { ArrowLeft, Save, Plus, Trash2, Pencil, ToggleLeft, ToggleRight, Info, FileText, Layers, Eye, CheckCircle, Loader2, Circle, GitMerge, ShieldCheck, Network, FolderOpen, Archive, RotateCcw, MessageSquare, Clock } from 'lucide-react';
import { api, type DocumentDetail as DocDetail, type DocField, type WorkflowState, type EntityFieldItem, type PipelineEventItem, type CanonicalFieldItem, type EntityItem, type BucketSummary, type DocumentBucketItem, type RelatedDocument, type DocumentCommentItem, type AuditLogEntry, type DocumentVersionItem } from '../api';
import Badge from '../components/Badge';
import Modal from '../components/Modal';
import CommentThread from '../components/CommentThread';
import AuditTimeline from '../components/AuditTimeline';

function usePdfBlobUrl(docId: string | undefined) {
  const [blobUrl, setBlobUrl] = useState<string | null>(null);
  useEffect(() => {
    if (!docId) return;
    let url: string | null = null;
    const token = localStorage.getItem('dmsai_token');
    fetch(`/api/documents/${docId}/pdf`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    })
      .then(r => { if (!r.ok) throw new Error(r.statusText); return r.blob(); })
      .then(blob => { url = URL.createObjectURL(blob); setBlobUrl(url); })
      .catch(() => setBlobUrl(null));
    return () => { if (url) URL.revokeObjectURL(url); };
  }, [docId]);
  return blobUrl;
}

function ConfBar({ label, value, method }: { label: string; value: number | undefined | null; method?: string }) {
  const pct = value != null ? value * 100 : 0;
  const color = pct >= 70 ? 'bg-green-500' : pct >= 50 ? 'bg-yellow-500' : 'bg-red-500';
  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between text-xs">
        <span className="text-gray-400">{label}</span>
        <span className="text-gray-300 font-medium">
          {value != null ? `${pct.toFixed(0)}%` : 'N/A'}
          {method && <span className="text-gray-600 ml-1">({method})</span>}
        </span>
      </div>
      <div className="w-full bg-gray-800 rounded-full h-2">
        <div className={`h-2 rounded-full ${color} transition-all`} style={{ width: `${Math.max(pct, 2)}%` }} />
      </div>
    </div>
  );
}

type Tab = 'confidence' | 'original' | 'extraction' | 'ocr' | 'info' | 'relations' | 'notes' | 'history';

type ConfidenceDetails = {
  score?: number | null;
  level?: string | null;
  method?: string | null;
  signals?: Record<string, number | null | undefined>;
  weights?: Record<string, number | null | undefined>;
  reasons?: string[];
  items?: Array<{
    field_name?: string;
    entity_id?: string;
    name?: string;
    score?: number | null;
    match_confidence?: number | null;
    details?: ConfidenceDetails | null;
  }>;
};

type StageConfidence = ConfidenceDetails & {
  count?: number | null;
  matched?: number | null;
  new?: number | null;
};

function pct(value: number | null | undefined, digits = 0) {
  return value != null ? `${(value * 100).toFixed(digits)}%` : 'N/A';
}

function confidenceTone(value: number | null | undefined) {
  if (value == null) return 'text-gray-500';
  if (value >= 0.85) return 'text-green-400';
  if (value >= 0.6) return 'text-yellow-400';
  return 'text-red-400';
}

function confidenceBadgeTone(value: number | null | undefined) {
  if (value == null) return 'bg-gray-800 text-gray-500 border-gray-700';
  if (value >= 0.85) return 'bg-green-500/10 text-green-300 border-green-500/20';
  if (value >= 0.6) return 'bg-yellow-500/10 text-yellow-300 border-yellow-500/20';
  return 'bg-red-500/10 text-red-300 border-red-500/20';
}

function reasonLabel(reason: string) {
  return reason
    .replace('value_or_evidence_found_in_ocr', 'Evidence found in OCR text')
    .replace('value_or_evidence_partially_matches_ocr', 'Evidence partially matches OCR text')
    .replace('no_direct_ocr_evidence_found', 'No direct OCR evidence found')
    .replace('required_parts_missing', 'Some expected parts are missing')
    .replace('low_source_quality', 'Source quality is low')
    .replace('weak_agreement_signal', 'Agreement signal is weak')
    .replace('ambiguous_output', 'Output is ambiguous')
    .replace(/_/g, ' ');
}

function SignalList({ details }: { details?: ConfidenceDetails | null }) {
  const signals = details?.signals;
  if (!signals || Object.keys(signals).length === 0) {
    return <div className="text-xs text-gray-600">No signal details available.</div>;
  }
  return (
    <div className="grid grid-cols-2 md:grid-cols-3 gap-2">
      {Object.entries(signals).map(([name, value]) => (
        <div key={name} className="rounded-lg bg-gray-950/50 border border-gray-800 px-3 py-2">
          <div className="text-[10px] uppercase tracking-wider text-gray-600">{name.replace(/_/g, ' ')}</div>
          <div className={`text-sm font-semibold ${confidenceTone(value ?? null)}`}>{pct(value ?? null)}</div>
        </div>
      ))}
    </div>
  );
}

function ReasonList({ reasons }: { reasons?: string[] }) {
  if (!reasons?.length) return null;
  return (
    <div className="flex flex-wrap gap-1.5">
      {reasons.map((reason) => (
        <span key={reason} className="rounded-full bg-gray-800/80 border border-gray-700 px-2 py-1 text-xs text-gray-400">
          {reasonLabel(reason)}
        </span>
      ))}
    </div>
  );
}

function StageConfidenceCard({ title, detail, method }: { title: string; detail?: StageConfidence | null; method?: string | null }) {
  const score = detail?.score ?? null;
  return (
    <div className="bg-gray-900 border border-gray-800 rounded-xl p-4 space-y-3">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-white">{title}</h3>
          {(method || detail?.method) && <p className="text-xs text-gray-600 mt-0.5">{method || detail?.method}</p>}
        </div>
        <div className={`rounded-full border px-2.5 py-1 text-xs font-semibold ${confidenceBadgeTone(score)}`}>
          {pct(score)}
        </div>
      </div>
      <ConfBar label="Stage score" value={score} />
      <SignalList details={detail} />
      <ReasonList reasons={detail?.reasons} />
      {(detail?.count != null || detail?.matched != null || detail?.new != null) && (
        <div className="flex gap-3 text-xs text-gray-500">
          {detail.count != null && <span>{detail.count} item{detail.count === 1 ? '' : 's'}</span>}
          {detail.matched != null && <span>{detail.matched} matched</span>}
          {detail.new != null && <span>{detail.new} new</span>}
        </div>
      )}
    </div>
  );
}

const PIPELINE_STAGES: { id: string; short: string }[] = [
  { id: 'ingestion', short: 'Ingest' },
  { id: 'conversion', short: 'Convert' },
  { id: 'storage', short: 'Store' },
  { id: 'ocr', short: 'OCR' },
  { id: 'entity_extraction', short: 'Entities' },
  { id: 'classification', short: 'Class' },
  { id: 'entity_resolution', short: 'Resolve' },
  { id: 'field_extraction', short: 'Fields' },
];

function stageStatuses(events: PipelineEventItem[]): Record<string, 'pending' | 'started' | 'completed'> {
  const byStage: Record<string, PipelineEventItem[]> = {};
  for (const ev of events) {
    if (!byStage[ev.stage]) byStage[ev.stage] = [];
    byStage[ev.stage].push(ev);
  }
  const out: Record<string, 'pending' | 'started' | 'completed'> = {};
  for (const { id } of PIPELINE_STAGES) {
    const list = byStage[id];
    if (!list?.length) {
      out[id] = 'pending';
      continue;
    }
    const last = list.reduce((a, b) => (new Date(a.timestamp) > new Date(b.timestamp) ? a : b));
    if (last.event_type === 'completed') out[id] = 'completed';
    else out[id] = 'started';
  }
  return out;
}

interface EntityWithFields {
  link_id: string;
  entity_id: string;
  name: string;
  canonical_name: string | null;
  entity_type: string;
  role: string;
  confidence: number;
  confidence_details?: Record<string, unknown> | null;
  fields: { id: string; field_name: string; field_value: string; confidence: number; confidence_details?: Record<string, unknown> | null }[];
}

export default function DocumentDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const location = useLocation();
  const [doc, setDoc] = useState<DocDetail | null>(null);
  const [fields, setFields] = useState<DocField[]>([]);
  const [entityDetails, setEntityDetails] = useState<EntityWithFields[]>([]);
  const [wfState, setWfState] = useState<WorkflowState | null>(null);
  const [tab, setTab] = useState<Tab>('confidence');
  const [loading, setLoading] = useState(true);
  const [editField, setEditField] = useState<DocField | null>(null);
  const [editName, setEditName] = useState('');
  const [editValue, setEditValue] = useState('');
  const [showAdd, setShowAdd] = useState(false);
  const [newName, setNewName] = useState('');
  const [newValue, setNewValue] = useState('');
  const [editLabel, setEditLabel] = useState(false);
  const [labelValue, setLabelValue] = useState('');
  const [subcategoryValue, setSubcategoryValue] = useState('');
  const autoLocked = useRef(false);
  const pdfBlobUrl = usePdfBlobUrl(doc?.id);

  // Entity field editing
  const [editEntityField, setEditEntityField] = useState<{ entityId: string; field: EntityFieldItem } | null>(null);
  const [editEntityFieldName, setEditEntityFieldName] = useState('');
  const [editEntityFieldValue, setEditEntityFieldValue] = useState('');
  const [showAddEntityField, setShowAddEntityField] = useState<string | null>(null);
  const [newEntityFieldName, setNewEntityFieldName] = useState('');
  const [newEntityFieldValue, setNewEntityFieldValue] = useState('');
  const [pipelineEvents, setPipelineEvents] = useState<PipelineEventItem[]>([]);
  const [canonicalDocumentFields, setCanonicalDocumentFields] = useState<CanonicalFieldItem[]>([]);
  const [canonicalEntityFields, setCanonicalEntityFields] = useState<CanonicalFieldItem[]>([]);
  const [resolveEntity, setResolveEntity] = useState<EntityWithFields | null>(null);
  const [entitySearch, setEntitySearch] = useState('');
  const [entityCandidates, setEntityCandidates] = useState<EntityItem[]>([]);
  const [entityTargetId, setEntityTargetId] = useState<string | null>(null);

  // Bucket management
  const [docBuckets, setDocBuckets] = useState<DocumentBucketItem[]>([]);
  const [allBuckets, setAllBuckets] = useState<BucketSummary[]>([]);
  const [addBucketId, setAddBucketId] = useState('');
  const [bucketSaving, setBucketSaving] = useState(false);

  // Relations
  const [relatedDocs, setRelatedDocs] = useState<RelatedDocument[] | null>(null);
  const [relatedLoading, setRelatedLoading] = useState(false);

  // Notes / Comments
  const [comments, setComments] = useState<DocumentCommentItem[]>([]);
  const [commentsLoading, setCommentsLoading] = useState(false);

  // History / Audit
  const [auditEntries, setAuditEntries] = useState<AuditLogEntry[]>([]);
  const [versions, setVersions] = useState<DocumentVersionItem[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);

  const load = async () => {
    if (!id) return;
    try {
      const [d, f, rawEntities, ws, pe, dBuckets, aBuckets] = await Promise.all([
        api.getDocument(id),
        api.getDocumentFields(id),
        api.getDocumentEntities(id),
        api.getWorkflowState(id),
        api.getDocumentEvents(id).then((r) => r.events).catch(() => [] as PipelineEventItem[]),
        api.getDocumentBuckets(id).catch(() => [] as DocumentBucketItem[]),
        api.getBuckets().catch(() => [] as BucketSummary[]),
      ]);
      setDocBuckets(dBuckets);
      setAllBuckets(aBuckets);
      setDoc(d);
      setPipelineEvents(pe);
      setFields(f);
      setWfState(ws);

      const details: EntityWithFields[] = [];
      for (const ent of rawEntities) {
        try {
          const detail = await api.getEntityDetail(ent.entity_id);
          details.push({
            ...ent,
            fields: Array.isArray(detail.fields) ? detail.fields : Object.entries(detail.fields as Record<string, string>).map(([k, v], i) => ({
              id: `${ent.entity_id}-${i}`,
              field_name: k,
              field_value: v,
              confidence: 1.0,
            })),
          });
        } catch {
          details.push({
            ...ent,
            fields: Object.entries(ent.fields).map(([k, v], i) => ({
              id: `${ent.entity_id}-${i}`,
              field_name: k,
              field_value: v,
              confidence: 1.0,
            })),
          });
        }
      }
      setEntityDetails(details);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, [id]);

  useEffect(() => {
    Promise.all([
      api.getCanonicalFields('document').catch(() => [] as CanonicalFieldItem[]),
      api.getCanonicalFields('entity').catch(() => [] as CanonicalFieldItem[]),
    ]).then(([docFields, entityFields]) => {
      setCanonicalDocumentFields(docFields);
      setCanonicalEntityFields(entityFields);
    });
  }, []);

  useEffect(() => {
    if (!id || doc?.status === 'COMPLETED') return;
    const token = localStorage.getItem('dmsai_token');
    const ac = new AbortController();
    let buf = '';

    (async () => {
      try {
        const res = await fetch(`/api/documents/${id}/events/stream`, {
          headers: token ? { Authorization: `Bearer ${token}` } : {},
          signal: ac.signal,
        });
        if (!res.ok || !res.body) return;
        const reader = res.body.getReader();
        const dec = new TextDecoder();
        for (;;) {
          const { done, value } = await reader.read();
          if (done) break;
          buf += dec.decode(value, { stream: true });
          const parts = buf.split('\n\n');
          buf = parts.pop() || '';
          for (const block of parts) {
            const line = block.split('\n').find((l) => l.startsWith('data: '));
            if (!line) continue;
            try {
              const data = JSON.parse(line.slice(6)) as PipelineEventItem | { done?: boolean };
              if ('done' in data && data.done) return;
              if ('stage' in data && 'id' in data) {
                setPipelineEvents((prev) => {
                  if (prev.some((e) => e.id === (data as PipelineEventItem).id)) return prev;
                  return [...prev, data as PipelineEventItem];
                });
              }
            } catch {
              /* ignore parse */
            }
          }
        }
      } catch {
        /* aborted or network */
      }
    })();

    return () => ac.abort();
  }, [id, doc?.status]);

  useEffect(() => {
    if (!id || doc?.status === 'COMPLETED') return;
    const done = pipelineEvents.some((e) => e.stage === 'field_extraction' && e.event_type === 'completed');
    if (done) api.getDocument(id).then(setDoc).catch(() => {});
  }, [pipelineEvents, id, doc?.status]);

  useEffect(() => {
    if (!id || autoLocked.current || !wfState) return;
    if (wfState.workflow_state && wfState.workflow_state !== 'locked' && wfState.workflow_state !== 'closed') {
      autoLocked.current = true;
      api.autoLockDocument(id).then(() => api.getWorkflowState(id)).then(setWfState).catch(console.error);
    } else {
      autoLocked.current = true;
    }
  }, [id, wfState]);

  useEffect(() => {
    const docId = id;
    return () => {
      if (docId && autoLocked.current) {
        api.autoUnlockDocument(docId).catch(() => {});
      }
    };
  }, [id]);

  const goBack = () => {
    const from = (location.state as { from?: string })?.from;
    if (from) {
      navigate(from);
    } else {
      navigate(-1);
    }
  };

  const toggleState = async () => {
    if (!id) return;
    await api.toggleDocumentState(id);
    const ws = await api.getWorkflowState(id);
    setWfState(ws);
  };

  const saveField = async () => {
    if (!id || !editField) return;
    await api.updateField(id, editField.id, {
      field_name: editName.trim() || editField.field_name,
      field_value: editValue,
    });
    setEditField(null);
    load();
  };

  const addField = async () => {
    if (!id || !newName.trim()) return;
    await api.createField(id, newName, newValue || undefined);
    setShowAdd(false);
    setNewName('');
    setNewValue('');
    load();
  };

  const deleteField = async (fieldId: string) => {
    if (!id || !confirm('Delete this field?')) return;
    await api.deleteField(id, fieldId);
    load();
  };

  const saveLabel = async () => {
    if (!id) return;
    await api.updateDocument(id, {
      classification_label: labelValue,
      classification_subcategory_label: subcategoryValue,
    });
    setEditLabel(false);
    load();
  };

  const saveEntityField = async () => {
    if (!editEntityField) return;
    await api.updateEntityField(editEntityField.entityId, editEntityField.field.id, {
      field_name: editEntityFieldName.trim() || editEntityField.field.field_name,
      field_value: editEntityFieldValue,
    });
    setEditEntityField(null);
    load();
  };

  const addEntityField = async () => {
    if (!showAddEntityField || !newEntityFieldName.trim()) return;
    await api.createEntityField(showAddEntityField, newEntityFieldName, newEntityFieldValue);
    setShowAddEntityField(null);
    setNewEntityFieldName('');
    setNewEntityFieldValue('');
    load();
  };

  const deleteEntityField = async (entityId: string, fieldId: string) => {
    if (!confirm('Delete this entity field?')) return;
    await api.deleteEntityField(entityId, fieldId);
    load();
  };

  const searchEntityTargets = async (q: string) => {
    setEntitySearch(q);
    setEntityTargetId(null);
    if (!q.trim()) {
      setEntityCandidates([]);
      return;
    }
    const res = await api.getEntities({ search: q.trim(), page_size: '20' });
    setEntityCandidates(res.items.filter((entity) => entity.id !== resolveEntity?.entity_id));
  };

  const resolveDocumentEntity = async () => {
    if (!id || !resolveEntity || !entityTargetId) return;
    await api.resolveDocumentEntity(id, resolveEntity.link_id, entityTargetId);
    setResolveEntity(null);
    setEntitySearch('');
    setEntityCandidates([]);
    setEntityTargetId(null);
    load();
  };

  const addToBucket = async () => {
    if (!id || !addBucketId) return;
    setBucketSaving(true);
    try {
      await api.addDocumentToBucket(id, addBucketId);
      setAddBucketId('');
      const updated = await api.getDocumentBuckets(id);
      setDocBuckets(updated);
    } catch (e) {
      console.error(e);
    } finally {
      setBucketSaving(false);
    }
  };

  const removeFromBucket = async (bucketDocumentId: string) => {
    if (!id || !confirm('Remove document from this bucket?')) return;
    await api.removeDocumentFromBucket(id, bucketDocumentId);
    const updated = await api.getDocumentBuckets(id);
    setDocBuckets(updated);
  };

  const loadRelated = async () => {
    if (!id || relatedDocs !== null) return;
    setRelatedLoading(true);
    try {
      const res = await api.getRelatedDocuments(id);
      setRelatedDocs(res.related);
    } catch (e) {
      console.error(e);
      setRelatedDocs([]);
    } finally {
      setRelatedLoading(false);
    }
  };

  const loadComments = async () => {
    if (!id) return;
    setCommentsLoading(true);
    try {
      const data = await api.getDocumentComments(id);
      setComments(data);
    } catch { setComments([]); }
    finally { setCommentsLoading(false); }
  };

  const loadHistory = async () => {
    if (!id) return;
    setHistoryLoading(true);
    try {
      const [log, vers] = await Promise.all([
        api.getDocumentAuditLog(id),
        api.getDocumentVersions(id),
      ]);
      setAuditEntries(log);
      setVersions(vers);
    } catch { setAuditEntries([]); setVersions([]); }
    finally { setHistoryLoading(false); }
  };

  const handleArchive = async () => {
    if (!id || !doc) return;
    if (doc.archived_at) {
      await api.unarchiveDocument(id);
    } else {
      if (!confirm('Archive this document? It will be hidden from the main list.')) return;
      await api.archiveDocument(id);
    }
    load();
  };

  const handleTrash = async () => {
    if (!id || !doc) return;
    if (doc.trashed_at) {
      await api.restoreDocument(id);
    } else {
      if (!confirm('Move to trash? Admins can permanently delete trashed documents.')) return;
      await api.trashDocument(id);
    }
    load();
  };

  if (loading) return <div className="text-gray-500">Loading...</div>;
  if (!doc) return <div className="text-red-400">Document not found</div>;

  const isClosed = wfState?.workflow_state === 'closed';
  const isLocked = wfState?.workflow_state === 'locked';

  const cd = doc.confidence_details as Record<string, unknown> | null;
  const rawSteps =
    (cd?.steps as Record<string, StageConfidence> | undefined) ||
    (cd as Record<string, StageConfidence> | undefined);
  const pipelineConfidence = rawSteps?.pipeline;
  const globalConf = doc.pipeline_confidence;
  const st = stageStatuses(pipelineEvents);

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-4">
        <button onClick={goBack} className="text-gray-500 hover:text-gray-300"><ArrowLeft size={20} /></button>
        <div className="flex-1 min-w-0">
          <h1 className="text-2xl font-bold text-white truncate">{doc.filename}</h1>
          <div className="flex items-center gap-3 mt-1">
            <Badge value={doc.status} />
            <Badge value={doc.mode} />
            {wfState?.workflow_state && <Badge value={wfState.workflow_state} />}
            {isLocked && wfState?.locked_by_name && (
              <span className="text-xs text-yellow-400">Locked by {wfState.locked_by_name}</span>
            )}
            {doc.archived_at && <Badge value="archived" />}
            {doc.trashed_at && <Badge value="trashed" />}
            {doc.compressed_at && <Badge value="compressed" />}
            <span className="text-xs text-gray-500">{new Date(doc.created_at).toLocaleString()}</span>
          </div>
        </div>
        {/* Archive / Trash quick actions */}
        {!doc.trashed_at && (
          <button onClick={handleArchive}
            title={doc.archived_at ? 'Unarchive document' : 'Archive document'}
            className={`flex items-center gap-1.5 px-3 py-2 rounded-lg text-sm font-medium transition-colors ${
              doc.archived_at ? 'bg-yellow-500/10 text-yellow-400 hover:bg-yellow-500/20' : 'bg-gray-800 text-gray-400 hover:text-yellow-400'
            }`}>
            <Archive size={14} /> {doc.archived_at ? 'Unarchive' : 'Archive'}
          </button>
        )}
        <button onClick={handleTrash}
          title={doc.trashed_at ? 'Restore from trash' : 'Move to trash'}
          className={`flex items-center gap-1.5 px-3 py-2 rounded-lg text-sm font-medium transition-colors ${
            doc.trashed_at ? 'bg-red-500/10 text-red-400 hover:bg-red-500/20' : 'bg-gray-800 text-gray-400 hover:text-red-400'
          }`}>
          {doc.trashed_at ? <><RotateCcw size={14} /> Restore</> : <><Trash2 size={14} /> Trash</>}
        </button>

        {wfState?.workflow_state && (
          <button
            onClick={toggleState}
            className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
              isClosed
                ? 'bg-green-600/20 text-green-400 hover:bg-green-600/30'
                : 'bg-red-600/20 text-red-400 hover:bg-red-600/30'
            }`}
          >
            {isClosed ? <ToggleLeft size={16} /> : <ToggleRight size={16} />}
            {isClosed ? 'Reopen Document' : 'Close Document'}
          </button>
        )}
      </div>

      {/* Pipeline stages */}
      <div className="bg-gray-900 border border-gray-800 rounded-xl p-4 overflow-x-auto">
        <div className="text-xs text-gray-500 uppercase tracking-wider mb-3">Pipeline progress</div>
        <div className="flex items-center gap-1 min-w-max">
          {PIPELINE_STAGES.map(({ id: sid, short }, i) => {
            const status = st[sid] || 'pending';
            return (
              <div key={sid} className="flex items-center gap-1">
                {i > 0 && <div className="w-4 h-px bg-gray-700" />}
                <div className="flex flex-col items-center gap-1 px-2">
                  <div className="flex items-center justify-center w-8 h-8 rounded-full border border-gray-700 bg-gray-800">
                    {status === 'completed' && <CheckCircle size={16} className="text-green-400" />}
                    {status === 'started' && <Loader2 size={16} className="text-amber-400 animate-spin" />}
                    {status === 'pending' && <Circle size={16} className="text-gray-600" />}
                  </div>
                  <span className="text-[10px] text-gray-500 max-w-[52px] text-center leading-tight">{short}</span>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 border-b border-gray-800 overflow-x-auto">
        {([
          { key: 'confidence' as Tab, label: 'Confidence', icon: <ShieldCheck size={14} /> },
          { key: 'original' as Tab, label: 'Original Doc', icon: <Eye size={14} /> },
          { key: 'extraction' as Tab, label: `Extraction (${fields.length + entityDetails.length})`, icon: <Layers size={14} /> },
          { key: 'ocr' as Tab, label: 'OCR Text', icon: <FileText size={14} /> },
          { key: 'notes' as Tab, label: `Notes (${comments.length})`, icon: <MessageSquare size={14} /> },
          { key: 'history' as Tab, label: 'History', icon: <Clock size={14} /> },
          { key: 'relations' as Tab, label: 'Relations', icon: <Network size={14} /> },
          { key: 'info' as Tab, label: 'Info', icon: <Info size={14} /> },
        ]).map(t => (
          <button
            key={t.key}
            onClick={() => {
              setTab(t.key);
              if (t.key === 'relations') loadRelated();
              if (t.key === 'notes') loadComments();
              if (t.key === 'history') loadHistory();
            }}
            className={`flex items-center gap-1.5 px-4 py-2.5 text-sm font-medium border-b-2 transition-colors whitespace-nowrap ${
              tab === t.key ? 'border-blue-500 text-blue-400' : 'border-transparent text-gray-500 hover:text-gray-300'
            }`}
          >
            {t.icon} {t.label}
          </button>
        ))}
      </div>

      {tab === 'confidence' && (
        <div className="space-y-6">
          <div className="bg-gray-900 border border-gray-800 rounded-xl p-6">
            <div className="flex flex-col lg:flex-row lg:items-center gap-6">
              <div className="flex-shrink-0">
                <div className="text-xs text-gray-500 uppercase tracking-wider mb-2">Overall Confidence</div>
                <div className={`text-6xl font-bold leading-none ${confidenceTone(globalConf)}`}>
                  {pct(globalConf)}
                </div>
                <div className="mt-3 flex items-center gap-2">
                  <span className={`rounded-full border px-2.5 py-1 text-xs font-semibold ${confidenceBadgeTone(globalConf)}`}>
                    {pipelineConfidence?.level || (globalConf != null && globalConf >= 0.85 ? 'high' : globalConf != null && globalConf >= 0.6 ? 'medium' : 'low')}
                  </span>
                  <span className="text-sm text-gray-400">
                    {[doc.classification_label, doc.classification_subcategory_label].filter(Boolean).join(' / ') || 'Unclassified'}
                  </span>
                  <button onClick={() => {
                    setLabelValue(doc.classification_label || '');
                    setSubcategoryValue(doc.classification_subcategory_label || '');
                    setEditLabel(true);
                  }} className="text-gray-600 hover:text-gray-300"><Pencil size={11} /></button>
                </div>
              </div>
              <div className="flex-1 space-y-4">
                <p className="text-sm text-gray-400 max-w-3xl">
                  This score combines autonomous signals from the LLM pipeline: model confidence, OCR evidence grounding,
                  extraction completeness, ambiguity or agreement, and source quality. Higher confidence means the extracted
                  result is both supported by the document text and consistent across the processing steps.
                </p>
                {pipelineConfidence ? (
                  <SignalList details={pipelineConfidence} />
                ) : (
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                    <ConfBar label="OCR" value={doc.ocr_confidence} method={doc.ocr_method || undefined} />
                    <ConfBar label="Classification" value={doc.classification_confidence} method={doc.classification_method || undefined} />
                  </div>
                )}
              </div>
            </div>
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <StageConfidenceCard title="OCR" detail={rawSteps?.ocr || { score: doc.ocr_confidence }} method={rawSteps?.ocr?.method || doc.ocr_method} />
            <StageConfidenceCard title="Classification" detail={rawSteps?.classification || { score: doc.classification_confidence }} method={rawSteps?.classification?.method || doc.classification_method} />
            <StageConfidenceCard title="Entity Extraction" detail={rawSteps?.entity_extraction} />
            <StageConfidenceCard title="Entity Resolution" detail={rawSteps?.entity_resolution} />
            <StageConfidenceCard title="Field Extraction" detail={rawSteps?.field_extraction} />
          </div>

          <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
            <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
              <div className="px-4 py-3 border-b border-gray-800">
                <h3 className="text-sm font-semibold text-white">Field Confidence</h3>
                <p className="text-xs text-gray-600 mt-0.5">Per-field score with the main reasons from the scorer.</p>
              </div>
              <div className="divide-y divide-gray-800/70">
                {fields.map((field) => {
                  const details = field.confidence_details as ConfidenceDetails | undefined;
                  return (
                    <div key={field.id} className="p-4 space-y-2">
                      <div className="flex items-center justify-between gap-3">
                        <div className="min-w-0">
                          <div className="text-sm font-medium text-gray-200 truncate">{field.field_name}</div>
                          <div className="text-xs text-gray-600 truncate">{field.field_value || 'No value extracted'}</div>
                        </div>
                        <span className={`rounded-full border px-2.5 py-1 text-xs font-semibold ${confidenceBadgeTone(field.confidence)}`}>
                          {pct(field.confidence)}
                        </span>
                      </div>
                      <ReasonList reasons={details?.reasons} />
                    </div>
                  );
                })}
                {fields.length === 0 && <div className="p-6 text-center text-sm text-gray-600">No field confidence available.</div>}
              </div>
            </div>

            <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
              <div className="px-4 py-3 border-b border-gray-800">
                <h3 className="text-sm font-semibold text-white">Entity Confidence</h3>
                <p className="text-xs text-gray-600 mt-0.5">Document-entity link confidence and resolution quality.</p>
              </div>
              <div className="divide-y divide-gray-800/70">
                {entityDetails.map((entity) => {
                  const details = entity.confidence_details as ConfidenceDetails | undefined;
                  return (
                    <div key={entity.link_id} className="p-4 space-y-2">
                      <div className="flex items-center justify-between gap-3">
                        <div className="min-w-0">
                          <div className="flex items-center gap-2">
                            <span className="text-sm font-medium text-gray-200 truncate">{entity.name}</span>
                            <Badge value={entity.role} />
                          </div>
                          <div className="text-xs text-gray-600">{entity.entity_type}</div>
                        </div>
                        <span className={`rounded-full border px-2.5 py-1 text-xs font-semibold ${confidenceBadgeTone(entity.confidence)}`}>
                          {pct(entity.confidence)}
                        </span>
                      </div>
                      <ReasonList reasons={details?.reasons} />
                    </div>
                  );
                })}
                {entityDetails.length === 0 && <div className="p-6 text-center text-sm text-gray-600">No entity confidence available.</div>}
              </div>
            </div>
          </div>
        </div>
      )}

      {tab === 'original' && (
        <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
          {pdfBlobUrl ? (
            <iframe
              src={`${pdfBlobUrl}#toolbar=1&navpanes=0`}
              className="w-full border-0"
              style={{ height: 'calc(100vh - 380px)', minHeight: '500px' }}
              title="Original Document"
            />
          ) : doc.pdf_url ? (
            <div className="p-12 text-center text-gray-500">Loading document...</div>
          ) : (
            <div className="p-12 text-center text-gray-600">No PDF available for this document</div>
          )}
        </div>
      )}

      {tab === 'extraction' && (
        <div className="space-y-6">
          {/* Document Fields */}
          <div>
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-sm font-semibold text-white uppercase tracking-wider">Document Fields</h3>
              <button onClick={() => setShowAdd(true)} className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-gray-800 text-gray-300 text-sm hover:bg-gray-700 transition-colors">
                <Plus size={14} /> Add Field
              </button>
            </div>
            <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-gray-800 text-gray-500 text-xs uppercase tracking-wider">
                    <th className="text-left px-4 py-3">Field</th>
                    <th className="text-left px-4 py-3">Value</th>
                    <th className="text-left px-4 py-3">Confidence</th>
                    <th className="text-left px-4 py-3">Method</th>
                    <th className="text-left px-4 py-3">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {fields.map(f => (
                    <tr key={f.id} className="border-b border-gray-800/50 hover:bg-gray-800/30">
                      <td className="px-4 py-3 font-medium text-gray-300">{f.field_name}</td>
                      <td className="px-4 py-3 text-gray-400 max-w-sm truncate">{f.field_value || '---'}</td>
                      <td className="px-4 py-3 text-gray-500">{(f.confidence * 100).toFixed(0)}%</td>
                      <td className="px-4 py-3"><Badge value={f.extraction_method} /></td>
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-1">
                          <button onClick={() => { setEditField(f); setEditName(f.field_name); setEditValue(f.field_value || ''); }} className="p-1 rounded hover:bg-gray-700 text-gray-500 hover:text-white"><Pencil size={13} /></button>
                          <button onClick={() => deleteField(f.id)} className="p-1 rounded hover:bg-gray-700 text-gray-500 hover:text-red-400"><Trash2 size={13} /></button>
                        </div>
                      </td>
                    </tr>
                  ))}
                  {fields.length === 0 && (
                    <tr><td colSpan={5} className="px-4 py-8 text-center text-gray-600">No fields extracted</td></tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>

          {/* Entities */}
          <div>
            <h3 className="text-sm font-semibold text-white uppercase tracking-wider mb-3">Entities</h3>
            {entityDetails.length === 0 ? (
              <div className="bg-gray-900 border border-gray-800 rounded-xl p-8 text-center text-gray-600">No entities found</div>
            ) : entityDetails.map(e => (
              <div key={e.entity_id} className="bg-gray-900 border border-gray-800 rounded-xl p-5 mb-3">
                <div className="flex items-center gap-3 mb-3">
                  <span className="text-white font-medium">{e.name}</span>
                  <Badge value={e.entity_type} />
                  <Badge value={e.role} />
                  <span className="text-xs text-gray-500">{(e.confidence * 100).toFixed(0)}%</span>
                  <button onClick={() => { setResolveEntity(e); setEntitySearch(''); setEntityCandidates([]); setEntityTargetId(null); }} className="ml-auto flex items-center gap-1 text-xs text-amber-400 hover:text-amber-300">
                    <GitMerge size={12} /> Resolve
                  </button>
                  <button onClick={() => setShowAddEntityField(e.entity_id)} className="flex items-center gap-1 text-xs text-blue-400 hover:text-blue-300">
                    <Plus size={12} /> Add Field
                  </button>
                </div>
                <div className="bg-gray-800/30 rounded-lg overflow-hidden">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="text-gray-500 text-xs uppercase tracking-wider">
                        <th className="text-left px-3 py-2">Field</th>
                        <th className="text-left px-3 py-2">Value</th>
                        <th className="text-left px-3 py-2">Actions</th>
                      </tr>
                    </thead>
                    <tbody>
                      {e.fields.map(f => (
                        <tr key={f.id} className="border-t border-gray-800/30 hover:bg-gray-800/20">
                          <td className="px-3 py-2 text-gray-400 text-xs font-mono">{f.field_name}</td>
                          <td className="px-3 py-2 text-gray-300">{f.field_value}</td>
                          <td className="px-3 py-2">
                            <div className="flex items-center gap-1">
                              <button onClick={() => { setEditEntityField({ entityId: e.entity_id, field: f }); setEditEntityFieldName(f.field_name); setEditEntityFieldValue(f.field_value); }}
                                className="p-1 rounded hover:bg-gray-700 text-gray-500 hover:text-white"><Pencil size={12} /></button>
                              <button onClick={() => deleteEntityField(e.entity_id, f.id)}
                                className="p-1 rounded hover:bg-gray-700 text-gray-500 hover:text-red-400"><Trash2 size={12} /></button>
                            </div>
                          </td>
                        </tr>
                      ))}
                      {e.fields.length === 0 && (
                        <tr><td colSpan={3} className="px-3 py-4 text-center text-gray-600 text-xs">No fields</td></tr>
                      )}
                    </tbody>
                  </table>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {tab === 'ocr' && (
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-5">
          <pre className="text-sm text-gray-300 whitespace-pre-wrap max-h-96 overflow-y-auto font-mono">
            {doc.ocr_text || 'No OCR text available'}
          </pre>
        </div>
      )}

      {tab === 'relations' && (
        <div className="space-y-6">
          {/* Entities on this document */}
          <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
            <div className="px-4 py-3 border-b border-gray-800">
              <h3 className="text-sm font-semibold text-white">Entities in this Document</h3>
              <p className="text-xs text-gray-500 mt-0.5">Entities extracted from this document. Click an entity to open its admin profile.</p>
            </div>
            {entityDetails.length === 0 ? (
              <div className="p-8 text-center text-gray-600 text-sm">No entities found in this document.</div>
            ) : (
              <div className="divide-y divide-gray-800/60">
                {entityDetails.map(e => (
                  <div key={e.entity_id} className="flex items-center justify-between px-4 py-3 hover:bg-gray-800/30">
                    <div className="flex items-center gap-3">
                      <div className="w-8 h-8 rounded-full bg-indigo-500/10 border border-indigo-500/20 flex items-center justify-center">
                        <span className="text-xs font-bold text-indigo-400">{(e.name || '?')[0].toUpperCase()}</span>
                      </div>
                      <div>
                        <div className="text-sm font-medium text-gray-200">{e.canonical_name || e.name}</div>
                        <div className="text-xs text-gray-500">{e.entity_type} · {e.role}</div>
                      </div>
                    </div>
                    <div className="flex items-center gap-2">
                      <span className={`text-xs font-semibold ${confidenceTone(e.confidence)}`}>{pct(e.confidence)}</span>
                      <a href={`/admin/entities/${e.entity_id}`} className="text-xs text-blue-500 hover:text-blue-400 px-2 py-1 rounded hover:bg-blue-500/10 transition-colors">
                        View profile →
                      </a>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Related documents */}
          <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
            <div className="px-4 py-3 border-b border-gray-800">
              <h3 className="text-sm font-semibold text-white">Related Documents</h3>
              <p className="text-xs text-gray-500 mt-0.5">Other documents in your organization that share entities with this one, ranked by number of shared entities.</p>
            </div>
            {relatedLoading ? (
              <div className="p-8 flex items-center justify-center gap-2 text-gray-500 text-sm">
                <Loader2 size={16} className="animate-spin" /> Loading relations...
              </div>
            ) : relatedDocs === null ? (
              <div className="p-8 text-center text-gray-600 text-sm">Click Relations tab to load.</div>
            ) : relatedDocs.length === 0 ? (
              <div className="p-8 text-center text-gray-600 text-sm">No related documents found.</div>
            ) : (
              <div className="divide-y divide-gray-800/60">
                {relatedDocs.map(r => (
                  <div key={r.document_id} className="px-4 py-3 hover:bg-gray-800/30">
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <a href={`/documents/${r.document_id}`} className="text-sm font-medium text-gray-200 hover:text-blue-400 truncate block">
                          {r.filename}
                        </a>
                        <div className="flex items-center gap-2 mt-1">
                          {r.classification_label && <Badge value={r.classification_label} />}
                          <span className="text-xs text-gray-600">{new Date(r.created_at).toLocaleDateString()}</span>
                        </div>
                      </div>
                      <div className="flex-shrink-0 text-right">
                        <div className="text-sm font-semibold text-indigo-400">{r.shared_entity_count}</div>
                        <div className="text-xs text-gray-600">shared entit{r.shared_entity_count === 1 ? 'y' : 'ies'}</div>
                      </div>
                    </div>
                    <div className="flex flex-wrap gap-1.5 mt-2">
                      {r.shared_entities.map(e => (
                        <span key={e.entity_id} className="rounded-full bg-indigo-500/10 border border-indigo-500/20 px-2 py-0.5 text-xs text-indigo-300">
                          {e.name}
                        </span>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}

      {tab === 'info' && (
        <div className="space-y-6">
          {/* Bucket membership */}
          <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
            <div className="px-4 py-3 border-b border-gray-800 flex items-center justify-between">
              <div>
                <h3 className="text-sm font-semibold text-white flex items-center gap-2"><FolderOpen size={14} /> Bucket Assignments</h3>
                <p className="text-xs text-gray-500 mt-0.5">Manually manage which buckets this document belongs to.</p>
              </div>
            </div>

            {/* Current assignments */}
            {docBuckets.length === 0 ? (
              <div className="px-4 py-4 text-sm text-gray-600">Not assigned to any bucket.</div>
            ) : (
              <div className="divide-y divide-gray-800/60">
                {docBuckets.map(bd => (
                  <div key={bd.bucket_document_id} className="flex items-center justify-between px-4 py-3">
                    <div>
                      <div className="text-sm font-medium text-gray-200">{bd.bucket_name}</div>
                      <div className="flex items-center gap-2 mt-0.5">
                        <Badge value={bd.workflow_state} />
                        <span className="text-xs text-gray-600">since {new Date(bd.created_at).toLocaleDateString()}</span>
                      </div>
                    </div>
                    <button
                      onClick={() => removeFromBucket(bd.bucket_document_id)}
                      className="p-1.5 rounded hover:bg-red-500/10 text-gray-600 hover:text-red-400 transition-colors"
                      title="Remove from bucket"
                    >
                      <Trash2 size={14} />
                    </button>
                  </div>
                ))}
              </div>
            )}

            {/* Add to bucket */}
            <div className="px-4 py-3 border-t border-gray-800 flex items-center gap-2">
              <select
                value={addBucketId}
                onChange={e => setAddBucketId(e.target.value)}
                className="flex-1 px-3 py-2 rounded-lg bg-gray-800 border border-gray-700 text-white text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              >
                <option value="">Add to bucket…</option>
                {allBuckets
                  .filter(b => !docBuckets.some(db => db.bucket_id === b.id))
                  .map(b => (
                    <option key={b.id} value={b.id}>{b.name}</option>
                  ))}
              </select>
              <button
                disabled={!addBucketId || bucketSaving}
                onClick={addToBucket}
                className="flex items-center gap-1.5 px-3 py-2 rounded-lg bg-blue-600 text-white text-sm hover:bg-blue-500 disabled:opacity-40 transition-colors"
              >
                <Plus size={14} /> {bucketSaving ? 'Adding…' : 'Add'}
              </button>
            </div>
          </div>

          {/* Metadata table */}
          <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
            <table className="w-full text-sm">
              <tbody>
                {([
                  ['Filename', doc.filename],
                  ['Extension', doc.original_extension],
                  ['Source', doc.source],
                  ['Mode', doc.mode],
                  ['Status', doc.status],
                  ['PDF', doc.pdf_url ? 'Available' : 'N/A'],
                  ['File Size', doc.file_size_bytes != null ? `${(doc.file_size_bytes / 1024).toFixed(1)} KB` : 'N/A'],
                  ['Page Count', doc.page_count != null ? String(doc.page_count) : 'N/A'],
                  ['Cluster ID', doc.cluster_id != null ? String(doc.cluster_id) : 'N/A'],
                  ['Classification', doc.classification_label || 'N/A'],
                  ['Subcategory', doc.classification_subcategory_label || 'N/A'],
                  ['Classification Path', doc.classification_path?.join(' / ') || 'N/A'],
                  ['Classification Method', doc.classification_method || 'N/A'],
                  ['Classification Confidence', doc.classification_confidence != null ? `${(doc.classification_confidence * 100).toFixed(1)}%` : 'N/A'],
                  ['OCR Method', doc.ocr_method || 'N/A'],
                  ['OCR Confidence', doc.ocr_confidence != null ? `${(doc.ocr_confidence * 100).toFixed(1)}%` : 'N/A'],
                  ['Pipeline Confidence', globalConf != null ? `${(globalConf * 100).toFixed(1)}%` : 'N/A'],
                  ['Created', new Date(doc.created_at).toLocaleString()],
                  ['Updated', doc.updated_at ? new Date(doc.updated_at).toLocaleString() : 'N/A'],
                  ['Processed', doc.processed_at ? new Date(doc.processed_at).toLocaleString() : 'N/A'],
                ] as [string, string][]).map(([label, val]) => (
                  <tr key={label} className="border-b border-gray-800/50">
                    <td className="px-4 py-2.5 text-gray-500 font-medium w-56">{label}</td>
                    <td className="px-4 py-2.5 text-gray-300">{val}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {tab === 'notes' && (
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-6">
          <CommentThread
            comments={comments}
            loading={commentsLoading}
            onAdd={async (content, parentId) => {
              if (id) { await api.createDocumentComment(id, content, parentId); await loadComments(); }
            }}
            onEdit={async (commentId, content) => {
              if (id) { await api.updateDocumentComment(id, commentId, content); await loadComments(); }
            }}
            onDelete={async (commentId) => {
              if (id && confirm('Delete this note?')) { await api.deleteDocumentComment(id, commentId); await loadComments(); }
            }}
          />
        </div>
      )}

      {tab === 'history' && (
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-6">
          <AuditTimeline
            entries={auditEntries}
            versions={versions}
            loading={historyLoading}
            onLoadVersion={async (versionId) => {
              if (!id) throw new Error();
              return api.getDocumentVersion(id, versionId);
            }}
          />
        </div>
      )}

      {/* Modals */}
      <Modal open={!!editField} onClose={() => setEditField(null)} title={`Edit: ${editField?.field_name}`}>
        <div className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-400 mb-1.5">Resolved Field Name</label>
            <input list="document-field-names" value={editName} onChange={e => setEditName(e.target.value)} className="w-full px-3.5 py-2.5 rounded-lg bg-gray-800 border border-gray-700 text-white text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
            <datalist id="document-field-names">
              {canonicalDocumentFields.map((f) => <option key={f.id} value={f.canonical_name} />)}
            </datalist>
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-400 mb-1.5">Value</label>
          <input value={editValue} onChange={e => setEditValue(e.target.value)} className="w-full px-3.5 py-2.5 rounded-lg bg-gray-800 border border-gray-700 text-white text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
          </div>
          <button onClick={saveField} className="w-full flex items-center justify-center gap-2 py-2.5 rounded-lg bg-blue-600 text-white text-sm font-medium hover:bg-blue-500 transition-colors">
            <Save size={14} /> Save
          </button>
        </div>
      </Modal>

      <Modal open={showAdd} onClose={() => setShowAdd(false)} title="Add Field">
        <div className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-400 mb-1.5">Field Name</label>
            <input list="document-field-names" value={newName} onChange={e => setNewName(e.target.value)} className="w-full px-3.5 py-2.5 rounded-lg bg-gray-800 border border-gray-700 text-white text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-400 mb-1.5">Value</label>
            <input value={newValue} onChange={e => setNewValue(e.target.value)} className="w-full px-3.5 py-2.5 rounded-lg bg-gray-800 border border-gray-700 text-white text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
          </div>
          <button onClick={addField} className="w-full py-2.5 rounded-lg bg-blue-600 text-white text-sm font-medium hover:bg-blue-500 transition-colors">Add Field</button>
        </div>
      </Modal>

      <Modal open={editLabel} onClose={() => setEditLabel(false)} title="Edit Classification">
        <div className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-400 mb-1.5">Category</label>
            <input value={labelValue} onChange={e => setLabelValue(e.target.value)} className="w-full px-3.5 py-2.5 rounded-lg bg-gray-800 border border-gray-700 text-white text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-400 mb-1.5">Subcategory</label>
            <input value={subcategoryValue} onChange={e => setSubcategoryValue(e.target.value)} className="w-full px-3.5 py-2.5 rounded-lg bg-gray-800 border border-gray-700 text-white text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
          </div>
          <button onClick={saveLabel} className="w-full py-2.5 rounded-lg bg-blue-600 text-white text-sm font-medium hover:bg-blue-500 transition-colors">Save</button>
        </div>
      </Modal>

      <Modal open={!!editEntityField} onClose={() => setEditEntityField(null)} title={`Edit: ${editEntityField?.field.field_name}`}>
        <div className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-400 mb-1.5">Resolved Field Name</label>
            <input list="entity-field-names" value={editEntityFieldName} onChange={e => setEditEntityFieldName(e.target.value)} className="w-full px-3.5 py-2.5 rounded-lg bg-gray-800 border border-gray-700 text-white text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
            <datalist id="entity-field-names">
              {canonicalEntityFields.map((f) => <option key={f.id} value={f.canonical_name} />)}
            </datalist>
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-400 mb-1.5">Value</label>
          <input value={editEntityFieldValue} onChange={e => setEditEntityFieldValue(e.target.value)} className="w-full px-3.5 py-2.5 rounded-lg bg-gray-800 border border-gray-700 text-white text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
          </div>
          <button onClick={saveEntityField} className="w-full flex items-center justify-center gap-2 py-2.5 rounded-lg bg-blue-600 text-white text-sm font-medium hover:bg-blue-500 transition-colors">
            <Save size={14} /> Save
          </button>
        </div>
      </Modal>

      <Modal open={!!showAddEntityField} onClose={() => setShowAddEntityField(null)} title="Add Entity Field">
        <div className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-400 mb-1.5">Field Name</label>
            <input list="entity-field-names" value={newEntityFieldName} onChange={e => setNewEntityFieldName(e.target.value)} className="w-full px-3.5 py-2.5 rounded-lg bg-gray-800 border border-gray-700 text-white text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-400 mb-1.5">Value</label>
            <input value={newEntityFieldValue} onChange={e => setNewEntityFieldValue(e.target.value)} className="w-full px-3.5 py-2.5 rounded-lg bg-gray-800 border border-gray-700 text-white text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
          </div>
          <button onClick={addEntityField} className="w-full py-2.5 rounded-lg bg-blue-600 text-white text-sm font-medium hover:bg-blue-500 transition-colors">Add Field</button>
        </div>
      </Modal>

      <Modal open={!!resolveEntity} onClose={() => setResolveEntity(null)} title={`Resolve entity: ${resolveEntity?.name}`}>
        <div className="space-y-4">
          <p className="text-sm text-gray-400">
            Reassign this document link to an existing entity. This records a correction and keeps the entity base intact.
          </p>
          <input
            value={entitySearch}
            onChange={e => searchEntityTargets(e.target.value)}
            placeholder="Search existing entity..."
            className="w-full px-3.5 py-2.5 rounded-lg bg-gray-800 border border-gray-700 text-white text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
          <div className="space-y-1 max-h-48 overflow-y-auto">
            {entityCandidates.map((candidate) => (
              <button
                key={candidate.id}
                type="button"
                onClick={() => setEntityTargetId(candidate.id)}
                className={`w-full text-left px-3 py-2 rounded-lg text-sm ${entityTargetId === candidate.id ? 'bg-blue-600/30 text-blue-300' : 'bg-gray-800 text-gray-300 hover:bg-gray-700'}`}
              >
                <span className="font-medium">{candidate.canonical_name || candidate.name}</span>
                <span className="ml-2 text-xs text-gray-500">{candidate.entity_type}</span>
              </button>
            ))}
          </div>
          <button disabled={!entityTargetId} onClick={resolveDocumentEntity} className="w-full flex items-center justify-center gap-2 py-2.5 rounded-lg bg-amber-600 text-white text-sm font-medium hover:bg-amber-500 transition-colors disabled:opacity-50">
            <GitMerge size={14} /> Reassign Document Entity
          </button>
        </div>
      </Modal>
    </div>
  );
}
