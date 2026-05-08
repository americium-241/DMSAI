import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { Archive, Trash2, RotateCcw, Layers, AlertTriangle, RefreshCw, Settings2 } from 'lucide-react';
import { api, type ArchivedDocumentSummary, type CompactResult, type PurgeTrashResult, type RetentionSettings } from '../../api';
import Badge from '../../components/Badge';
import { useToast } from '../../components/Toast';

type ViewTab = 'archived' | 'trashed';

export default function ArchiveManagement() {
  const { show } = useToast();
  const [tab, setTab] = useState<ViewTab>('archived');
  const [docs, setDocs] = useState<ArchivedDocumentSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(false);
  const [compacting, setCompacting] = useState(false);
  const [compactResult, setCompactResult] = useState<CompactResult | null>(null);
  const [purgeResult, setPurgeResult] = useState<PurgeTrashResult | null>(null);
  const [purging, setPurging] = useState(false);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const PAGE_SIZE = 30;

  // Retention settings
  const [retention, setRetention] = useState<RetentionSettings | null>(null);
  const [retentionEdit, setRetentionEdit] = useState<{ archive: string; trash: string }>({ archive: '', trash: '' });
  const [savingRetention, setSavingRetention] = useState(false);

  const load = async (t = tab, p = page) => {
    setLoading(true);
    try {
      const res = await api.getArchivedDocuments(t, p);
      setDocs(res.documents);
      setTotal(res.total);
    } catch (e) {
      show(String(e), 'error');
    } finally {
      setLoading(false);
    }
  };

  const loadRetention = async () => {
    try {
      const r = await api.getRetentionSettings();
      setRetention(r);
      setRetentionEdit({
        archive: r.org_archive_retention_days !== null ? String(r.org_archive_retention_days) : '',
        trash: r.org_trash_retention_days !== null ? String(r.org_trash_retention_days) : '',
      });
    } catch { /* non-fatal */ }
  };

  const handleSaveRetention = async () => {
    setSavingRetention(true);
    try {
      const payload: { archive_retention_days?: number | null; trash_retention_days?: number | null } = {};
      payload.archive_retention_days = retentionEdit.archive === '' ? null : parseInt(retentionEdit.archive, 10);
      payload.trash_retention_days = retentionEdit.trash === '' ? null : parseInt(retentionEdit.trash, 10);
      if (
        (payload.archive_retention_days !== null && isNaN(payload.archive_retention_days)) ||
        (payload.trash_retention_days !== null && isNaN(payload.trash_retention_days))
      ) {
        show('Please enter valid numbers', 'error');
        return;
      }
      await api.updateRetentionSettings(payload);
      show('Retention settings saved', 'success');
      loadRetention();
    } catch (e) { show(String(e), 'error'); }
    finally { setSavingRetention(false); }
  };

  useEffect(() => { load(tab, 1); setPage(1); }, [tab]);
  useEffect(() => { loadRetention(); }, []);

  const handleCompact = async () => {
    setCompacting(true);
    setCompactResult(null);
    try {
      const r = await api.compactStorage();
      setCompactResult(r);
      if (r.compressed.length > 0) show(`Compressed ${r.compressed.length} file(s)`, 'success');
      else show('Nothing to compress', 'info');
      load(tab, page);
    } catch (e) { show(String(e), 'error'); }
    finally { setCompacting(false); }
  };

  const handlePurgeCheck = async () => {
    setPurging(true);
    setPurgeResult(null);
    try {
      const r = await api.purgeTrashCandidates();
      setPurgeResult(r);
    } catch (e) { show(String(e), 'error'); }
    finally { setPurging(false); }
  };

  const handlePermanentDelete = async (docId: string, filename: string) => {
    if (!confirm(`Permanently delete "${filename}"? This cannot be undone.`)) return;
    setDeletingId(docId);
    try {
      await api.permanentDeleteDocument(docId);
      show('Document permanently deleted', 'success');
      load(tab, page);
      setPurgeResult(prev => prev ? { ...prev, candidates: prev.candidates.filter(c => c.id !== docId) } : null);
    } catch (e) { show(String(e), 'error'); }
    finally { setDeletingId(null); }
  };

  const handleRestore = async (docId: string) => {
    try {
      await api.restoreDocument(docId);
      show('Document restored', 'success');
      load(tab, page);
    } catch (e) { show(String(e), 'error'); }
  };

  const handleUnarchive = async (docId: string) => {
    try {
      await api.unarchiveDocument(docId);
      show('Document unarchived', 'success');
      load(tab, page);
    } catch (e) { show(String(e), 'error'); }
  };

  const totalPages = Math.ceil(total / PAGE_SIZE);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-white">Archive & Trash</h1>
        <p className="text-sm text-gray-500 mt-1">Manage archived and trashed documents, run storage compaction, and permanently delete trashed items.</p>
      </div>

      {/* Retention settings */}
      <div className="bg-gray-900 border border-gray-800 rounded-xl p-5 space-y-4">
        <div className="flex items-center gap-2">
          <Settings2 size={16} className="text-purple-400" />
          <h3 className="text-sm font-semibold text-white">Retention Periods</h3>
          <span className="ml-auto text-xs text-gray-600">Organisation override — leave blank to use global default</span>
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div className="space-y-1.5">
            <label className="text-xs text-gray-400 flex justify-between">
              <span>Archive compression after (days)</span>
              {retention && (
                <span className="text-gray-600">
                  global: {retention.global_archive_retention_days}d
                  {retention.org_archive_retention_days !== null && (
                    <span className="text-purple-400 ml-1">→ org: {retention.org_archive_retention_days}d</span>
                  )}
                </span>
              )}
            </label>
            <input
              type="number" min={0}
              value={retentionEdit.archive}
              onChange={e => setRetentionEdit(v => ({ ...v, archive: e.target.value }))}
              placeholder={retention ? `Default: ${retention.global_archive_retention_days}` : '90'}
              className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-purple-500 placeholder-gray-600"
            />
            {retention && (
              <p className="text-xs text-gray-600">
                Effective: <span className="text-white">{retention.effective_archive_retention_days} days</span>
                {retention.effective_archive_retention_days === 0 && <span className="text-yellow-500 ml-1">(disabled)</span>}
              </p>
            )}
          </div>
          <div className="space-y-1.5">
            <label className="text-xs text-gray-400 flex justify-between">
              <span>Trash auto-purge after (days)</span>
              {retention && (
                <span className="text-gray-600">
                  global: {retention.global_trash_retention_days}d
                  {retention.org_trash_retention_days !== null && (
                    <span className="text-purple-400 ml-1">→ org: {retention.org_trash_retention_days}d</span>
                  )}
                </span>
              )}
            </label>
            <input
              type="number" min={0}
              value={retentionEdit.trash}
              onChange={e => setRetentionEdit(v => ({ ...v, trash: e.target.value }))}
              placeholder={retention ? `Default: ${retention.global_trash_retention_days}` : '30'}
              className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-purple-500 placeholder-gray-600"
            />
            {retention && (
              <p className="text-xs text-gray-600">
                Effective: <span className="text-white">{retention.effective_trash_retention_days} days</span>
                {retention.effective_trash_retention_days === 0 && <span className="text-yellow-500 ml-1">(disabled)</span>}
              </p>
            )}
          </div>
        </div>
        <div className="flex items-center gap-3">
          <button
            onClick={handleSaveRetention}
            disabled={savingRetention}
            className="flex items-center gap-2 px-4 py-2 rounded-lg bg-purple-600/20 text-purple-400 text-sm hover:bg-purple-600/30 disabled:opacity-50"
          >
            <Settings2 size={14} />
            {savingRetention ? 'Saving…' : 'Save retention settings'}
          </button>
          {(retentionEdit.archive !== '' || retentionEdit.trash !== '') && (
            <button
              onClick={() => {
                setRetentionEdit({ archive: '', trash: '' });
                api.updateRetentionSettings({ archive_retention_days: null, trash_retention_days: null })
                  .then(() => { show('Reverted to global defaults', 'success'); loadRetention(); })
                  .catch(e => show(String(e), 'error'));
              }}
              className="text-xs text-gray-500 hover:text-gray-300 underline"
            >
              Revert to global defaults
            </button>
          )}
        </div>
      </div>

      {/* Action cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-5 space-y-3">
          <div className="flex items-center gap-2">
            <Layers size={16} className="text-cyan-400" />
            <h3 className="text-sm font-semibold text-white">Storage Compaction</h3>
          </div>
          <p className="text-xs text-gray-500">Compress archived PDFs whose retention period has elapsed. The compressed .gz file replaces the original on disk.</p>
          <button onClick={handleCompact} disabled={compacting}
            className="flex items-center gap-2 px-4 py-2 rounded-lg bg-cyan-600/20 text-cyan-400 text-sm hover:bg-cyan-600/30 disabled:opacity-50">
            <RefreshCw size={14} className={compacting ? 'animate-spin' : ''} />
            {compacting ? 'Compressing…' : 'Run compaction'}
          </button>
          {compactResult && (
            <div className="text-xs text-gray-400 bg-gray-800/50 rounded-lg px-3 py-2 space-y-1">
              {compactResult.status === 'disabled' ? (
                <div className="text-yellow-500">Compaction is disabled (retention = 0 or compression off)</div>
              ) : (
                <>
                  {compactResult.cutoff && (
                    <div className="text-gray-500">
                      Eligible: archived before <span className="text-white">{new Date(compactResult.cutoff).toLocaleDateString()}</span>
                      <span className="ml-1">({compactResult.retention_days}d retention)</span>
                    </div>
                  )}
                  <div><span className="text-cyan-400 font-medium">{compactResult.compressed.length}</span> compressed</div>
                  <div><span className="text-gray-500">{compactResult.already_done.length}</span> already compressed</div>
                  {compactResult.skipped.length > 0 && <div><span className="text-yellow-400">{compactResult.skipped.length}</span> skipped (missing files)</div>}
                  {compactResult.compressed.length === 0 && compactResult.already_done.length === 0 && (
                    <div className="text-gray-600 italic">No archived documents older than {compactResult.retention_days} days found.</div>
                  )}
                </>
              )}
            </div>
          )}
        </div>

        <div className="bg-gray-900 border border-gray-800 rounded-xl p-5 space-y-3">
          <div className="flex items-center gap-2">
            <AlertTriangle size={16} className="text-red-400" />
            <h3 className="text-sm font-semibold text-white">Trash Retention Check</h3>
          </div>
          <p className="text-xs text-gray-500">List documents in trash that have exceeded the retention period. You can then permanently delete each one.</p>
          <button onClick={handlePurgeCheck} disabled={purging}
            className="flex items-center gap-2 px-4 py-2 rounded-lg bg-red-600/20 text-red-400 text-sm hover:bg-red-600/30 disabled:opacity-50">
            <AlertTriangle size={14} />
            {purging ? 'Checking…' : 'Check overdue trash'}
          </button>
          {purgeResult && (
            <div className="text-xs text-gray-400 bg-gray-800/50 rounded-lg px-3 py-2 space-y-1">
              {purgeResult.status === 'disabled' ? (
                <div className="text-yellow-500">Trash purge is disabled (retention = 0)</div>
              ) : (
              <>
              <div>
                Retention: <span className="text-white font-medium">{purgeResult.trash_retention_days} days</span>
                {purgeResult.cutoff && (
                  <span className="ml-2 text-gray-600">— eligible if trashed before <span className="text-gray-400">{new Date(purgeResult.cutoff).toLocaleDateString()}</span></span>
                )}
              </div>
              <div><span className={`font-medium ${purgeResult.candidates.length > 0 ? 'text-red-400' : 'text-green-400'}`}>{purgeResult.candidates.length}</span> overdue
                {purgeResult.candidates.length === 0 && <span className="text-gray-600 italic ml-1">(no documents in trash older than {purgeResult.trash_retention_days} days)</span>}
              </div>
              {purgeResult.candidates.map(c => (
                <div key={c.id} className="flex items-center justify-between py-0.5">
                  <span className="text-gray-300 truncate">{c.filename}</span>
                  <button onClick={() => handlePermanentDelete(c.id, c.filename)}
                    disabled={deletingId === c.id}
                    className="ml-3 flex-shrink-0 text-xs text-red-400 hover:text-red-300 disabled:opacity-50 underline">
                    {deletingId === c.id ? 'Deleting…' : 'Delete permanently'}
                  </button>
                </div>
              ))}
              </>
              )}
            </div>
          )}
        </div>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 border-b border-gray-800">
        {([
          { key: 'archived' as ViewTab, label: 'Archived', icon: Archive },
          { key: 'trashed' as ViewTab, label: 'Trash', icon: Trash2 },
        ]).map(t => (
          <button key={t.key} onClick={() => setTab(t.key)}
            className={`flex items-center gap-1.5 px-4 py-2.5 text-sm font-medium border-b-2 transition-colors ${
              tab === t.key ? 'border-blue-500 text-blue-400' : 'border-transparent text-gray-500 hover:text-gray-300'
            }`}>
            <t.icon size={14} /> {t.label}
            {tab === t.key && <span className="ml-1 text-xs text-gray-600">({total})</span>}
          </button>
        ))}
      </div>

      {/* Table */}
      <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-gray-800 text-gray-500 text-xs uppercase tracking-wider">
              <th className="text-left px-4 py-3">Filename</th>
              <th className="text-left px-4 py-3">Classification</th>
              <th className="text-left px-4 py-3">{tab === 'archived' ? 'Archived' : 'Trashed'}</th>
              <th className="text-left px-4 py-3">Compressed</th>
              <th className="text-left px-4 py-3">Actions</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr><td colSpan={5} className="px-4 py-8 text-center text-gray-600">Loading…</td></tr>
            ) : docs.length === 0 ? (
              <tr><td colSpan={5} className="px-4 py-8 text-center text-gray-600">
                {tab === 'archived' ? 'No archived documents.' : 'Trash is empty.'}
              </td></tr>
            ) : docs.map(d => (
              <tr key={d.id} className="border-b border-gray-800/50 hover:bg-gray-800/30">
                <td className="px-4 py-3">
                  <Link to={`/documents/${d.id}`} className="text-blue-400 hover:underline truncate max-w-xs block">{d.filename}</Link>
                </td>
                <td className="px-4 py-3 text-gray-400">{d.classification_label || '—'}</td>
                <td className="px-4 py-3 text-gray-500 text-xs">
                  {tab === 'archived'
                    ? (d.archived_at ? new Date(d.archived_at).toLocaleString() : '—')
                    : (d.trashed_at ? new Date(d.trashed_at).toLocaleString() : '—')}
                </td>
                <td className="px-4 py-3">
                  {d.compressed_at ? <Badge value="compressed" /> : <span className="text-gray-700">—</span>}
                </td>
                <td className="px-4 py-3">
                  <div className="flex items-center gap-2">
                    {tab === 'archived' ? (
                      <button onClick={() => handleUnarchive(d.id)}
                        className="flex items-center gap-1 text-xs text-green-400 hover:text-green-300">
                        <RotateCcw size={11} /> Unarchive
                      </button>
                    ) : (
                      <>
                        <button onClick={() => handleRestore(d.id)}
                          className="flex items-center gap-1 text-xs text-green-400 hover:text-green-300">
                          <RotateCcw size={11} /> Restore
                        </button>
                        <button onClick={() => handlePermanentDelete(d.id, d.filename)}
                          disabled={deletingId === d.id}
                          className="flex items-center gap-1 text-xs text-red-400 hover:text-red-300 disabled:opacity-50">
                          <Trash2 size={11} /> {deletingId === d.id ? 'Deleting…' : 'Delete permanently'}
                        </button>
                      </>
                    )}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {totalPages > 1 && (
        <div className="flex items-center justify-center gap-2">
          <button onClick={() => { const p = Math.max(1, page - 1); setPage(p); load(tab, p); }}
            disabled={page === 1} className="px-3 py-1.5 rounded bg-gray-800 text-gray-400 text-sm hover:bg-gray-700 disabled:opacity-50">Prev</button>
          <span className="text-sm text-gray-500">Page {page} of {totalPages}</span>
          <button onClick={() => { const p = page + 1; setPage(p); load(tab, p); }}
            disabled={page >= totalPages} className="px-3 py-1.5 rounded bg-gray-800 text-gray-400 text-sm hover:bg-gray-700 disabled:opacity-50">Next</button>
        </div>
      )}
    </div>
  );
}
