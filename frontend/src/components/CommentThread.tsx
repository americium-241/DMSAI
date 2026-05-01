import { useState } from 'react';
import { MessageSquare, Reply, Pencil, Trash2, Send, ChevronDown, ChevronRight } from 'lucide-react';
import type { DocumentCommentItem, EntityCommentItem } from '../api';
import { useAuth } from '../auth';

type AnyComment = DocumentCommentItem | EntityCommentItem;

interface Props {
  comments: AnyComment[];
  onAdd: (content: string, parentId?: string) => Promise<void>;
  onEdit: (commentId: string, content: string) => Promise<void>;
  onDelete: (commentId: string) => Promise<void>;
  loading?: boolean;
}

function timeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

function Avatar({ name }: { name: string | null }) {
  const initials = name ? name.split(' ').map(w => w[0]).join('').slice(0, 2).toUpperCase() : '?';
  return (
    <div className="w-7 h-7 rounded-full bg-blue-600/30 flex items-center justify-center text-blue-400 text-xs font-bold flex-shrink-0">
      {initials}
    </div>
  );
}

interface CommentItemProps {
  comment: AnyComment;
  replies: AnyComment[];
  depth: number;
  currentUserId?: string;
  currentUserRole?: string;
  onAdd: (content: string, parentId?: string) => Promise<void>;
  onEdit: (commentId: string, content: string) => Promise<void>;
  onDelete: (commentId: string) => Promise<void>;
}

