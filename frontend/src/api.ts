const BASE = '/api';

function getToken(): string | null {
  return localStorage.getItem('dmsai_token');
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const headers: Record<string, string> = {};
  const token = getToken();
  if (token) headers['Authorization'] = `Bearer ${token}`;

  if (options?.headers) {
    const h = options.headers as Record<string, string>;
    Object.assign(headers, h);
  }

  const res = await fetch(`${BASE}${path}`, { ...options, headers });
  if (res.status === 401) {
    localStorage.removeItem('dmsai_token');
    localStorage.removeItem('dmsai_user');
    window.location.href = '/login';
    throw new Error('Unauthorized');
  }
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || res.statusText);
  }
  return res.json();
}

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface OrgMembership {
  organization_id: string;
  organization_name: string;
  role: string;
  is_default: boolean;
}

export interface OrgMember {
  membership_id: string;
  user_id: string;
  email: string;
  full_name: string;
  role: string;
  is_default: boolean;
  joined_at: string;
  is_active: boolean;
}

export interface IngestionConfig {
  id: string;
  name: string;
  source_type: 'directory' | 'email';
  config: Record<string, string>;
  is_active: boolean;
  created_at: string;
}

export interface IngestionConfigCreate {
  name: string;
  source_type: 'directory' | 'email';
  config: Record<string, string>;
  is_active?: boolean;
}

export interface UserInfo {
  id: string;
  email: string;
  full_name: string;
  role: string;
  organization_id: string;
  organization_name: string | null;
  is_active?: boolean;
  email_verified?: boolean;
  auth_provider?: string;
  organizations?: OrgMembership[];
}

export interface AuthResponse {
  access_token?: string;
  token_type?: string;
  status?: string;
  message?: string;
  user: UserInfo;
}

export interface AuthProviders {
  local: boolean;
  ldap: boolean;
  registration_open: boolean;
  email_verification: boolean;
}

export interface DocumentSummary {
  id: string;
  filename: string;
  original_extension: string;
  source: string;
  mode: string;
  status: string;
  pdf_url: string | null;
  file_size_bytes: number | null;
  page_count: number | null;
  ocr_confidence: number | null;
  ocr_method: string | null;
  classification_label: string | null;
  classification_subcategory_label: string | null;
  classification_path: string[] | null;
  classification_confidence: number | null;
  classification_method: string | null;
  cluster_id: number | null;
  pipeline_confidence: number | null;
  confidence_details: Record<string, unknown> | null;
  created_at: string;
  updated_at: string | null;
  processed_at: string | null;
  archived_at: string | null;
  trashed_at: string | null;
  compressed_at: string | null;
}

export interface DocumentDetail extends DocumentSummary {
  ocr_text: string | null;
}

export interface PagedDocuments {
  total: number;
  page: number;
  page_size: number;
  documents: DocumentSummary[];
}

export interface DocField {
  id: string;
  field_name: string;
  field_value: string | null;
  confidence: number;
  confidence_details?: Record<string, unknown> | null;
  extraction_method: string;
}

export interface DocEntity {
  link_id: string;
  entity_id: string;
  name: string;
  canonical_name: string | null;
  entity_type: string;
  role: string;
  confidence: number;
  confidence_details?: Record<string, unknown> | null;
  fields: Record<string, string>;
}

export interface EntityFieldItem {
  id: string;
  field_name: string;
  field_value: string;
  confidence: number;
  confidence_details?: Record<string, unknown> | null;
}

export interface CanonicalFieldItem {
  id: string;
  scope: string;
  canonical_name: string;
  description: string;
  document_class: string | null;
  aliases: string[];
  created_at: string;
}

export interface CanonicalDocumentClassItem {
  id: string;
  parent_id: string | null;
  canonical_name: string;
  description: string;
  aliases: string[];
  created_at: string;
  updated_at: string | null;
}

// ------- Comments -------
export interface DocumentCommentItem {
  id: string;
  document_id: string;
  user_id: string;
  author_name: string | null;
  content: string;
  parent_id: string | null;
  created_at: string;
  updated_at: string | null;
}

