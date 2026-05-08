import { ChevronLeft, ChevronRight } from 'lucide-react'

export function DataTable({ columns, data, emptyMessage = 'No data found' }) {
  if (!data || data.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-16 text-muted">
        <div className="text-4xl mb-3">📭</div>
        <p className="text-sm">{emptyMessage}</p>
      </div>
    )
  }

  return (
    <div className="overflow-x-auto">
      <table className="data-table">
        <thead>
          <tr>
            {columns.map((col) => (
              <th key={col.key} style={{ minWidth: col.width || 'auto' }}>{col.label}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {data.map((row, i) => (
            <tr key={i} className="group animate-fade-in">
              {columns.map((col) => (
                <td key={col.key}>
                  {col.render ? col.render(row[col.key], row) : (row[col.key] ?? '—')}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export function Pagination({ page, totalPages, onPage, total, perPage }) {
  if (totalPages <= 1) return null
  const start = (page - 1) * perPage + 1
  const end   = Math.min(page * perPage, total)

  return (
    <div className="flex items-center justify-between px-4 py-3 border-t border-border">
      <p className="text-xs text-muted">
        Showing {start}–{end} of {total} results
      </p>
      <div className="flex items-center gap-2">
        <button
          onClick={() => onPage(page - 1)} disabled={page === 1}
          className="w-8 h-8 flex items-center justify-center rounded-lg border border-border text-muted hover:text-white hover:border-slate-500 disabled:opacity-30 disabled:cursor-not-allowed transition-all"
        >
          <ChevronLeft size={14} />
        </button>
        <span className="text-xs text-slate-300 px-2">
          {page} / {totalPages}
        </span>
        <button
          onClick={() => onPage(page + 1)} disabled={page === totalPages}
          className="w-8 h-8 flex items-center justify-center rounded-lg border border-border text-muted hover:text-white hover:border-slate-500 disabled:opacity-30 disabled:cursor-not-allowed transition-all"
        >
          <ChevronRight size={14} />
        </button>
      </div>
    </div>
  )
}
