import { useEffect, useState, useCallback } from 'react';
import { Link } from 'react-router-dom';
import { ChevronLeft, ChevronRight, X, FileText, User } from 'lucide-react';
import { api, type AuditFeedItem } from '../api';

// ---------------------------------------------------------------------------
// Action metadata
// ---------------------------------------------------------------------------

const ACTION_META: Record<string, { label: string; color: string }> = {
  field_updated:          { label: 'Field updated',        color: 'bg-indigo-900/40 text-indigo-300 border-indigo-800/50' },
  entity_resolved:        { label: 'Entity resolved',      color: 'bg-teal-900/40 text-teal-300 border-teal-800/50' },
  comment_added:          { label: 'Note added',           color: 'bg-blue-900/40 text-blue-300 border-blue-800/50' },
  comment_edited:         { label: 'Note edited',          color: 'bg-blue-900/40 text-blue-300 border-blue-800/50' },
  comment_deleted:        { label: 'Note deleted',         color: 'bg-red-900/40 text-red-300 border-red-800/50' },
  archived:               { label: 'Archived',             color: 'bg-gray-800 text-gray-400 border-gray-700' },
  unarchived:             { label: 'Unarchived',           color: 'bg-gray-800 text-gray-400 border-gray-700' },
  trashed:                { label: 'Trashed',              color: 'bg-red-900/30 text-red-400 border-red-800/40' },
  restored_from_trash:    { label: 'Restored',             color: 'bg-green-900/40 text-green-300 border-green-800/50' },
  classification_updated: { label: 'Classification',       color: 'bg-purple-900/40 text-purple-300 border-purple-800/50' },
  entity_field_updated:   { label: 'Entity field',         color: 'bg-cyan-900/40 text-cyan-300 border-cyan-800/50' },
};