export interface EntityCommentItem {
  id: string;
  entity_id: string;
  user_id: string;
  author_name: string | null;
  content: string;
  parent_id: string | null;
  created_at: string;
  updated_at: string | null;
}

// ------- Audit / Versions -------
export interface AuditLogEntry {
  id: string;
  action: string;
  user_id: string | null;
  author_name: string | null;
  entity_id: string | null;
  details: string | null;
  created_at: string;
}

export interface DocumentVersionItem {
  id: string;
  version_number: number;
  created_by: string | null;
  author_name: string | null;
  created_at: string;
  summary: string;
}

export interface DocumentVersionDetail extends DocumentVersionItem {
  snapshot: Record<string, unknown> | null;
}

// ------- Archive -------
export interface ArchivedDocumentSummary {
  id: string;
  filename: string;
  status: string;
  classification_label: string | null;
  archived_at: string | null;
  trashed_at: string | null;
  compressed_at: string | null;
  created_at: string;
}

export interface ArchiveListResponse {
  total: number;
  documents: ArchivedDocumentSummary[];
}

export interface CompactResult {
  status: string;
  compressed: string[];
  already_done: string[];
  skipped: string[];
}

export interface PurgeTrashResult {
  status: string;
  trash_retention_days: number;
  candidates: { id: string; filename: string; trashed_at: string }[];
}

export interface RetentionSettings {
  global_archive_retention_days: number;
  global_trash_retention_days: number;
  org_archive_retention_days: number | null;
  org_trash_retention_days: number | null;
  effective_archive_retention_days: number;
  effective_trash_retention_days: number;
}

export interface SystemConfigItem {
  key: string;
  value: string;
  category: string;
  description: string;
  updated_at: string;
}

export interface BucketSummary {
  id: string;
  name: string;
  description: string | null;
  created_at: string;
  states: Record<string, number>;
  total: number;
  rules?: RuleItem[];
}

export interface BucketDocItem {
  id: string;
  document_id: string;
  workflow_state: string;
  locked_by: string | null;
  locked_by_name: string | null;
  locked_at: string | null;
  filename: string | null;
  classification_label: string | null;
  classification_subcategory_label: string | null;
  classification_path: string | null;
  status: string | null;
  created_at: string | null;
  company_name: string | null;
  client_name: string | null;
}

export interface WorkflowState {
  workflow_state: string | null;
  locked_by: string | null;
  locked_by_name: string | null;
}

export interface PagedBucketDocs {
  total: number;
  page: number;
  page_size: number;
  documents: BucketDocItem[];
}

export interface RuleItem {
  id: string;
  field: string;
  operator: string;
  value: string;
}

export interface PermissionItem {
  id: string;
  user_id: string;
  user_name: string | null;
  user_email: string | null;
  permission: string;
}

export interface SearchResult {
  document_id: string;
  filename: string | null;
  match_type: string;
  match_value: string | null;
  snippet: string | null;
  classification_label: string | null;
  classification_subcategory_label: string | null;
  status: string | null;
  pipeline_confidence: number | null;
  created_at: string | null;
}

export interface PagedSearch {
  total: number;
  page: number;
  page_size: number;
  results: SearchResult[];
}

export type SearchScope = 'filename' | 'content' | 'fields' | 'entities';

export interface DailyCount { date: string; count: number; }
export interface AuditFeedItem {
  id: string;
  document_id: string;
  filename: string | null;
  action: string;
  details: string | null;
  actor: string | null;
  created_at: string;
}

export interface Dashboard {
  total_documents: number;
  processing_documents: number;
  today_documents: number;
  week_documents: number;
  closed_documents: number;
  pending_documents: number;
  my_locked_documents: number;
  // Charts
  daily_counts: DailyCount[];
  status_breakdown: { completed: number; processing: number; failed: number };
  confidence_buckets: { low: number; medium: number; good: number; high: number };
  top_classifications: { label: string; count: number }[];
  top_entities: { id: string; name: string; entity_type: string; doc_count: number }[];
  // Lists
  bucket_summaries: BucketSummary[];
  recent_audit: AuditFeedItem[];
  recent_documents: {
    id: string; filename: string; status: string;
    classification_label: string | null; classification_subcategory_label: string | null;
    pipeline_confidence: number | null; created_at: string;
  }[];
  // Legacy (kept for backwards compat)
  classification_distribution: Record<string, number>;
  classification_subcategory_distribution: Record<string, number>;
}

