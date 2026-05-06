import { useEffect, useState, useCallback, useRef } from 'react';
import { Link } from 'react-router-dom';
import { Search, X, ChevronLeft, ChevronRight, SlidersHorizontal, FileText, Hash, Users, AlignLeft } from 'lucide-react';
import { api, type DocumentSummary, type SearchResult, type SearchScope } from '../api';
import Badge from '../components/Badge';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

type LifecycleFilter = '' | 'archived' | 'trashed';

const SCOPE_LABELS: Record<SearchScope, { label: string; icon: React.ReactNode }> = {
  filename: { label: 'Filename', icon: <FileText size={12} /> },
  content:  { label: 'Content',  icon: <AlignLeft size={12} /> },
  fields:   { label: 'Fields',   icon: <Hash size={12} /> },
  entities: { label: 'Entities', icon: <Users size={12} /> },
};

const ALL_SCOPES: SearchScope[] = ['filename', 'content', 'fields', 'entities'];

function ConfidenceBadge({ value }: { value: number | null | undefined }) {
  if (value == null) return <span className="text-gray-600">—</span>;
  const pct = (value * 100).toFixed(0);
  const color = value >= 0.7 ? 'text-green-400' : value >= 0.5 ? 'text-yellow-400' : 'text-red-400';
  return <span className={`font-medium tabular-nums ${color}`}>{pct}%</span>;
}