function ActionBadge({ action }: { action: string }) {
  const meta = ACTION_META[action] ?? { label: action.replace(/_/g, ' '), color: 'bg-gray-800 text-gray-400 border-gray-700' };
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded text-[11px] font-medium border ${meta.color}`}>
      {meta.label}
    </span>
  );
}

function reltime(iso: string) {
  const s = Math.floor((Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60)    return `${s}s ago`;
  if (s < 3600)  return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return new Date(iso).toLocaleDateString();
}

const PAGE_SIZE = 30;

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function ActivityPage() {
  const [items, setItems]           = useState<AuditFeedItem[]>([]);
  const [total, setTotal]           = useState(0);
  const [page, setPage]             = useState(1);
  const [loading, setLoading]       = useState(false);
  const [actionTypes, setActionTypes] = useState<string[]>([]);
  const [filterAction, setFilterAction] = useState('');

  const load = useCallback(async (p = page, action = filterAction) => {
    setLoading(true);
    try {
      const res = await api.getActivity({ page: p, page_size: PAGE_SIZE, action: action || undefined });
      setItems(res.items);
      setTotal(res.total);
      if (res.action_types.length > 0 && actionTypes.length === 0) {
        setActionTypes(res.action_types);
      }
    } finally {
      setLoading(false);
    }
  }, [page, filterAction, actionTypes.length]);

  useEffect(() => { load(1, ''); }, []);

  const goPage = (p: number) => {
    setPage(p);
    load(p, filterAction);
  };

  const selectAction = (a: string) => {
    setFilterAction(a);
    setPage(1);
    load(1, a);
  };

  const totalPages = Math.ceil(total / PAGE_SIZE);

  return (
    <div className="space-y-5">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-white">Global activity</h1>
        <p className="text-sm text-gray-500 mt-0.5">
          {loading ? 'Loading…' : `${total.toLocaleString()} event${total !== 1 ? 's' : ''}${filterAction ? ` · ${filterAction.replace(/_/g, ' ')}` : ''}`}
        </p>
      </div>

      {/* Action type filter */}
      <div className="flex flex-wrap gap-2">
        <button
          onClick={() => selectAction('')}
          className={`px-3 py-1.5 rounded-full text-xs font-medium border transition-colors ${
            filterAction === ''
              ? 'bg-blue-600/20 border-blue-500/40 text-blue-300'
              : 'bg-gray-900 border-gray-700 text-gray-500 hover:text-gray-300'
          }`}
        >
          All
        </button>
        {actionTypes.map(a => {
          const meta = ACTION_META[a];
          return (
            <button key={a} onClick={() => selectAction(a)}
              className={`px-3 py-1.5 rounded-full text-xs font-medium border transition-colors ${
                filterAction === a
                  ? 'bg-blue-600/20 border-blue-500/40 text-blue-300'
                  : 'bg-gray-900 border-gray-700 text-gray-500 hover:text-gray-300'
              }`}
            >
              {meta?.label ?? a.replace(/_/g, ' ')}
            </button>
          );
        })}
        {filterAction && (
          <button onClick={() => selectAction('')}
            className="flex items-center gap-1 px-2 py-1.5 rounded-full text-xs text-gray-500 hover:text-gray-300">
            <X size={11} /> Clear
          </button>
        )}
      </div>

      {/* Table */}
      <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-gray-800 text-gray-500 text-xs uppercase tracking-wider">
              <th className="text-left px-4 py-3">Action</th>
              <th className="text-left px-4 py-3">Document</th>
              <th className="text-left px-4 py-3">Details</th>
              <th className="text-left px-4 py-3">By</th>
              <th className="text-left px-4 py-3">When</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr>
                <td colSpan={5} className="px-4 py-10 text-center text-gray-600">Loading…</td>
              </tr>
            ) : items.length === 0 ? (
              <tr>
                <td colSpan={5} className="px-4 py-10 text-center text-gray-600">No activity found</td>
              </tr>
            ) : items.map(item => (
              <tr key={item.id} className="border-b border-gray-800/50 hover:bg-gray-800/30 transition-colors">
                <td className="px-4 py-3">
                  <ActionBadge action={item.action} />
                </td>
                <td className="px-4 py-3">
                  <Link to={`/documents/${item.document_id}`}
                    className="text-blue-400 hover:underline flex items-center gap-1.5 truncate max-w-[200px]">
                    <FileText size={12} className="text-gray-600 flex-shrink-0" />
                    {item.filename ?? item.document_id}
                  </Link>
                </td>
                <td className="px-4 py-3 text-gray-500 text-xs max-w-xs truncate">
                  {item.details ?? '—'}
                </td>
                <td className="px-4 py-3">
                  {item.actor ? (
                    <span className="flex items-center gap-1.5 text-xs text-gray-400">
                      <User size={11} className="text-gray-600" /> {item.actor}
                    </span>
                  ) : (
                    <span className="text-xs text-gray-600">System</span>
                  )}
                </td>
                <td className="px-4 py-3 text-xs text-gray-500 whitespace-nowrap">
                  <span title={new Date(item.created_at).toLocaleString()}>
                    {reltime(item.created_at)}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-center gap-3">
          <button onClick={() => goPage(Math.max(1, page - 1))} disabled={page === 1}
            className="flex items-center gap-1 px-3 py-1.5 rounded-lg bg-gray-800 text-gray-400 text-sm hover:bg-gray-700 disabled:opacity-40 transition-colors">
            <ChevronLeft size={14} /> Prev
          </button>
          <span className="text-sm text-gray-500">
            Page <span className="text-gray-300 font-medium">{page}</span> of {totalPages}
          </span>
          <button onClick={() => goPage(page + 1)} disabled={page >= totalPages}
            className="flex items-center gap-1 px-3 py-1.5 rounded-lg bg-gray-800 text-gray-400 text-sm hover:bg-gray-700 disabled:opacity-40 transition-colors">
            Next <ChevronRight size={14} />
          </button>
        </div>
      )}
    </div>
  );
}