export interface EntityItem {
  id: string;
  name: string;
  canonical_name: string | null;
  entity_type: string;
  created_at: string;
  fields: Record<string, string>;
  key_fields: Record<string, string>;
  doc_count: number;
}

export interface NodeHealth {
  status: string;
  node?: string;
  queue?: { pending: number; processing: number; dead_letter: number };
}

export interface QualityMetrics {
  total_documents: number;
  total_corrections: number;
  corrections_by_type: Record<string, number>;
  correction_rate: number;
  avg_pipeline_confidence: number | null;
  weekly_confidence: { week: string | null; avg_pipeline_confidence: number | null }[];
  confidence_distribution: Record<string, number>;
  most_corrected_fields: { field_name: string | null; count: number }[];
  classification_changes: { from: string | null; to: string | null; count: number }[];
  recent_corrections: {
    id: string;
    document_id: string;
    entity_id: string | null;
    field_type: string;
    field_name: string | null;
    original_value: string | null;
    corrected_value: string | null;
    corrected_by_name: string;
    created_at: string;
  }[];
}

export interface PipelineEventItem {
  id: string;
  document_id: string;
  stage: string;
  event_type: string;
  timestamp: string;
  details: string | null;
}

export interface ActivityItem {
  id: string;
  document_id: string;
  filename: string | null;
  stage: string;
  event_type: string;
  timestamp: string;
  details: string | null;
}

export interface EntityRelationshipItem {
  entity_id: string;
  name: string;
  entity_type: string;
  shared_document_count: number;
  shared_documents: { id: string; filename: string | null }[];
}

export interface EntityDossierResponse {
  entity: {
    id: string;
    name: string;
    canonical_name: string | null;
    entity_type: string;
    created_at: string;
  };
  fields: { id: string; field_name: string; field_value: string; confidence: number }[];
  documents: {
    document_id: string;
    filename: string;
    status: string | null;
    classification_label: string | null;
    pipeline_confidence: number | null;
    role: string;
    link_confidence: number;
    created_at: string;
  }[];
  timeline: { document_id: string; filename: string; role: string; at: string }[];
}

export interface DocumentBucketItem {
  bucket_document_id: string;
  bucket_id: string;
  bucket_name: string;
  workflow_state: string;
  locked_by: string | null;
  created_at: string;
}

export interface RelatedDocument {
  document_id: string;
  filename: string;
  classification_label: string | null;
  classification_subcategory_label: string | null;
  status: string;
  created_at: string;
  shared_entity_count: number;
  shared_entities: { entity_id: string; name: string; entity_type: string }[];
}

export interface RelatedDocumentsResponse {
  document_id: string;
  related: RelatedDocument[];
}

// ---------------------------------------------------------------------------
// API client
// ---------------------------------------------------------------------------

