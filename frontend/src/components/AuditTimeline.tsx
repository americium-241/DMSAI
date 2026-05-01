import { useState } from 'react';
import { Clock, ChevronDown, ChevronRight, GitCommit, User, Building2, Tag, FileText, Archive, Trash2, RotateCcw, MessageSquare, Pencil, Plus, Minus, GitMerge, Layers } from 'lucide-react';
import type { AuditLogEntry, DocumentVersionItem, DocumentVersionDetail } from '../api';

const ACTION_META: Record<string, { label: string; icon: React.ElementType; color: string }> = {
  field_edited:         { label: 'Field edited',           icon: Pencil,       color: 'text-blue-400' },
  field_added:          { label: 'Field added',            icon: Plus,         color: 'text-green-400' },
  field_deleted:        { label: 'Field deleted',          icon: Minus,        color: 'text-red-400' },
  entity_resolved:      { label: 'Entity reassigned',      icon: GitMerge,     color: 'text-amber-400' },
  entity_field_edited:  { label: 'Entity field edited',    icon: Pencil,       color: 'text-blue-400' },
  entity_field_added:   { label: 'Entity field added',     icon: Plus,         color: 'text-green-400' },
  entity_field_deleted: { label: 'Entity field deleted',   icon: Minus,        color: 'text-red-400' },
  classification_edited:{ label: 'Classification changed', icon: Tag,          color: 'text-purple-400' },
  comment_added:        { label: 'Note added',             icon: MessageSquare,color: 'text-gray-400' },
  comment_edited:       { label: 'Note edited',            icon: MessageSquare,color: 'text-gray-400' },
  comment_deleted:      { label: 'Note deleted',           icon: MessageSquare,color: 'text-gray-500' },
  archived:             { label: 'Archived',               icon: Archive,      color: 'text-yellow-400' },
  unarchived:           { label: 'Unarchived',             icon: RotateCcw,    color: 'text-green-400' },
  trashed:              { label: 'Moved to trash',         icon: Trash2,       color: 'text-red-400' },
  restored_from_trash:  { label: 'Restored from trash',   icon: RotateCcw,    color: 'text-green-400' },
  compressed:           { label: 'File compressed',        icon: Layers,       color: 'text-cyan-400' },
};

function timeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const d = Math.floor(hrs / 24);
  return `${d}d ago`;
}

interface AuditTimelineProps {
  entries: AuditLogEntry[];
  versions: DocumentVersionItem[];
  onLoadVersion?: (versionId: string) => Promise<DocumentVersionDetail>;
  loading?: boolean;
}

