import { useEffect, useState, useCallback, useRef } from 'react';
import { Link } from 'react-router-dom';
import {
  Search, X, ChevronLeft, ChevronRight, Building2, User, MapPin,
  FileText, ExternalLink, ChevronDown, ChevronUp,
} from 'lucide-react';
import { api, type EntityItem, type DocumentSummary } from '../api';
import Badge from '../components/Badge';
import { useAuth } from '../auth';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const TYPE_ICONS: Record<string, React.ReactNode> = {
  company:  <Building2 size={14} />,
  person:   <User size={14} />,
  address:  <MapPin size={14} />,
};

function typeIcon(t: string) {
  return TYPE_ICONS[t.toLowerCase()] ?? <FileText size={14} />;
}

function ConfidenceBar({ value }: { value: number | null | undefined }) {
  if (value == null) return null;
  const pct = Math.round(value * 100);
  const color = value >= 0.7 ? 'bg-green-500' : value >= 0.5 ? 'bg-yellow-500' : 'bg-red-500';
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 w-16 rounded-full bg-gray-800 overflow-hidden">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs tabular-nums text-gray-500">{pct}%</span>
    </div>
  );
}

const IDENTIFIER_KEYS = ['tax_id', 'siret', 'siren', 'vat_number', 'registration_number', 'email', 'phone'];

const PAGE_SIZE = 40;

// ---------------------------------------------------------------------------
// Entity row — expandable
// ---------------------------------------------------------------------------