function CommentItem({ comment, replies, depth, currentUserId, currentUserRole, onAdd, onEdit, onDelete }: CommentItemProps) {
  const [replying, setReplying] = useState(false);
  const [editing, setEditing] = useState(false);
  const [editText, setEditText] = useState(comment.content);
  const [replyText, setReplyText] = useState('');
  const [expanded, setExpanded] = useState(true);
  const [saving, setSaving] = useState(false);

  const canModify = currentUserId === comment.user_id || currentUserRole === 'admin' || currentUserRole === 'manager';

  const handleEdit = async () => {
    if (!editText.trim()) return;
    setSaving(true);
    try {
      await onEdit(comment.id, editText.trim());
      setEditing(false);
    } finally {
      setSaving(false);
    }
  };

  const handleReply = async () => {
    if (!replyText.trim()) return;
    setSaving(true);
    try {
      await onAdd(replyText.trim(), comment.id);
      setReplyText('');
      setReplying(false);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className={`${depth > 0 ? 'ml-8 border-l border-gray-800 pl-4' : ''}`}>
      <div className="flex gap-3 py-3">
        <Avatar name={comment.author_name} />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1">
            <span className="text-sm font-medium text-gray-200">{comment.author_name || 'Unknown'}</span>
            <span className="text-xs text-gray-600">{timeAgo(comment.created_at)}</span>
            {comment.updated_at && <span className="text-xs text-gray-700">(edited)</span>}
          </div>

          {editing ? (
            <div className="space-y-2">
              <textarea
                value={editText}
                onChange={e => setEditText(e.target.value)}
                rows={3}
                className="w-full px-3 py-2 rounded-lg bg-gray-800 border border-gray-700 text-white text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none"
              />
              <div className="flex gap-2">
                <button onClick={handleEdit} disabled={saving || !editText.trim()}
                  className="px-3 py-1.5 rounded bg-blue-600 text-white text-xs font-medium hover:bg-blue-500 disabled:opacity-50">
                  {saving ? 'Saving…' : 'Save'}
                </button>
                <button onClick={() => { setEditing(false); setEditText(comment.content); }}
                  className="px-3 py-1.5 rounded bg-gray-700 text-gray-300 text-xs hover:bg-gray-600">Cancel</button>
              </div>
            </div>
          ) : (
            <p className="text-sm text-gray-300 whitespace-pre-wrap">{comment.content}</p>
          )}

          {!editing && (
            <div className="flex items-center gap-3 mt-1.5">
              {depth < 3 && (
                <button onClick={() => setReplying(!replying)}
                  className="flex items-center gap-1 text-xs text-gray-600 hover:text-gray-400">
                  <Reply size={11} /> Reply
                </button>
              )}
              {canModify && (
                <>
                  <button onClick={() => setEditing(true)}
                    className="flex items-center gap-1 text-xs text-gray-600 hover:text-gray-400">
                    <Pencil size={11} /> Edit
                  </button>
                  <button onClick={() => onDelete(comment.id)}
                    className="flex items-center gap-1 text-xs text-gray-600 hover:text-red-400">
                    <Trash2 size={11} /> Delete
                  </button>
                </>
              )}
              {replies.length > 0 && (
                <button onClick={() => setExpanded(!expanded)}
                  className="flex items-center gap-1 text-xs text-gray-600 hover:text-gray-400 ml-auto">
                  {expanded ? <ChevronDown size={11} /> : <ChevronRight size={11} />}
                  {replies.length} {replies.length === 1 ? 'reply' : 'replies'}
                </button>
              )}
            </div>
          )}

          {replying && (
            <div className="mt-2 space-y-2">
              <textarea
                value={replyText}
                onChange={e => setReplyText(e.target.value)}
                placeholder="Write a reply…"
                rows={2}
                className="w-full px-3 py-2 rounded-lg bg-gray-800 border border-gray-700 text-white text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none"
              />
              <div className="flex gap-2">
                <button onClick={handleReply} disabled={saving || !replyText.trim()}
                  className="flex items-center gap-1 px-3 py-1.5 rounded bg-blue-600 text-white text-xs font-medium hover:bg-blue-500 disabled:opacity-50">
                  <Send size={11} /> {saving ? 'Sending…' : 'Reply'}
                </button>
                <button onClick={() => { setReplying(false); setReplyText(''); }}
                  className="px-3 py-1.5 rounded bg-gray-700 text-gray-300 text-xs hover:bg-gray-600">Cancel</button>
              </div>
            </div>
          )}
        </div>
      </div>

      {expanded && replies.map(r => (
        <CommentItem key={r.id} comment={r} replies={[]} depth={depth + 1}
          currentUserId={currentUserId} currentUserRole={currentUserRole}
          onAdd={onAdd} onEdit={onEdit} onDelete={onDelete} />
      ))}
    </div>
  );
}

export default function CommentThread({ comments, onAdd, onEdit, onDelete, loading }: Props) {
  const { user } = useAuth();
  const [newComment, setNewComment] = useState('');
  const [submitting, setSubmitting] = useState(false);

  const topLevel = comments.filter(c => !c.parent_id);
  const byParent = comments.reduce<Record<string, AnyComment[]>>((acc, c) => {
    if (c.parent_id) {
      acc[c.parent_id] = acc[c.parent_id] ?? [];
      acc[c.parent_id].push(c);
    }
    return acc;
  }, {});

  const handlePost = async () => {
    if (!newComment.trim()) return;
    setSubmitting(true);
    try {
      await onAdd(newComment.trim());
      setNewComment('');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2 mb-2">
        <MessageSquare size={14} className="text-gray-500" />
        <span className="text-xs font-semibold text-gray-500 uppercase tracking-wider">
          {comments.length} {comments.length === 1 ? 'note' : 'notes'}
        </span>
      </div>

      {loading ? (
        <div className="text-sm text-gray-600">Loading notes…</div>
      ) : topLevel.length === 0 && !loading ? (
        <div className="text-sm text-gray-700">No notes yet. Be the first to leave one.</div>
      ) : (
        <div className="divide-y divide-gray-800/50">
          {topLevel.map(c => (
            <CommentItem key={c.id} comment={c} replies={byParent[c.id] ?? []}
              depth={0} currentUserId={user?.id} currentUserRole={user?.role}
              onAdd={onAdd} onEdit={onEdit} onDelete={onDelete} />
          ))}
        </div>
      )}

      <div className="flex gap-3 pt-2 border-t border-gray-800">
        <Avatar name={user?.full_name ?? null} />
        <div className="flex-1 space-y-2">
          <textarea
            value={newComment}
            onChange={e => setNewComment(e.target.value)}
            placeholder="Add a note…"
            rows={2}
            className="w-full px-3 py-2 rounded-lg bg-gray-800 border border-gray-700 text-white text-sm placeholder-gray-600 focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none"
          />
          <button onClick={handlePost} disabled={submitting || !newComment.trim()}
            className="flex items-center gap-1.5 px-4 py-1.5 rounded-lg bg-blue-600 text-white text-sm font-medium hover:bg-blue-500 disabled:opacity-50 transition-colors">
            <Send size={13} /> {submitting ? 'Posting…' : 'Post'}
          </button>
        </div>
      </div>
    </div>
  );
}