function VersionCard({
  version, onLoad,
}: {
  version: DocumentVersionItem;
  onLoad?: (id: string) => Promise<DocumentVersionDetail>;
}) {
  const [detail, setDetail] = useState<DocumentVersionDetail | null>(null);
  const [expanded, setExpanded] = useState(false);
  const [loading, setLoading] = useState(false);

  const toggle = async () => {
    if (!expanded && !detail && onLoad) {
      setLoading(true);
      try { setDetail(await onLoad(version.id)); } finally { setLoading(false); }
    }
    setExpanded(!expanded);
  };

  return (
    <div className="border border-gray-800 rounded-lg overflow-hidden">
      <button onClick={toggle}
        className="w-full flex items-center gap-3 px-4 py-3 text-left hover:bg-gray-800/40 transition-colors">
        <GitCommit size={14} className="text-cyan-400 flex-shrink-0" />
        <div className="flex-1 min-w-0">
          <span className="text-sm text-gray-200 font-medium">v{version.version_number}</span>
          <span className="mx-2 text-gray-600">·</span>
          <span className="text-xs text-gray-400">{version.summary}</span>
        </div>
        <div className="flex items-center gap-3 flex-shrink-0">
          <span className="text-xs text-gray-600">{version.author_name || 'system'}</span>
          <span className="text-xs text-gray-700">{timeAgo(version.created_at)}</span>
          {expanded ? <ChevronDown size={14} className="text-gray-600" /> : <ChevronRight size={14} className="text-gray-600" />}
        </div>
      </button>

      {expanded && (
        <div className="border-t border-gray-800 bg-gray-900/50 px-4 py-3">
          {loading && <div className="text-sm text-gray-600">Loading snapshot…</div>}
          {detail?.snapshot && (
            <div className="space-y-3 text-sm">
              <div className="flex flex-wrap gap-3">
                <div>
                  <span className="text-gray-600 text-xs">Classification</span>
                  <p className="text-gray-300">{detail.snapshot.classification_label as string || '—'}</p>
                </div>
                <div>
                  <span className="text-gray-600 text-xs">Status</span>
                  <p className="text-gray-300">{detail.snapshot.status as string || '—'}</p>
                </div>
                <div>
                  <span className="text-gray-600 text-xs">Confidence</span>
                  <p className="text-gray-300">
                    {detail.snapshot.pipeline_confidence != null
                      ? `${((detail.snapshot.pipeline_confidence as number) * 100).toFixed(0)}%`
                      : '—'}
                  </p>
                </div>
              </div>
              {Boolean(detail.snapshot.fields) && Object.keys(detail.snapshot.fields as Record<string, string>).length > 0 && (
                <div>
                  <span className="text-gray-600 text-xs block mb-1">Fields snapshot</span>
                  <div className="flex flex-wrap gap-1.5">
                    {Object.entries(detail.snapshot.fields as Record<string, string>).map(([k, v]) => (
                      <span key={k} className="text-xs bg-gray-800 rounded px-2 py-0.5 text-gray-400">
                        <span className="text-gray-600">{k}:</span> {String(v)}
                      </span>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default function AuditTimeline({ entries, versions, onLoadVersion, loading }: AuditTimelineProps) {
  const [tab, setTab] = useState<'log' | 'versions'>('log');

  return (
    <div className="space-y-4">
      <div className="flex gap-1 border-b border-gray-800">
        {([
          { key: 'log' as const, label: 'Activity log', icon: Clock },
          { key: 'versions' as const, label: `Versions (${versions.length})`, icon: GitCommit },
        ]).map(t => (
          <button key={t.key} onClick={() => setTab(t.key)}
            className={`flex items-center gap-1.5 px-3 py-2 text-xs font-medium border-b-2 transition-colors ${
              tab === t.key ? 'border-blue-500 text-blue-400' : 'border-transparent text-gray-500 hover:text-gray-300'
            }`}>
            <t.icon size={12} />{t.label}
          </button>
        ))}
      </div>

      {tab === 'log' && (
        <div>
          {loading ? (
            <div className="text-sm text-gray-600">Loading log…</div>
          ) : entries.length === 0 ? (
            <div className="text-sm text-gray-700">No activity recorded yet.</div>
          ) : (
            <div className="relative">
              <div className="absolute left-[18px] top-0 bottom-0 w-px bg-gray-800" />
              <div className="space-y-0">
                {entries.map(e => {
                  const meta = ACTION_META[e.action] ?? { label: e.action, icon: FileText, color: 'text-gray-400' };
                  const Icon = meta.icon;
                  return (
                    <div key={e.id} className="flex gap-3 items-start py-2.5 relative">
                      <div className="w-9 h-9 rounded-full bg-gray-900 border border-gray-800 flex items-center justify-center flex-shrink-0 z-10">
                        <Icon size={13} className={meta.color} />
                      </div>
                      <div className="flex-1 min-w-0 pt-0.5">
                        <div className="flex items-center gap-2 flex-wrap">
                          <span className="text-sm text-gray-200">{meta.label}</span>
                          {e.author_name && (
                            <span className="text-xs text-gray-500 flex items-center gap-1">
                              <User size={10} /> {e.author_name}
                            </span>
                          )}
                          {e.entity_id && (
                            <span className="text-xs text-gray-500 flex items-center gap-1">
                              <Building2 size={10} /> entity
                            </span>
                          )}
                          <span className="text-xs text-gray-700 ml-auto">{timeAgo(e.created_at)}</span>
                        </div>
                        {e.details && (
                          <p className="text-xs text-gray-500 mt-0.5 truncate max-w-md" title={e.details}>{e.details}</p>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}
        </div>
      )}

      {tab === 'versions' && (
        <div className="space-y-2">
          {versions.length === 0 ? (
            <div className="text-sm text-gray-700">No versions saved yet.</div>
          ) : (
            versions.map(v => (
              <VersionCard key={v.id} version={v} onLoad={onLoadVersion} />
            ))
          )}
        </div>
      )}
    </div>
  );
}