function EntityRow({
  entity,
  isAdmin,
  expanded,
  onToggle,
}: {
  entity: EntityItem;
  isAdmin: boolean;
  expanded: boolean;
  onToggle: () => void;
}) {
  const [docs, setDocs]       = useState<DocumentSummary[]>([]);
  const [docsLoaded, setDocsLoaded] = useState(false);
  const [docsLoading, setDocsLoading] = useState(false);

  const loadDocs = useCallback(async () => {
    if (docsLoaded) return;
    setDocsLoading(true);
    try {
      const res = await api.getDocuments({ entity_id: entity.id, page_size: '50' });
      setDocs(res.documents);
      setDocsLoaded(true);
    } finally {
      setDocsLoading(false);
    }
  }, [entity.id, docsLoaded]);

  const handleToggle = () => {
    if (!expanded) loadDocs();
    onToggle();
  };

  const keyFields = entity.key_fields && Object.keys(entity.key_fields).length > 0
    ? entity.key_fields
    : Object.fromEntries(
        Object.entries(entity.fields)
          .filter(([k]) => IDENTIFIER_KEYS.includes(k.toLowerCase()))
          .slice(0, 3)
      );

  return (
    <>
      <tr
        onClick={handleToggle}
        className={`border-b border-gray-800/50 hover:bg-gray-800/30 transition-colors cursor-pointer select-none ${
          expanded ? 'bg-gray-800/20' : ''
        }`}
      >
        {/* Name */}
        <td className="px-4 py-3">
          <div className="flex items-center gap-2.5">
            <span className="text-gray-500 flex-shrink-0">{typeIcon(entity.entity_type)}</span>
            <div className="min-w-0">
              <div className="font-medium text-white truncate max-w-[220px]">{entity.name}</div>
              {entity.canonical_name && entity.canonical_name !== entity.name && (
                <div className="text-[11px] text-gray-500 truncate">
                  aka {entity.canonical_name}
                </div>
              )}
            </div>
          </div>
        </td>

        {/* Type */}
        <td className="px-4 py-3">
          <Badge value={entity.entity_type} />
        </td>

        {/* Key identifiers */}
        <td className="px-4 py-3 max-w-xs">
          {Object.keys(keyFields).length > 0 ? (
            <div className="flex flex-wrap gap-1">
              {Object.entries(keyFields).slice(0, 3).map(([k, v]) => (
                <span key={k} className="text-[10px] bg-gray-800 rounded px-1.5 py-0.5 text-gray-400">
                  <span className="text-gray-600">{k}:</span> {String(v)}
                </span>
              ))}
            </div>
          ) : (
            <span className="text-gray-600 text-xs">—</span>
          )}
        </td>

        {/* Doc count */}
        <td className="px-4 py-3 text-gray-400 text-sm tabular-nums">
          {entity.doc_count ?? 0}
        </td>

        {/* Actions */}
        <td className="px-4 py-3">
          <div className="flex items-center gap-2 justify-end">
            {isAdmin && (
              <Link
                to={`/admin/entities/${entity.id}`}
                onClick={e => e.stopPropagation()}
                className="text-blue-400 hover:text-blue-300 flex items-center gap-1 text-xs"
              >
                <ExternalLink size={12} /> Edit
              </Link>
            )}
            <span className="text-gray-600">
              {expanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
            </span>
          </div>
        </td>
      </tr>

      {/* Expanded panel */}
      {expanded && (
        <tr className="border-b border-gray-800">
          <td colSpan={5} className="px-4 pb-4 pt-2 bg-gray-900/60">
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
              {/* All fields */}
              {Object.keys(entity.fields).length > 0 && (
                <div>
                  <p className="text-[10px] uppercase tracking-wider text-gray-600 mb-2">Fields</p>
                  <div className="flex flex-wrap gap-1.5">
                    {Object.entries(entity.fields).map(([k, v]) => (
                      <span key={k} className="text-xs bg-gray-800 border border-gray-700 rounded px-2 py-1 text-gray-300">
                        <span className="text-gray-500">{k}:</span> {String(v)}
                      </span>
                    ))}
                  </div>
                </div>
              )}

              {/* Linked documents */}
              <div>
                <p className="text-[10px] uppercase tracking-wider text-gray-600 mb-2">
                  Linked documents
                  {docsLoaded && <span className="ml-1 text-gray-500">({docs.length})</span>}
                </p>
                {docsLoading ? (
                  <p className="text-xs text-gray-600">Loading…</p>
                ) : docs.length === 0 ? (
                  <p className="text-xs text-gray-600">None</p>
                ) : (
                  <div className="space-y-1 max-h-40 overflow-y-auto">
                    {docs.map(d => (
                      <Link
                        key={d.id}
                        to={`/documents/${d.id}`}
                        onClick={e => e.stopPropagation()}
                        className="flex items-center gap-2 text-xs text-blue-400 hover:underline group"
                      >
                        <FileText size={11} className="text-gray-600 flex-shrink-0" />
                        <span className="truncate">{d.filename}</span>
                        <span className="text-gray-600 flex-shrink-0">
                          {d.classification_label || '—'}
                        </span>
                      </Link>
                    ))}
                  </div>
                )}
              </div>
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function EntityDirectoryPage() {
  const { user } = useAuth();
  const isAdmin = user?.role === 'admin' || user?.role === 'org_admin' || user?.role === 'manager';

  const [entities, setEntities]     = useState<EntityItem[]>([]);
  const [total, setTotal]           = useState(0);
  const [loading, setLoading]       = useState(false);
  const [page, setPage]             = useState(1);
  const [entityTypes, setEntityTypes] = useState<string[]>([]);
  const [activeType, setActiveType] = useState('');
  const [searchQ, setSearchQ]       = useState('');
  const [activeQ, setActiveQ]       = useState('');
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const loadTypes = async () => {
    try {
      const types = await api.getEntityTypes();
      setEntityTypes(types);
    } catch {}
  };

  const loadEntities = useCallback(async (p = 1, type = activeType, q = activeQ) => {
    setLoading(true);
    try {
      const params: Record<string, string> = { page: String(p), page_size: String(PAGE_SIZE) };
      if (type) params.entity_type = type;
      if (q.trim()) params.search = q.trim();
      const res = await api.getEntities(params);
      setEntities(res.items);
      setTotal(res.total);
    } finally {
      setLoading(false);
    }
  }, [activeType, activeQ]);

  useEffect(() => {
    loadTypes();
    loadEntities(1, '', '');
  }, []);

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    setPage(1);
    setExpandedId(null);
    setActiveQ(searchQ);
    loadEntities(1, activeType, searchQ);
  };

  const clearSearch = () => {
    setSearchQ('');
    setActiveQ('');
    setPage(1);
    setExpandedId(null);
    loadEntities(1, activeType, '');
    inputRef.current?.focus();
  };

  const selectType = (t: string) => {
    setActiveType(t);
    setPage(1);
    setExpandedId(null);
    loadEntities(1, t, activeQ);
  };

  const goPage = (p: number) => {
    setPage(p);
    setExpandedId(null);
    loadEntities(p, activeType, activeQ);
  };

  const totalPages = Math.ceil(total / PAGE_SIZE);

  return (
    <div className="space-y-5">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">Entities</h1>
          <p className="text-sm text-gray-500 mt-0.5">
            {loading ? 'Loading…' : `${total.toLocaleString()} entit${total !== 1 ? 'ies' : 'y'}${activeQ ? ` matching "${activeQ}"` : ''}`}
          </p>
        </div>
      </div>

      {/* Search + type filters */}
      <div className="flex flex-wrap items-center gap-3">
        <form onSubmit={handleSearch} className="relative flex-1 min-w-[200px] max-w-sm">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-500 pointer-events-none" />
          <input
            ref={inputRef}
            value={searchQ}
            onChange={e => setSearchQ(e.target.value)}
            placeholder="Search by name, identifier…"
            className="w-full pl-9 pr-8 py-2 rounded-xl bg-gray-900 border border-gray-700 text-white text-sm placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-blue-500 transition"
          />
          {searchQ && (
            <button type="button" onClick={clearSearch}
              className="absolute right-2.5 top-1/2 -translate-y-1/2 text-gray-500 hover:text-gray-300">
              <X size={13} />
            </button>
          )}
        </form>

        {/* Type pills */}
        <div className="flex flex-wrap gap-1.5">
          <button
            onClick={() => selectType('')}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium border transition-colors ${
              activeType === ''
                ? 'bg-blue-600/20 border-blue-500/40 text-blue-300'
                : 'bg-gray-900 border-gray-700 text-gray-500 hover:text-gray-300'
            }`}
          >
            All
          </button>
          {entityTypes.map(t => (
            <button key={t}
              onClick={() => selectType(t)}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium border capitalize transition-colors ${
                activeType === t
                  ? 'bg-blue-600/20 border-blue-500/40 text-blue-300'
                  : 'bg-gray-900 border-gray-700 text-gray-500 hover:text-gray-300'
              }`}
            >
              {typeIcon(t)}
              {t}
            </button>
          ))}
        </div>
      </div>

      {/* Table */}
      <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-gray-800 text-gray-500 text-xs uppercase tracking-wider">
              <th className="text-left px-4 py-3">Name</th>
              <th className="text-left px-4 py-3">Type</th>
              <th className="text-left px-4 py-3">Key identifiers</th>
              <th className="text-left px-4 py-3">Docs</th>
              <th className="px-4 py-3" />
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr>
                <td colSpan={5} className="px-4 py-10 text-center text-gray-600">Loading…</td>
              </tr>
            ) : entities.length === 0 ? (
              <tr>
                <td colSpan={5} className="px-4 py-10 text-center text-gray-600">
                  {activeQ ? `No entities matching "${activeQ}"` : 'No entities found'}
                </td>
              </tr>
            ) : entities.map(e => (
              <EntityRow
                key={e.id}
                entity={e}
                isAdmin={isAdmin}
                expanded={expandedId === e.id}
                onToggle={() => setExpandedId(prev => prev === e.id ? null : e.id)}
              />
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
