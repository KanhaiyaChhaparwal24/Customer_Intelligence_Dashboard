export function Skeleton({ className = '', rows = 1 }) {
  return (
    <div className={`animate-pulse ${className}`}>
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="h-4 bg-border rounded-lg mb-2 last:mb-0" />
      ))}
    </div>
  )
}

export function CardSkeleton() {
  return (
    <div className="glass-card p-5 animate-pulse">
      <div className="h-3 bg-border rounded w-24 mb-3" />
      <div className="h-8 bg-border rounded w-16 mb-2" />
      <div className="h-3 bg-border rounded w-20" />
    </div>
  )
}

export function TableSkeleton({ rows = 8, cols = 5 }) {
  return (
    <div className="animate-pulse">
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="flex gap-4 px-4 py-3 border-b border-border/50">
          {Array.from({ length: cols }).map((_, j) => (
            <div key={j} className="h-4 bg-border rounded flex-1" />
          ))}
        </div>
      ))}
    </div>
  )
}