function MatchChip({ type }: { type: string }) {
  const isField    = type.startsWith('field:');
  const isEntity   = type.startsWith('entity:');
  const isContent  = type === 'content';
  const isFilename = type === 'filename';
  const isClass    = type === 'classification';

  let bg = 'bg-gray-800 text-gray-400';
  if (isField)    bg = 'bg-indigo-900/40 text-indigo-300';
  if (isEntity)   bg = 'bg-teal-900/40 text-teal-300';
  if (isContent)  bg = 'bg-amber-900/40 text-amber-300';
  if (isFilename) bg = 'bg-blue-900/40 text-blue-300';
  if (isClass)    bg = 'bg-purple-900/40 text-purple-300';

  const label = isField   ? type.slice(6)
              : isEntity  ? type.slice(7)
              : type;

  return (
    <span className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium ${bg}`}>
      {label}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Page component
// ---------------------------------------------------------------------------

const PAGE_SIZE = 20;

export default function DocumentsPage() {
  // — search state -----------------------------------------------------------
  const [query, setQuery]     = useState('');
  const [activeQ, setActiveQ] = useState('');         // committed query
  const [scopes, setScopes]   = useState<Set<SearchScope>>(new Set(ALL_SCOPES));

  // — facet state ------------------------------------------------------------
  const [statusFilter, setStatusFilter]       = useState('');
  const [classFilter, setClassFilter]         = useState('');
  const [lifecycleFilter, setLifecycleFilter] = useState<LifecycleFilter>('');
  const [showFacets, setShowFacets]           = useState(false);

  // — results ----------------------------------------------------------------
  const [results, setResults]       = useState<SearchResult[]>([]);
  const [browseDocs, setBrowseDocs] = useState<DocumentSummary[]>([]);
  const [total, setTotal]           = useState(0);
  const [page, setPage]             = useState(1);
  const [loading, setLoading]       = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  // — browse (no query) mode -------------------------------------------------
  const loadBrowse = useCallback(async (p = 1) => {
    setLoading(true);
    try {
      const params: Record<string, string> = { page: String(p), page_size: String(PAGE_SIZE) };
      if (statusFilter)   params.status         = statusFilter;
      if (classFilter)    params.classification  = classFilter;
      if (lifecycleFilter === 'archived') params.archived = 'true';
      if (lifecycleFilter === 'trashed')  params.trashed  = 'true';
      const res = await api.getDocuments(params);
      setBrowseDocs(res.documents);
      setResults([]);
      setTotal(res.total);
    } finally {
      setLoading(false);
    }
  }, [statusFilter, classFilter, lifecycleFilter]);

  // — search mode ------------------------------------------------------------
  const runSearch = useCallback(async (q: string, p = 1) => {
    if (!q.trim()) { setActiveQ(''); loadBrowse(p); return; }
    setLoading(true);
    try {
      const res = await api.search(q.trim(), {
        scope: [...scopes].join(','),
        status: statusFilter || undefined,
        classification: classFilter || undefined,
        page: p,
        page_size: PAGE_SIZE,
      });
      setResults(res.results);
      setBrowseDocs([]);
      setTotal(res.total);
    } finally {
      setLoading(false);
    }
  }, [scopes, statusFilter, classFilter]);

  // Initial load
  useEffect(() => { loadBrowse(1); }, []);

  // Re-run when facets change while a query is active
  useEffect(() => {
    if (activeQ) runSearch(activeQ, 1);
    else         loadBrowse(1);
    setPage(1);
  }, [statusFilter, classFilter, lifecycleFilter]);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setPage(1);
    setActiveQ(query);
    runSearch(query, 1);
  };

  const clearQuery = () => {
    setQuery('');
    setActiveQ('');
    setPage(1);
    loadBrowse(1);
    inputRef.current?.focus();
  };

  const clearAllFacets = () => {
    setStatusFilter('');
    setClassFilter('');
    setLifecycleFilter('');
  };

  const toggleScope = (s: SearchScope) => {
    setScopes(prev => {
      const next = new Set(prev);
      if (next.has(s) && next.size > 1) next.delete(s);
      else next.add(s);
      return next;
    });
  };

  const goPage = (p: number) => {
    setPage(p);
    if (activeQ) runSearch(activeQ, p);
    else         loadBrowse(p);
  };

  const hasActiveFacets = !!(statusFilter || classFilter || lifecycleFilter);
  const totalPages = Math.ceil(total / PAGE_SIZE);
  const isSearchMode = !!activeQ;

  return (
    <div className="space-y-5">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">Search</h1>
          <p className="text-sm text-gray-500 mt-0.5">
            {loading ? 'Searching…' : `${total.toLocaleString()} document${total !== 1 ? 's' : ''}${isSearchMode ? ` for "${activeQ}"` : ''}`}
          </p>
        </div>
      </div>

      {/* Search bar */}
      <form onSubmit={handleSubmit} className="flex gap-2">
        <div className="relative flex-1">
          <Search size={16} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-gray-500 pointer-events-none" />
          <input
            ref={inputRef}
            value={query}
            onChange={e => setQuery(e.target.value)}
            placeholder="Search documents, fields, entities…"
            className="w-full pl-10 pr-10 py-2.5 rounded-xl bg-gray-900 border border-gray-700 text-white text-sm placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-blue-500 transition"
          />
          {query && (
            <button type="button" onClick={clearQuery}
              className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-500 hover:text-gray-300">
              <X size={15} />
            </button>
          )}
        </div>
        <button type="submit" disabled={loading}
          className="px-5 py-2.5 rounded-xl bg-blue-600 text-white text-sm font-medium hover:bg-blue-500 disabled:opacity-50 transition-colors">
          Search
        </button>
        <button type="button" onClick={() => setShowFacets(v => !v)}
          className={`flex items-center gap-1.5 px-3.5 py-2.5 rounded-xl text-sm border transition-colors ${
            showFacets || hasActiveFacets
              ? 'bg-blue-600/15 border-blue-500/40 text-blue-400'
              : 'bg-gray-900 border-gray-700 text-gray-400 hover:text-gray-200'
          }`}
          title="Filters">
          <SlidersHorizontal size={15} />
          {hasActiveFacets && <span className="w-1.5 h-1.5 rounded-full bg-blue-400" />}
        </button>
      </form>

      {/* Scope toggles (always visible) */}
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs text-gray-600 mr-1">Search in:</span>
        {ALL_SCOPES.map(s => (
          <button key={s} onClick={() => toggleScope(s)}
            className={`flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium border transition-colors ${
              scopes.has(s)
                ? 'bg-blue-600/20 border-blue-500/40 text-blue-300'
                : 'bg-gray-900 border-gray-700 text-gray-500 hover:text-gray-300'
            }`}>
            {SCOPE_LABELS[s].icon}
            {SCOPE_LABELS[s].label}
          </button>
        ))}
      </div>

      {/* Facet sidebar (collapsible) */}
      {showFacets && (
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-4 flex flex-wrap gap-4 items-end">
          <div className="flex flex-col gap-1">
            <label className="text-xs text-gray-500 uppercase tracking-wider">Status</label>
            <select value={statusFilter} onChange={e => setStatusFilter(e.target.value)}
              className="px-3 py-1.5 rounded-lg bg-gray-800 border border-gray-700 text-gray-300 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500">
              <option value="">Any</option>
              <option value="COMPLETED">Completed</option>
              <option value="INGESTED">Ingested</option>
              <option value="OCR_DONE">OCR Done</option>
              <option value="CLASSIFIED">Classified</option>
            </select>
          </div>
          <div className="flex flex-col gap-1">
            <label className="text-xs text-gray-500 uppercase tracking-wider">Classification</label>
            <input value={classFilter} onChange={e => setClassFilter(e.target.value)}
              placeholder="e.g. invoice"
              className="px-3 py-1.5 rounded-lg bg-gray-800 border border-gray-700 text-white text-sm placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-blue-500 w-40" />
          </div>
          <div className="flex flex-col gap-1">
            <label className="text-xs text-gray-500 uppercase tracking-wider">Lifecycle</label>
            <select value={lifecycleFilter} onChange={e => setLifecycleFilter(e.target.value as LifecycleFilter)}
              className="px-3 py-1.5 rounded-lg bg-gray-800 border border-gray-700 text-gray-300 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500">
              <option value="">Active</option>
              <option value="archived">Archived</option>
              <option value="trashed">Trash</option>
            </select>
          </div>
          {hasActiveFacets && (
            <button onClick={clearAllFacets}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm text-gray-500 hover:text-gray-300 transition-colors">
              <X size={13} /> Clear filters
            </button>
          )}
        </div>
      )}

      {/* Active filter pills */}
      {hasActiveFacets && !showFacets && (
        <div className="flex flex-wrap gap-2">
          {statusFilter && (
            <span className="flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs bg-gray-800 border border-gray-700 text-gray-300">
              Status: {statusFilter}
              <button onClick={() => setStatusFilter('')}><X size={11} /></button>
            </span>
          )}
          {classFilter && (
            <span className="flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs bg-gray-800 border border-gray-700 text-gray-300">
              Class: {classFilter}
              <button onClick={() => setClassFilter('')}><X size={11} /></button>
            </span>
          )}
          {lifecycleFilter && (
            <span className="flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs bg-gray-800 border border-gray-700 text-gray-300">
              {lifecycleFilter}
              <button onClick={() => setLifecycleFilter('')}><X size={11} /></button>
            </span>
          )}
        </div>
      )}

      {/* Results table */}
      <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-gray-800 text-gray-500 text-xs uppercase tracking-wider">
              <th className="text-left px-4 py-3">Document</th>
              {isSearchMode && <th className="text-left px-4 py-3">Match</th>}
              <th className="text-left px-4 py-3">Classification</th>
              <th className="text-left px-4 py-3">Status</th>
              <th className="text-left px-4 py-3">Confidence</th>
              <th className="text-left px-4 py-3">Date</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr>
                <td colSpan={isSearchMode ? 6 : 5} className="px-4 py-10 text-center text-gray-600">
                  Searching…
                </td>
              </tr>
            ) : isSearchMode ? (
              results.length === 0 ? (
                <tr>
                  <td colSpan={6} className="px-4 py-10 text-center text-gray-600">
                    No results for <span className="text-gray-400">"{activeQ}"</span>
                  </td>
                </tr>
              ) : results.map((r, i) => (
                <tr key={`${r.document_id}-${i}`} className="border-b border-gray-800/50 hover:bg-gray-800/30 transition-colors">
                  <td className="px-4 py-3">
                    <Link to={`/documents/${r.document_id}`}
                      className="text-blue-400 hover:underline font-medium truncate block max-w-xs">
                      {r.filename || r.document_id}
                    </Link>
                  </td>
                  <td className="px-4 py-3 max-w-xs">
                    <div className="flex flex-col gap-0.5">
                      <MatchChip type={r.match_type} />
                      {r.snippet && (
                        <span className="text-xs text-gray-500 truncate mt-0.5 block">{r.snippet}</span>
                      )}
                    </div>
                  </td>
                  <td className="px-4 py-3 text-gray-400 text-xs">
                    {[r.classification_label, r.classification_subcategory_label].filter(Boolean).join(' / ') || '—'}
                  </td>
                  <td className="px-4 py-3">
                    {r.status ? <Badge value={r.status} /> : <span className="text-gray-600">—</span>}
                  </td>
                  <td className="px-4 py-3"><ConfidenceBadge value={r.pipeline_confidence} /></td>
                  <td className="px-4 py-3 text-gray-500 text-xs whitespace-nowrap">
                    {r.created_at ? new Date(r.created_at).toLocaleDateString() : '—'}
                  </td>
                </tr>
              ))
            ) : (
              browseDocs.length === 0 ? (
                <tr>
                  <td colSpan={5} className="px-4 py-10 text-center text-gray-600">No documents found</td>
                </tr>
              ) : browseDocs.map(d => (
                <tr key={d.id} className="border-b border-gray-800/50 hover:bg-gray-800/30 transition-colors">
                  <td className="px-4 py-3">
                    <Link to={`/documents/${d.id}`} className="text-blue-400 hover:underline font-medium">
                      {d.filename}
                    </Link>
                  </td>
                  <td className="px-4 py-3 text-gray-400 text-xs">
                    {[d.classification_label, d.classification_subcategory_label].filter(Boolean).join(' / ') || '—'}
                  </td>
                  <td className="px-4 py-3"><Badge value={d.status} /></td>
                  <td className="px-4 py-3"><ConfidenceBadge value={d.pipeline_confidence} /></td>
                  <td className="px-4 py-3 text-gray-500 text-xs">{new Date(d.created_at).toLocaleDateString()}</td>
                </tr>
              ))
            )}
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
