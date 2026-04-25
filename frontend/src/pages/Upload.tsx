import { useState, useRef } from 'react';
import { Upload as UploadIcon, CheckCircle, AlertCircle, FileUp } from 'lucide-react';
import { api } from '../api';
import { useToast } from '../components/Toast';

export default function UploadPage() {
  const { show } = useToast();
  const [files, setFiles] = useState<File[]>([]);
  const [results, setResults] = useState<{ name: string; ok: boolean; id?: string; error?: string }[]>([]);
  const [uploading, setUploading] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setFiles(prev => [...prev, ...Array.from(e.dataTransfer.files)]);
  };

  const handleUpload = async () => {
    if (files.length === 0) return;
    setUploading(true);
    setResults([]);
    const rs: typeof results = [];
    for (const file of files) {
      try {
        const r = await api.uploadFile(file, 0, 'auto');
        rs.push({ name: file.name, ok: true, id: r.document_id });
      } catch (err: unknown) {
        rs.push({ name: file.name, ok: false, error: err instanceof Error ? err.message : 'Upload failed' });
      }
    }
    setResults(rs);
    setFiles([]);
    setUploading(false);
    const okN = rs.filter((r) => r.ok).length;
    const failN = rs.length - okN;
    if (failN === 0) show(`Uploaded ${okN} file(s)`, 'success');
    else if (okN === 0) show(`${failN} upload(s) failed`, 'error');
    else show(`${okN} ok, ${failN} failed`, 'info');
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-white">Upload Documents</h1>
        <p className="text-sm text-gray-500 mt-1">Upload documents for AI processing</p>
      </div>

      <div className="bg-gray-900 border border-gray-800 rounded-xl p-6 space-y-6">
        <div
          onDrop={handleDrop}
          onDragOver={e => e.preventDefault()}
          onClick={() => inputRef.current?.click()}
          className="border-2 border-dashed border-gray-700 rounded-xl p-12 text-center cursor-pointer hover:border-gray-600 transition-colors"
        >
          <FileUp size={40} className="mx-auto text-gray-600 mb-4" />
          <p className="text-gray-400">Drop files here or click to browse</p>
          <p className="text-xs text-gray-600 mt-1">PDF, PNG, JPEG, TIFF, DOC, DOCX supported</p>
          <input ref={inputRef} type="file" multiple className="hidden" onChange={e => { if (e.target.files) setFiles(prev => [...prev, ...Array.from(e.target.files!)]); }} />
        </div>

        {files.length > 0 && (
          <div className="space-y-2">
            <div className="text-sm text-gray-400">{files.length} file{files.length > 1 ? 's' : ''} selected</div>
            {files.map((f, i) => (
              <div key={i} className="flex items-center justify-between bg-gray-800/50 rounded-lg px-4 py-2">
                <span className="text-sm text-gray-300">{f.name}</span>
                <button onClick={() => setFiles(files.filter((_, j) => j !== i))} className="text-gray-500 hover:text-red-400 text-xs">Remove</button>
              </div>
            ))}
          </div>
        )}

        <button
          onClick={handleUpload} disabled={files.length === 0 || uploading}
          className="flex items-center justify-center gap-2 w-full py-3 rounded-lg bg-blue-600 text-white font-medium hover:bg-blue-500 disabled:opacity-50 transition-colors"
        >
          <UploadIcon size={18} />
          {uploading ? 'Uploading...' : `Upload ${files.length} File${files.length !== 1 ? 's' : ''}`}
        </button>
      </div>

      {results.length > 0 && (
        <div className="space-y-2">
          {results.map((r, i) => (
            <div key={i} className={`flex items-center gap-3 px-4 py-3 rounded-lg border ${r.ok ? 'bg-green-500/5 border-green-500/20' : 'bg-red-500/5 border-red-500/20'}`}>
              {r.ok ? <CheckCircle size={16} className="text-green-400" /> : <AlertCircle size={16} className="text-red-400" />}
              <span className="text-sm text-gray-300">{r.name}</span>
              {r.ok && <span className="text-xs text-gray-500 ml-auto">ID: {r.id}</span>}
              {r.error && <span className="text-xs text-red-400 ml-auto">{r.error}</span>}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