export const api = {
  // Auth
  login(email: string, password: string) {
    return request<AuthResponse>('/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password }),
    });
  },
  register(email: string, password: string, full_name: string, organization_name?: string) {
    return request<AuthResponse>('/auth/register', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password, full_name, organization_name }),
    });
  },
  getMe() {
    return request<UserInfo>('/auth/me');
  },
  listMyOrganizations() {
    return request<OrgMembership[]>('/auth/organizations');
  },
  switchOrg(org_id: string) {
    return request<AuthResponse>('/auth/switch-org', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ org_id }),
    });
  },
  getAuthProviders() {
    return request<AuthProviders>('/auth/providers');
  },
  resendVerification(email: string) {
    return request<{ status: string; message: string }>('/auth/resend-verification', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email }),
    });
  },

  // Users
  getUsers() {
    return request<UserInfo[]>('/users');
  },
  updateUser(id: string, data: { full_name?: string; role?: string; is_active?: boolean }) {
    return request<{ status: string }>(`/users/${id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
  },

  // Organization
  getOrganization() {
    return request<{ id: string; name: string; created_at: string }>('/organization');
  },
  updateOrganization(name: string) {
    return request<{ status: string; name: string }>('/organization', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name }),
    });
  },

  // Documents
  getDocuments(params?: Record<string, string>) {
    const qs = params ? '?' + new URLSearchParams(params).toString() : '';
    return request<PagedDocuments>(`/documents${qs}`);
  },
  getDocument(id: string) {
    return request<DocumentDetail>(`/documents/${id}`);
  },
  getDocumentPdfUrl(id: string) {
    return `${BASE}/documents/${id}/pdf`;
  },
  getDocumentFields(id: string) {
    return request<DocField[]>(`/documents/${id}/fields`);
  },
  getDocumentEntities(id: string) {
    return request<DocEntity[]>(`/documents/${id}/entities`);
  },
  resolveDocumentEntity(docId: string, linkId: string, targetEntityId: string) {
    return request<{ status: string; link_id: string; entity_id: string }>(`/documents/${docId}/entities/${linkId}/resolve`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ target_entity_id: targetEntityId }),
    });
  },
  updateDocument(id: string, data: { classification_label?: string; classification_subcategory_label?: string }) {
    return request<{ status: string }>(`/documents/${id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
  },
  updateField(docId: string, fieldId: string, data: { field_value?: string; field_name?: string }) {
    return request<{ status: string }>(`/documents/${docId}/fields/${fieldId}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
  },
  createField(docId: string, field_name: string, field_value?: string) {
    return request<{ id: string }>(`/documents/${docId}/fields`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ field_name, field_value }),
    });
  },
  deleteField(docId: string, fieldId: string) {
    return request<{ status: string }>(`/documents/${docId}/fields/${fieldId}`, { method: 'DELETE' });
  },

  // Upload
  async uploadFile(file: File, priority = 0, mode = 'auto') {
    const form = new FormData();
    form.append('file', file);
    form.append('priority', String(priority));
    form.append('mode', mode);
    return request<{ status: string; document_id: string }>('/upload', {
      method: 'POST',
      body: form,
    });
  },

  // Search
  search(q: string, opts: { scope?: string; status?: string; classification?: string; page?: number; page_size?: number } = {}) {
    const params = new URLSearchParams({ q });
    if (opts.scope) params.set('scope', opts.scope);
    if (opts.status) params.set('status', opts.status);
    if (opts.classification) params.set('classification', opts.classification);
    if (opts.page) params.set('page', String(opts.page));
    if (opts.page_size) params.set('page_size', String(opts.page_size));
    return request<PagedSearch>(`/search?${params.toString()}`);
  },

  // Document workflow
  autoLockDocument(docId: string) {
    return request<{ status: string; locked_count: number }>(`/documents/${docId}/auto-lock`, { method: 'POST' });
  },
  autoUnlockDocument(docId: string) {
    return request<{ status: string; unlocked_count: number }>(`/documents/${docId}/auto-unlock`, { method: 'POST' });
  },
  toggleDocumentState(docId: string) {
    return request<{ status: string; new_state: string }>(`/documents/${docId}/toggle-state`, { method: 'POST' });
  },
  getWorkflowState(docId: string) {
    return request<WorkflowState>(`/documents/${docId}/workflow-state`);
  },

  // Dashboard
  getDashboard(dateFrom?: string, dateTo?: string) {
    const params = new URLSearchParams();
    if (dateFrom) params.set('date_from', dateFrom);
    if (dateTo) params.set('date_to', dateTo);
    const qs = params.toString() ? `?${params.toString()}` : '';
    return request<Dashboard>(`/dashboard${qs}`);
  },

  // Buckets
  getBuckets() {
    return request<BucketSummary[]>('/buckets');
  },
  getBucket(id: string) {
    return request<BucketSummary>(`/buckets/${id}`);
  },
  createBucket(name: string, description?: string) {
    return request<{ id: string; name: string }>('/buckets', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, description }),
    });
  },
  updateBucket(id: string, data: { name?: string; description?: string }) {
    return request<{ status: string }>(`/buckets/${id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
  },
  deleteBucket(id: string) {
    return request<{ status: string }>(`/buckets/${id}`, { method: 'DELETE' });
  },
  getBucketDocuments(bucketId: string, params?: Record<string, string>) {
    const qs = params ? '?' + new URLSearchParams(params).toString() : '';
    return request<PagedBucketDocs>(`/buckets/${bucketId}/documents${qs}`);
  },

  // Bucket state/lock
  changeDocState(bucketId: string, docId: string, state: string) {
    return request<{ status: string }>(`/buckets/${bucketId}/documents/${docId}/state`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ workflow_state: state }),
    });
  },
  lockDoc(bucketId: string, docId: string) {
    return request<{ status: string }>(`/buckets/${bucketId}/documents/${docId}/lock`, { method: 'POST' });
  },
  unlockDoc(bucketId: string, docId: string) {
    return request<{ status: string }>(`/buckets/${bucketId}/documents/${docId}/unlock`, { method: 'POST' });
  },

  // Bucket rules
  getBucketRules(bucketId: string) {
    return request<RuleItem[]>(`/buckets/${bucketId}/rules`);
  },
  createBucketRule(bucketId: string, field: string, operator: string, value: string) {
    return request<RuleItem>(`/buckets/${bucketId}/rules`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ field, operator, value }),
    });
  },
  deleteBucketRule(bucketId: string, ruleId: string) {
    return request<{ status: string }>(`/buckets/${bucketId}/rules/${ruleId}`, { method: 'DELETE' });
  },

  // Bucket permissions
  getBucketPermissions(bucketId: string) {
    return request<PermissionItem[]>(`/buckets/${bucketId}/permissions`);
  },
  createBucketPermission(bucketId: string, userId: string, permission: string) {
    return request<{ id: string }>(`/buckets/${bucketId}/permissions`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ user_id: userId, permission }),
    });
  },
  deleteBucketPermission(bucketId: string, permId: string) {
    return request<{ status: string }>(`/buckets/${bucketId}/permissions/${permId}`, { method: 'DELETE' });
  },

  // Auto-assign
  assignDocuments() {
    return request<{ status: string; count: number }>('/buckets/assign', { method: 'POST' });
  },

  // Admin
  getEntityTypes() {
    return request<string[]>('/admin/entities/types');
  },
  getEntities(params?: Record<string, string>) {
    const qs = params ? '?' + new URLSearchParams(params).toString() : '';
    return request<{ items: EntityItem[]; total: number; page: number; page_size: number }>(`/admin/entities${qs}`);
  },
  getEntity(id: string) {
    return request<EntityItem>(`/admin/entities/${id}`);
  },
  getCanonicalDocumentClasses() {
    return request<CanonicalDocumentClassItem[]>('/admin/canonical-document-classes');
  },
  createCanonicalDocumentClass(data: { canonical_name: string; description?: string; aliases?: string[]; parent_id?: string | null }) {
    return request<{ id: string; canonical_name: string }>('/admin/canonical-document-classes', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
  },
  getCanonicalFields(scope?: string) {
    const qs = scope ? `?scope=${encodeURIComponent(scope)}` : '';
    return request<CanonicalFieldItem[]>(`/admin/canonical-fields${qs}`);
  },
  // Entity fields
  getEntityDetail(id: string) {
    return request<{ id: string; name: string; canonical_name: string | null; entity_type: string; created_at: string; fields: EntityFieldItem[] }>(`/admin/entities/${id}`);
  },
  updateEntityField(entityId: string, fieldId: string, data: { field_value?: string; field_name?: string }) {
    return request<{ status: string }>(`/entities/${entityId}/fields/${fieldId}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
  },
  createEntityField(entityId: string, field_name: string, field_value: string) {
    return request<{ id: string }>(`/entities/${entityId}/fields`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ field_name, field_value }),
    });
  },
  deleteEntityField(entityId: string, fieldId: string) {
    return request<{ status: string }>(`/entities/${entityId}/fields/${fieldId}`, { method: 'DELETE' });
  },

  // System Config
  getSystemConfig(category?: string) {
    const qs = category ? `?category=${encodeURIComponent(category)}` : '';
    return request<SystemConfigItem[]>(`/admin/system-config${qs}`);
  },
  updateSystemConfig(key: string, value: string) {
    return request<{ status: string }>(`/admin/system-config/${key}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ value }),
    });
  },
  restartServices(services: string[]) {
    return request<{ status: string; services: string[] }>('/admin/services/restart', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ services }),
    });
  },

  // Admin — Organizations (list + create)
  adminListOrganizations() {
    return request<{ id: string; name: string; created_at: string }[]>('/admin/organizations');
  },
  adminCreateOrganization(name: string) {
    return request<{ status: string; id: string; name: string }>('/admin/organizations', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name }),
    });
  },

  // Pipeline
  getPipelineHealth() {
    return request<Record<string, NodeHealth>>('/pipeline/health');
  },

  getQualityMetrics() {
    return request<QualityMetrics>('/admin/quality-metrics');
  },

  getEntityRelationships(entityId: string) {
    return request<{ items: EntityRelationshipItem[] }>(`/admin/entities/${entityId}/relationships`);
  },

  getEntityDossier(entityId: string) {
    return request<EntityDossierResponse>(`/admin/entities/${entityId}/dossier`);
  },

  mergeEntities(sourceId: string, targetId: string) {
    return request<{ status: string; target_id: string }>('/admin/entities/merge', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ source_id: sourceId, target_id: targetId }),
    });
  },

  getDocumentEvents(documentId: string) {
    return request<{ events: PipelineEventItem[] }>(`/documents/${documentId}/events`);
  },

  getRecentActivity(limit = 30) {
    return request<{ items: ActivityItem[] }>(`/activity/recent?limit=${limit}`);
  },
  getActivity(params?: { page?: number; page_size?: number; action?: string; document_id?: string }) {
    const p = new URLSearchParams();
    if (params?.page) p.set('page', String(params.page));
    if (params?.page_size) p.set('page_size', String(params.page_size));
    if (params?.action) p.set('action', params.action);
    if (params?.document_id) p.set('document_id', params.document_id);
    return request<{ total: number; page: number; page_size: number; items: AuditFeedItem[]; action_types: string[] }>(
      `/activity?${p.toString()}`
    );
  },

  // Document buckets (manual assignment)
  getDocumentBuckets(docId: string) {
    return request<DocumentBucketItem[]>(`/documents/${docId}/buckets`);
  },
  addDocumentToBucket(docId: string, bucketId: string) {
    return request<DocumentBucketItem & { status: string }>(`/documents/${docId}/buckets`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ bucket_id: bucketId }),
    });
  },
  removeDocumentFromBucket(docId: string, bucketDocumentId: string) {
    return request<{ status: string }>(`/documents/${docId}/buckets/${bucketDocumentId}`, { method: 'DELETE' });
  },

  // Document relations
  getRelatedDocuments(docId: string, limit = 20) {
    return request<RelatedDocumentsResponse>(`/documents/${docId}/related?limit=${limit}`);
  },

  // ---- Comments ----
  getDocumentComments(docId: string) {
    return request<DocumentCommentItem[]>(`/documents/${docId}/comments`);
  },
  createDocumentComment(docId: string, content: string, parentId?: string) {
    return request<{ id: string; status: string }>(`/documents/${docId}/comments`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content, parent_id: parentId ?? null }),
    });
  },
  updateDocumentComment(docId: string, commentId: string, content: string) {
    return request<{ status: string }>(`/documents/${docId}/comments/${commentId}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content }),
    });
  },
  deleteDocumentComment(docId: string, commentId: string) {
    return request<{ status: string }>(`/documents/${docId}/comments/${commentId}`, { method: 'DELETE' });
  },
  getEntityComments(entityId: string) {
    return request<EntityCommentItem[]>(`/entities/${entityId}/comments`);
  },
  createEntityComment(entityId: string, content: string, parentId?: string) {
    return request<{ id: string; status: string }>(`/entities/${entityId}/comments`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content, parent_id: parentId ?? null }),
    });
  },
  updateEntityComment(entityId: string, commentId: string, content: string) {
    return request<{ status: string }>(`/entities/${entityId}/comments/${commentId}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content }),
    });
  },
  deleteEntityComment(entityId: string, commentId: string) {
    return request<{ status: string }>(`/entities/${entityId}/comments/${commentId}`, { method: 'DELETE' });
  },

  // ---- Archive / Trash ----
  archiveDocument(docId: string) {
    return request<{ status: string; archived_at?: string }>(`/documents/${docId}/archive`, { method: 'POST' });
  },
  unarchiveDocument(docId: string) {
    return request<{ status: string }>(`/documents/${docId}/unarchive`, { method: 'POST' });
  },
  trashDocument(docId: string) {
    return request<{ status: string; trashed_at?: string }>(`/documents/${docId}/trash`, { method: 'POST' });
  },
  restoreDocument(docId: string) {
    return request<{ status: string }>(`/documents/${docId}/restore`, { method: 'POST' });
  },
  permanentDeleteDocument(docId: string) {
    return request<{ status: string }>(`/documents/${docId}/permanent`, { method: 'DELETE' });
  },
  getArchivedDocuments(status: 'archived' | 'trashed' = 'archived', page = 1) {
    return request<ArchiveListResponse>(`/admin/archive?status=${status}&page=${page}`);
  },
  compactStorage() {
    return request<CompactResult>('/admin/storage/compact', { method: 'POST' });
  },
  purgeTrashCandidates() {
    return request<PurgeTrashResult>('/admin/storage/purge-trash', { method: 'POST' });
  },
  getRetentionSettings() {
    return request<RetentionSettings>('/admin/archive/retention');
  },
  updateRetentionSettings(data: { archive_retention_days?: number | null; trash_retention_days?: number | null }) {
    return request<RetentionSettings & { status: string }>('/admin/archive/retention', {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
  },

  // ---- Versions ----
  getDocumentVersions(docId: string) {
    return request<DocumentVersionItem[]>(`/documents/${docId}/versions`);
  },
  getDocumentVersion(docId: string, versionId: string) {
    return request<DocumentVersionDetail>(`/documents/${docId}/versions/${versionId}`);
  },

  // ---- Audit Log ----
  getDocumentAuditLog(docId: string, limit = 100) {
    return request<AuditLogEntry[]>(`/documents/${docId}/audit-log?limit=${limit}`);
  },

  // ---- Org membership management (admin) ----
  adminListOrgMembers(orgId: string) {
    return request<OrgMember[]>(`/admin/organizations/${orgId}/members`);
  },
  adminAddOrgMember(orgId: string, user_id: string, role: string) {
    return request<{ status: string }>(`/admin/organizations/${orgId}/members`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ user_id, role }),
    });
  },
  adminUpdateOrgMember(orgId: string, userId: string, role: string) {
    return request<{ status: string }>(`/admin/organizations/${orgId}/members/${userId}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ role }),
    });
  },
  adminRemoveOrgMember(orgId: string, userId: string) {
    return request<{ status: string }>(`/admin/organizations/${orgId}/members/${userId}`, {
      method: 'DELETE',
    });
  },

  // ---- Org ingestion config (admin) ----
  adminListIngestionConfigs(orgId: string) {
    return request<IngestionConfig[]>(`/admin/organizations/${orgId}/ingestion`);
  },
  adminCreateIngestionConfig(orgId: string, data: IngestionConfigCreate) {
    return request<IngestionConfig>(`/admin/organizations/${orgId}/ingestion`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
  },
  adminUpdateIngestionConfig(orgId: string, configId: string, data: Partial<IngestionConfigCreate>) {
    return request<{ status: string }>(`/admin/organizations/${orgId}/ingestion/${configId}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
  },
  adminDeleteIngestionConfig(orgId: string, configId: string) {
    return request<{ status: string }>(`/admin/organizations/${orgId}/ingestion/${configId}`, {
      method: 'DELETE',
    });
  },
};
