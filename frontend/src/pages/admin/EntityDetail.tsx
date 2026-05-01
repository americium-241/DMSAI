import { useEffect, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { ArrowLeft, Pencil, Plus, Trash2, GitMerge, MessageSquare } from 'lucide-react';
import { api, type EntityDossierResponse, type EntityRelationshipItem, type EntityFieldItem, type EntityCommentItem } from '../../api';
import Badge from '../../components/Badge';
import Modal from '../../components/Modal';
import { useToast } from '../../components/Toast';
import CommentThread from '../../components/CommentThread';

export default function EntityDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { show } = useToast();
  const [data, setData] = useState<EntityDossierResponse | null>(null);
  const [rels, setRels] = useState<EntityRelationshipItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [mergeOpen, setMergeOpen] = useState(false);
  const [mergeSearch, setMergeSearch] = useState('');
  const [mergeCandidates, setMergeCandidates] = useState<{ id: string; name: string }[]>([]);
  const [mergeTarget, setMergeTarget] = useState<string | null>(null);

  const [editField, setEditField] = useState<EntityFieldItem | null>(null);
  const [editVal, setEditVal] = useState('');
  const [showAddField, setShowAddField] = useState(false);
  const [newFieldName, setNewFieldName] = useState('');
  const [newFieldValue, setNewFieldValue] = useState('');
  const [comments, setComments] = useState<EntityCommentItem[]>([]);
  const [commentsLoading, setCommentsLoading] = useState(false);
  const [showNotes, setShowNotes] = useState(false);

  const load = async () => {
    if (!id) return;
    setLoading(true);
    try {
      const [d, r] = await Promise.all([
        api.getEntityDossier(id),
        api.getEntityRelationships(id),
      ]);
      setData(d);
      setRels(r.items);
    } catch (e) {
      console.error(e);
      setData(null);
    } finally {
      setLoading(false);
    }
  };

  const loadComments = async () => {
    if (!id) return;
    setCommentsLoading(true);
    try { setComments(await api.getEntityComments(id)); }
    catch { setComments([]); }
    finally { setCommentsLoading(false); }
  };

  useEffect(() => {
    load();
  }, [id]);

  const searchMergeTargets = async (q: string) => {
    setMergeSearch(q);
    if (!q.trim() || !id) {
      setMergeCandidates([]);
      return;
    }
    try {
      const res = await api.getEntities({ search: q.trim(), page_size: '20' });
      setMergeCandidates(res.items.filter((e) => e.id !== id).map((e) => ({ id: e.id, name: e.name })));
    } catch {
      setMergeCandidates([]);
    }
  };

  const doMerge = async () => {
    if (!id || !mergeTarget) return;
    try {
      await api.mergeEntities(id, mergeTarget);
      show('Entities merged', 'success');
      navigate(`/admin/entities/${mergeTarget}`);
    } catch (e) {
      show(String(e), 'error');
    }
    setMergeOpen(false);
  };

  const saveField = async () => {
    if (!id || !editField) return;
    try {
      await api.updateEntityField(id, editField.id, { field_value: editVal });
      setEditField(null);
      load();
      show('Field updated', 'success');
    } catch (e) {
      show(String(e), 'error');
    }
  };

  const addField = async () => {
    if (!id || !newFieldName.trim()) return;
    try {
      await api.createEntityField(id, newFieldName.trim(), newFieldValue);
      setShowAddField(false);
      setNewFieldName('');
      setNewFieldValue('');
      load();
      show('Field added', 'success');
    } catch (e) {
      show(String(e), 'error');
    }
  };

  const deleteField = async (fid: string) => {
    if (!id || !confirm('Delete this field?')) return;
    try {
      await api.deleteEntityField(id, fid);
      load();
      show('Field deleted', 'success');
    } catch (e) {
      show(String(e), 'error');
    }
  };

  if (loading && !data) return <div className="text-gray-500">Loading...</div>;
  if (!data) return <div className="text-red-400">Entity not found</div>;

  const e = data.entity;

  return (
    <div className="space-y-6">
      <div className="flex items-start gap-4">
        <button type="button" onClick={() => navigate(-1)} className="text-gray-500 hover:text-gray-300 mt-1">
          <ArrowLeft size={20} />
        </button>
        <div className="flex-1 min-w-0">
          <h1 className="text-2xl font-bold text-white truncate">{e.name}</h1>
          <div className="flex flex-wrap items-center gap-2 mt-2">
            <Badge value={e.entity_type} />
            {e.canonical_name && <span className="text-sm text-gray-500">Canonical: {e.canonical_name}</span>}
            <span className="text-xs text-gray-600">{new Date(e.created_at).toLocaleString()}</span>
          </div>
        </div>
        <button
          type="button"
          onClick={() => setMergeOpen(true)}
          className="flex items-center gap-2 px-4 py-2 rounded-lg bg-amber-600/20 text-amber-400 text-sm hover:bg-amber-600/30"
        >
          <GitMerge size={16} /> Merge into…
        </button>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-5">
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-lg font-semibold text-white">Entity fields</h2>
            <button type="button" onClick={() => setShowAddField(true)} className="flex items-center gap-1 text-sm text-blue-400 hover:text-blue-300">
              <Plus size={14} /> Add
            </button>
          </div>
          <table className="w-full text-sm">
            <thead>
              <tr className="text-gray-500 text-xs border-b border-gray-800">
                <th className="text-left py-2">Field</th>
                <th className="text-left py-2">Value</th>
                <th className="text-right py-2 w-20">Actions</th>
              </tr>
            </thead>
            <tbody>
              {data.fields.map((f) => (
                <tr key={f.id} className="border-b border-gray-800/50">
                  <td className="py-2 font-mono text-xs text-gray-400">{f.field_name}</td>
                  <td className="py-2 text-gray-300">{f.field_value}</td>
                  <td className="py-2 text-right">
                    <button type="button" onClick={() => { setEditField(f); setEditVal(f.field_value); }} className="p-1 text-gray-500 hover:text-white"><Pencil size={13} /></button>
                    <button type="button" onClick={() => deleteField(f.id)} className="p-1 text-gray-500 hover:text-red-400"><Trash2 size={13} /></button>
                  </td>
                </tr>
              ))}
              {!data.fields.length && (
                <tr><td colSpan={3} className="py-6 text-center text-gray-600">No fields</td></tr>
              )}
            </tbody>
          </table>
        </div>

        <div className="bg-gray-900 border border-gray-800 rounded-xl p-5">
          <h2 className="text-lg font-semibold text-white mb-3">Related entities</h2>
          <div className="space-y-2 max-h-80 overflow-y-auto">
            {rels.map((r) => (
              <Link
                key={r.entity_id}
                to={`/admin/entities/${r.entity_id}`}
                className="flex items-center justify-between p-3 rounded-lg bg-gray-800/50 hover:bg-gray-800 transition-colors"
              >
                <div>
                  <div className="text-white font-medium">{r.name}</div>
                  <div className="text-xs text-gray-500 capitalize">{r.entity_type} · {r.shared_document_count} shared docs</div>
                </div>
              </Link>
            ))}
            {!rels.length && <p className="text-gray-600 text-sm">No co-occurring entities</p>}
          </div>
        </div>
      </div>

      <div className="bg-gray-900 border border-gray-800 rounded-xl p-5">
        <h2 className="text-lg font-semibold text-white mb-4">Documents</h2>
        <table className="w-full text-sm">
          <thead>
            <tr className="text-gray-500 text-xs border-b border-gray-800">
              <th className="text-left py-2">Filename</th>
              <th className="text-left py-2">Role</th>
              <th className="text-left py-2">Status</th>
              <th className="text-left py-2">Confidence</th>
            </tr>
          </thead>
          <tbody>
            {data.documents.map((d) => (
              <tr key={d.document_id} className="border-b border-gray-800/50">
                <td className="py-2">
                  <Link to={`/documents/${d.document_id}`} className="text-blue-400 hover:underline">{d.filename}</Link>
                </td>
                <td className="py-2"><Badge value={d.role} /></td>
                <td className="py-2">{d.status && <Badge value={d.status} />}</td>
                <td className="py-2 text-gray-400">
                  {d.pipeline_confidence != null ? `${(d.pipeline_confidence * 100).toFixed(0)}%` : '—'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <Modal open={!!editField} onClose={() => setEditField(null)} title="Edit field">
        <div className="space-y-4">
          <input value={editVal} onChange={(ev) => setEditVal(ev.target.value)} className="w-full px-3 py-2 rounded-lg bg-gray-800 border border-gray-700 text-white text-sm" />
          <button type="button" onClick={saveField} className="w-full py-2.5 rounded-lg bg-blue-600 text-white text-sm">Save</button>
        </div>
      </Modal>

      <Modal open={showAddField} onClose={() => setShowAddField(false)} title="Add field">
        <div className="space-y-4">
          <input placeholder="Name" value={newFieldName} onChange={(ev) => setNewFieldName(ev.target.value)} className="w-full px-3 py-2 rounded-lg bg-gray-800 border border-gray-700 text-white text-sm" />
          <input placeholder="Value" value={newFieldValue} onChange={(ev) => setNewFieldValue(ev.target.value)} className="w-full px-3 py-2 rounded-lg bg-gray-800 border border-gray-700 text-white text-sm" />
          <button type="button" onClick={addField} className="w-full py-2.5 rounded-lg bg-blue-600 text-white text-sm">Add</button>
        </div>
      </Modal>

      {/* Notes section */}
      <div className="bg-gray-900 border border-gray-800 rounded-xl p-5">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <MessageSquare size={16} className="text-gray-500" />
            <h2 className="text-lg font-semibold text-white">Notes</h2>
          </div>
          {!showNotes && (
            <button type="button"
              onClick={() => { setShowNotes(true); loadComments(); }}
              className="text-sm text-blue-400 hover:text-blue-300">
              Show notes
            </button>
          )}
        </div>
        {showNotes && (
          <CommentThread
            comments={comments}
            loading={commentsLoading}
            onAdd={async (content, parentId) => {
              if (id) { await api.createEntityComment(id, content, parentId); await loadComments(); }
            }}
            onEdit={async (commentId, content) => {
              if (id) { await api.updateEntityComment(id, commentId, content); await loadComments(); }
            }}
            onDelete={async (commentId) => {
              if (id && confirm('Delete this note?')) { await api.deleteEntityComment(id, commentId); await loadComments(); }
            }}
          />
        )}
      </div>

      <Modal open={mergeOpen} onClose={() => setMergeOpen(false)} title="Merge entity">
        <p className="text-sm text-gray-400 mb-3">
          All links and fields from this entity will move into the target. This entity will be deleted.
        </p>
        <input
          value={mergeSearch}
          onChange={(ev) => searchMergeTargets(ev.target.value)}
          placeholder="Search target entity by name…"
          className="w-full px-3 py-2 rounded-lg bg-gray-800 border border-gray-700 text-white text-sm mb-3"
        />
        <div className="space-y-1 max-h-40 overflow-y-auto mb-3">
          {mergeCandidates.map((c) => (
            <button
              key={c.id}
              type="button"
              onClick={() => setMergeTarget(c.id)}
              className={`w-full text-left px-3 py-2 rounded-lg text-sm ${mergeTarget === c.id ? 'bg-blue-600/30 text-blue-300' : 'bg-gray-800 text-gray-300 hover:bg-gray-700'}`}
            >
              {c.name}
            </button>
          ))}
        </div>
        <button
          type="button"
          disabled={!mergeTarget}
          onClick={doMerge}
          className="w-full py-2.5 rounded-lg bg-amber-600 text-white text-sm disabled:opacity-50"
        >
          Merge into selected
        </button>
      </Modal>
    </div>
  );
}
