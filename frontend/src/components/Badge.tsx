const COLORS: Record<string, string> = {
  open: 'bg-green-500/15 text-green-400 border-green-500/30',
  pending: 'bg-yellow-500/15 text-yellow-400 border-yellow-500/30',
  locked: 'bg-red-500/15 text-red-400 border-red-500/30',
  closed: 'bg-gray-500/15 text-gray-400 border-gray-500/30',
  COMPLETED: 'bg-green-500/15 text-green-400 border-green-500/30',
  INGESTED: 'bg-blue-500/15 text-blue-400 border-blue-500/30',
  admin: 'bg-purple-500/15 text-purple-400 border-purple-500/30',
  manager: 'bg-blue-500/15 text-blue-400 border-blue-500/30',
  user: 'bg-gray-500/15 text-gray-400 border-gray-500/30',
  auto: 'bg-cyan-500/15 text-cyan-400 border-cyan-500/30',
};

export default function Badge({ value, className = '' }: { value: string; className?: string }) {
  const color = COLORS[value] || 'bg-gray-500/15 text-gray-400 border-gray-500/30';
  return (
    <span className={`inline-flex items-center px-2 py-0.5 text-xs font-medium rounded-md border ${color} ${className}`}>
      {value}
    </span>
  );
}
