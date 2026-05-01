import { useEffect, useState, useCallback } from 'react';
import { Link } from 'react-router-dom';
import { Search, X, ChevronRight, ChevronLeft } from 'lucide-react';
import { api, type DocumentSummary, type SearchResult, type EntityItem } from '../api';
import Badge from '../components/Badge';

type SearchMode = 'filters' | 'content' | 'entities';

function ConfidenceBadge({ value }: { value: number | null | undefined }) {
  if (value == null) return <span className="text-gray-600">---</span>;
  const pct = (value * 100).toFixed(0);
  const color = value >= 0.7 ? 'text-green-400' : value >= 0.5 ? 'text-yellow-400' : 'text-red-400';
  return <span className={`font-medium ${color}`}>{pct}%</span>;
}

export default function DocumentsPage() {
  const [docs, setDocs] = useState<DocumentSummary[]>([]);
  const [searchResults, setSearchResults] = useState<SearchResult[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [mode, setMode] = useState<SearchMode>('filters');

  // Filter-based search
  const [statusFilter, setStatusFilter] = useState('');
  const [classFilter, setClassFilter] = useState('');
  const [nameFilter, setNameFilter] = useState('');
  const [lifecycleFilter, setLifecycleFilter] = useState<'' | 'archived' | 'trashed'>('');

  // Content search
  const [contentQuery, setContentQuery] = useState('');

  // Entities tab
  const [entities, setEntities] = useState<EntityItem[]>([]);
  const [entitiesTotal, setEntitiesTotal] = useState(0);
  const [entitiesLoading, setEntitiesLoading] = useState(false);
  const [selectedEntity, setSelectedEntity] = useState<EntityItem | null>(null);
  const [entityDocs, setEntityDocs] = useState<DocumentSummary[]>([]);
  const [entityDocsLoading, setEntityDocsLoading] = useState(false);
  const [entityTypes, setEntityTypes] = useState<string[]>([]);
  const [activeTypeTag, setActiveTypeTag] = useState<string>('all');
  const [entityNameFilter, setEntityNameFilter] = useState('');
  const [entityPage, setEntityPage] = useState(1);
  const ENTITY_PAGE_SIZE = 50;

  const loadFiltered = async (p = page) => {
    setLoading(true);
    try {
      const params: Record<string, string> = { page: String(p), page_size: '20' };
      if (statusFilter) params.status = statusFilter;
      if (classFilter) params.classification = classFilter;
      if (nameFilter) params.search = nameFilter;
      if (lifecycleFilter === 'archived') params.archived = 'true';
      if (lifecycleFilter === 'trashed') params.trashed = 'true';
      const res = await api.getDocuments(params);
      setDocs(res.documents);
      setSearchResults([]);
      setTotal(res.total);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  const loadContent = async (p = 1) => {
    if (!contentQuery.trim()) return;
    setLoading(true);
    try {
      const res = await api.search(contentQuery.trim(), p);
      setSearchResults(res.results);
      setDocs([]);
      setTotal(res.total);
      setPage(p);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  const loadEntities = useCallback(async (p = entityPage, typeTag = activeTypeTag, nameQ = entityNameFilter) => {
    setEntitiesLoading(true);
    try {
      const params: Record<string, string> = { page: String(p), page_size: String(ENTITY_PAGE_SIZE) };
      if (typeTag && typeTag !== 'all') params.entity_type = typeTag;
      if (nameQ.trim()) params.search = nameQ.trim();
      const res = await api.getEntities(params);
      setEntities(res.items);
      setEntitiesTotal(res.total);
    } catch (e) {
      console.error(e);
    } finally {
      setEntitiesLoading(false);
    }
  }, [entityPage, activeTypeTag, entityNameFilter]);

  const loadEntityTypes = async () => {
    try {
      const types = await api.getEntityTypes();
      setEntityTypes(types);
    } catch (e) {
      console.error(e);
    }
  };

  const loadEntityDocs = async (entityId: string) => {
    setEntityDocsLoading(true);
    try {
      const res = await api.getDocuments({ entity_id: entityId, page_size: '100' });
      setEntityDocs(res.documents);
    } catch (e) {
      console.error(e);
    } finally {
      setEntityDocsLoading(false);
    }
  };

  useEffect(() => {
    if (mode === 'filters') loadFiltered(page);
  }, [page, statusFilter, classFilter]);

  const handleFilterSearch = (e: React.FormEvent) => {
    e.preventDefault();
    setPage(1);
    loadFiltered(1);
  };

  const handleContentSearch = (e: React.FormEvent) => {
    e.preventDefault();
    setPage(1);
    loadContent(1);
  };

  const switchMode = (m: SearchMode) => {
    setMode(m);
    setPage(1);
    setTotal(0);
    setSelectedEntity(null);
    setEntityDocs([]);
    if (m === 'filters') {
      setSearchResults([]);
      loadFiltered(1);
    } else if (m === 'content') {
      setDocs([]);
    } else if (m === 'entities') {
      setDocs([]);
      setSearchResults([]);
      setEntityPage(1);
      setActiveTypeTag('all');
      setEntityNameFilter('');
      loadEntities(1, 'all', '');
      loadEntityTypes();
    }
  };

  const clearFilters = () => {
    setStatusFilter('');
    setClassFilter('');
    setNameFilter('');
    setLifecycleFilter('');
    setPage(1);
  };

  const hasActiveFilters = !!(statusFilter || classFilter || nameFilter || lifecycleFilter);

  const entityTotalPages = Math.ceil(entitiesTotal / ENTITY_PAGE_SIZE);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-white">Search</h1>
        <p className="text-sm text-gray-500 mt-1">
          {mode === 'entities' ? `${entitiesTotal} entities` : `${total} document${total !== 1 ? 's' : ''} found`}
        </p>
      </div>

      <div className="flex gap-1 border-b border-gray-800">
        {([
          { key: 'filters' as const, label: 'Filter by fields' },
          { key: 'content' as const, label: 'Search content' },
          { key: 'entities' as const, label: 'Entities' },
        ]).map(t => (
          <button key={t.key} onClick={() => switchMode(t.key)}
            className={`px-4 py-2.5 text-sm font-medium border-b-2 transition-colors ${
              mode === t.key ? 'border-blue-500 text-blue-400' : 'border-transparent text-gray-500 hover:text-gray-300'
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {mode === 'filters' && (
        <div className="flex flex-wrap gap-3 items-end">
          <form onSubmit={handleFilterSearch} className="flex gap-2">
            <input
              value={nameFilter} onChange={e => setNameFilter(e.target.value)}
              className="px-3.5 py-2 rounded-lg bg-gray-900 border border-gray-800 text-white text-sm placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-blue-500 w-56"
              placeholder="Search by filename..."
            />
            <button type="submit" className="px-4 py-2 rounded-lg bg-gray-800 text-gray-300 text-sm hover:bg-gray-700 transition-colors">Filter</button>
          </form>
          <select value={statusFilter} onChange={e => { setStatusFilter(e.target.value); setPage(1); }}
            className="px-3 py-2 rounded-lg bg-gray-900 border border-gray-800 text-gray-300 text-sm focus:outline-none">
            <option value="">All statuses</option>
            <option value="COMPLETED">Completed</option>
            <option value="INGESTED">Ingested</option>
            <option value="OCR_DONE">OCR Done</option>
            <option value="CLASSIFIED">Classified</option>
          </select>
          <select value={lifecycleFilter} onChange={e => { setLifecycleFilter(e.target.value as '' | 'archived' | 'trashed'); setPage(1); loadFiltered(1); }}
            className="px-3 py-2 rounded-lg bg-gray-900 border border-gray-800 text-gray-300 text-sm focus:outline-none">
            <option value="">Active documents</option>
            <option value="archived">Archived</option>
            <option value="trashed">Trash</option>
          </select>
          <input value={classFilter} onChange={e => { setClassFilter(e.target.value); setPage(1); }}
            className="px-3.5 py-2 rounded-lg bg-gray-900 border border-gray-800 text-white text-sm placeholder-gray-500 focus:outline-none w-40"
            placeholder="Classification..."
          />
          {hasActiveFilters && (
            <button onClick={clearFilters} className="flex items-center gap-1 px-3 py-2 rounded-lg text-gray-500 hover:text-gray-300 text-sm">
              <X size={14} /> Clear
            </button>
          )}
        </div>
      )}

      {mode === 'content' && (
        <form onSubmit={handleContentSearch} className="flex gap-3">
          <div className="flex-1 relative">
            <Search size={16} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-gray-500" />
            <input
              value={contentQuery} onChange={e => setContentQuery(e.target.value)}
              className="w-full pl-10 pr-4 py-2.5 rounded-lg bg-gray-900 border border-gray-800 text-white text-sm placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-blue-500"
              placeholder="Search by document content, fields, entities..."
            />
          </div>
          <button type="submit" disabled={loading} className="px-6 py-2.5 rounded-lg bg-blue-600 text-white text-sm font-medium hover:bg-blue-500 disabled:opacity-50 transition-colors">
            {loading ? 'Searching...' : 'Search'}
          </button>
        </form>
      )}

      {mode === 'entities' && (
        <div className="space-y-4">
          <div className="flex flex-wrap items-center gap-2">
            <button
              onClick={() => { setActiveTypeTag('all'); setEntityPage(1); loadEntities(1, 'all', entityNameFilter); }}
              className={`px-3 py-1.5 rounded-full text-xs font-medium border transition-colors ${
                activeTypeTag === 'all' ? 'bg-blue-600/20 border-blue-500/50 text-blue-400' : 'bg-gray-800 border-gray-700 text-gray-400 hover:text-gray-200'
              }`}
            >All</button>
            {entityTypes.map(t => (
              <button key={t}
                onClick={() => { setActiveTypeTag(t); setEntityPage(1); loadEntities(1, t, entityNameFilter); }}
                className={`px-3 py-1.5 rounded-full text-xs font-medium border transition-colors capitalize ${
                  activeTypeTag === t ? 'bg-blue-600/20 border-blue-500/50 text-blue-400' : 'bg-gray-800 border-gray-700 text-gray-400 hover:text-gray-200'
                }`}
              >{t}</button>
            ))}
            <div className="ml-auto flex gap-2">
              <input
                value={entityNameFilter}
                onChange={e => setEntityNameFilter(e.target.value)}
                onKeyDown={e => { if (e.key === 'Enter') { setEntityPage(1); loadEntities(1, activeTypeTag, entityNameFilter); } }}
                placeholder="Filter by name..."
                className="px-3 py-1.5 rounded-lg bg-gray-900 border border-gray-800 text-white text-sm placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-blue-500 w-48"
              />
              <button
                onClick={() => { setEntityPage(1); loadEntities(1, activeTypeTag, entityNameFilter); }}
                className="px-3 py-1.5 rounded-lg bg-gray-800 text-gray-300 text-sm hover:bg-gray-700 transition-colors"
              ><Search size={14} /></button>
            </div>
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            <div className="lg:col-span-1 space-y-2">
              {entitiesLoading ? (
                <div className="text-gray-500">Loading entities...</div>
              ) : (
                <>
                  <div className="space-y-1 max-h-[60vh] overflow-y-auto">
                    {entities.map(e => (
                      <button key={e.id} onClick={() => { setSelectedEntity(e); loadEntityDocs(e.id); }}
                        className={`w-full text-left px-3 py-2.5 rounded-lg text-sm transition-colors flex items-center justify-between ${
                          selectedEntity?.id === e.id ? 'bg-blue-600/20 text-blue-400' : 'text-gray-300 hover:bg-gray-800'
                        }`}
                      >
                        <div className="flex items-center gap-2 min-w-0">
                          <Link to={`/admin/entities/${e.id}`} className="truncate text-blue-400 hover:underline">{e.name}</Link>
                          <span className="text-[10px] text-gray-600 capitalize flex-shrink-0">{e.entity_type}</span>
                        </div>
                        <ChevronRight size={14} className="text-gray-600 flex-shrink-0" />
                      </button>
                    ))}
                  </div>
                  {entities.length === 0 && <div className="text-gray-600 text-sm">No entities found</div>}
                  {entityTotalPages > 1 && (
                    <div className="flex items-center justify-center gap-2 pt-2">
                      <button onClick={() => { const p = Math.max(1, entityPage - 1); setEntityPage(p); loadEntities(p, activeTypeTag, entityNameFilter); }}
                        disabled={entityPage === 1} className="p-1.5 rounded bg-gray-800 text-gray-400 hover:bg-gray-700 disabled:opacity-50">
                        <ChevronLeft size={14} />
                      </button>
                      <span className="text-xs text-gray-500">{entityPage} / {entityTotalPages}</span>
                      <button onClick={() => { const p = entityPage + 1; setEntityPage(p); loadEntities(p, activeTypeTag, entityNameFilter); }}
                        disabled={entityPage >= entityTotalPages} className="p-1.5 rounded bg-gray-800 text-gray-400 hover:bg-gray-700 disabled:opacity-50">
                        <ChevronRight size={14} />
                      </button>
                    </div>
                  )}
                </>
              )}
            </div>

            <div className="lg:col-span-2">
              {selectedEntity ? (
                <div className="space-y-4">
                  <div className="bg-gray-900 border border-gray-800 rounded-xl p-4">
                    <div className="flex items-center gap-3 mb-2">
                      <span className="text-white font-medium text-lg">{selectedEntity.name}</span>
                      <Badge value={selectedEntity.entity_type} />
                    </div>
                    {Object.keys(selectedEntity.fields).length > 0 && (
                      <div className="flex flex-wrap gap-2 mt-2">
                        {Object.entries(selectedEntity.fields).map(([k, v]) => (
                          <span key={k} className="text-xs bg-gray-800 rounded px-2 py-1 text-gray-400">
                            <span className="text-gray-500">{k}:</span> {v}
                          </span>
                        ))}
                      </div>
                    )}
                  </div>
                  {entityDocsLoading ? (
                    <div className="text-gray-500">Loading documents...</div>
                  ) : (
                    <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
                      <table className="w-full text-sm">
                        <thead>
                          <tr className="border-b border-gray-800 text-gray-500 text-xs uppercase tracking-wider">
                            <th className="text-left px-4 py-3">Filename</th>
                            <th className="text-left px-4 py-3">Status</th>
                            <th className="text-left px-4 py-3">Classification</th>
                            <th className="text-left px-4 py-3">Confidence</th>
                            <th className="text-left px-4 py-3">Date</th>
                          </tr>
                        </thead>
                        <tbody>
                          {entityDocs.map(d => (
                            <tr key={d.id} className="border-b border-gray-800/50 hover:bg-gray-800/30">
                              <td className="px-4 py-3">
                                <Link to={`/documents/${d.id}`} className="text-blue-400 hover:underline">{d.filename}</Link>
                              </td>
                              <td className="px-4 py-3"><Badge value={d.status} /></td>
                              <td className="px-4 py-3 text-gray-400">{[d.classification_label, d.classification_subcategory_label].filter(Boolean).join(' / ') || '---'}</td>
                              <td className="px-4 py-3"><ConfidenceBadge value={d.pipeline_confidence} /></td>
                              <td className="px-4 py-3 text-gray-500 text-xs">{new Date(d.created_at).toLocaleString()}</td>
                            </tr>
                          ))}
                          {entityDocs.length === 0 && (
                            <tr><td colSpan={5} className="px-4 py-8 text-center text-gray-600">No documents linked to this entity</td></tr>
                          )}
                        </tbody>
                      </table>
                    </div>
                  )}
                </div>
              ) : (
                <div className="bg-gray-900 border border-gray-800 rounded-xl p-12 text-center text-gray-600">
                  Select an entity to view its documents
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {mode !== 'entities' && (
        <>
          <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-800 text-gray-500 text-xs uppercase tracking-wider">
                  <th className="text-left px-4 py-3">Filename</th>
                  {mode === 'content' && <th className="text-left px-4 py-3">Match</th>}
                  <th className="text-left px-4 py-3">Status</th>
                  <th className="text-left px-4 py-3">Classification</th>
                  <th className="text-left px-4 py-3">Confidence</th>
                  <th className="text-left px-4 py-3">Date</th>
                </tr>
              </thead>
              <tbody>
                {loading ? (
                  <tr><td colSpan={7} className="px-4 py-8 text-center text-gray-600">Loading...</td></tr>
                ) : mode === 'filters' ? (
                  docs.length === 0 ? (
                    <tr><td colSpan={7} className="px-4 py-8 text-center text-gray-600">No documents found</td></tr>
                  ) : docs.map(d => (
                    <tr key={d.id} className="border-b border-gray-800/50 hover:bg-gray-800/30">
                      <td className="px-4 py-3">
                        <Link to={`/documents/${d.id}`} className="text-blue-400 hover:underline">{d.filename}</Link>
                      </td>
                      <td className="px-4 py-3"><Badge value={d.status} /></td>
                      <td className="px-4 py-3 text-gray-400">{[d.classification_label, d.classification_subcategory_label].filter(Boolean).join(' / ') || '---'}</td>
                      <td className="px-4 py-3"><ConfidenceBadge value={d.pipeline_confidence} /></td>
                      <td className="px-4 py-3 text-gray-500 text-xs">{new Date(d.created_at).toLocaleString()}</td>
                    </tr>
                  ))
                ) : (
                  searchResults.length === 0 ? (
                    <tr><td colSpan={7} className="px-4 py-8 text-center text-gray-600">{contentQuery ? 'No results found' : 'Enter a search query'}</td></tr>
                  ) : searchResults.map((r, i) => (
                    <tr key={i} className="border-b border-gray-800/50 hover:bg-gray-800/30">
                      <td className="px-4 py-3">
                        <Link to={`/documents/${r.document_id}`} className="text-blue-400 hover:underline">{r.filename || r.document_id}</Link>
                      </td>
                      <td className="px-4 py-3">
                        <Badge value={r.match_type} />
                        <span className="ml-2 text-gray-500 text-xs truncate max-w-[200px] inline-block align-middle">{r.match_value}</span>
                      </td>
                      <td className="px-4 py-3">{r.status ? <Badge value={r.status} /> : '---'}</td>
                      <td className="px-4 py-3 text-gray-400">{r.classification_label || '---'}</td>
                      <td className="px-4 py-3 text-gray-600">---</td>
                      <td className="px-4 py-3" />
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>

          {total > 20 && (
            <div className="flex items-center justify-center gap-2">
              <button
                onClick={() => { const p = Math.max(1, page - 1); setPage(p); if (mode === 'content') loadContent(p); }}
                disabled={page === 1}
                className="px-3 py-1.5 rounded bg-gray-800 text-gray-400 text-sm hover:bg-gray-700 disabled:opacity-50"
              >Prev</button>
              <span className="text-sm text-gray-500">Page {page} of {Math.ceil(total / 20)}</span>
              <button
                onClick={() => { const p = page + 1; setPage(p); if (mode === 'content') loadContent(p); }}
                disabled={page * 20 >= total}
                className="px-3 py-1.5 rounded bg-gray-800 text-gray-400 text-sm hover:bg-gray-700 disabled:opacity-50"
              >Next</button>
            </div>
          )}
        </>
      )}
    </div>
  );
}
