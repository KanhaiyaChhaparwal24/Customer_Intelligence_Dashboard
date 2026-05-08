import { TrendingUp, TrendingDown, Minus } from 'lucide-react'
import { CardSkeleton } from '../ui/Skeleton'

export function KpiCard({ label, value, sub, color = 'text-white', icon: Icon, trend, loading }) {
  if (loading) return <CardSkeleton />

  const TrendIcon = trend > 0 ? TrendingUp : trend < 0 ? TrendingDown : Minus
  const trendColor = trend > 0 ? 'text-emerald-400' : trend < 0 ? 'text-red-400' : 'text-muted'

  return (
    <div className="kpi-card group">
      <div className="flex items-start justify-between mb-3">
        <p className="text-xs font-semibold uppercase tracking-wider text-muted">{label}</p>
        {Icon && (
          <span className="w-8 h-8 rounded-lg flex items-center justify-center bg-surface border border-border group-hover:border-converted/40 transition-colors">
            <Icon size={15} className="text-muted group-hover:text-converted transition-colors" />
          </span>
        )}
      </div>
      <p className={`text-3xl font-bold tracking-tight ${color} mb-1`}>{value ?? '—'}</p>
      <div className="flex items-center gap-2">
        {sub && <p className="text-xs text-muted">{sub}</p>}
        {trend !== undefined && (
          <span className={`flex items-center gap-0.5 text-xs ${trendColor}`}>
            <TrendIcon size={11} />
            {Math.abs(trend)}%
          </span>
        )}
      </div>
    </div>
  )
}

export function StatusCard({ label, value, color, icon: Icon }) {
  return (
    <div className="flex items-center gap-3 px-4 py-3 rounded-xl bg-surface border border-border">
      {Icon && <Icon size={16} className={color} />}
      <div>
        <p className="text-xs text-muted">{label}</p>
        <p className={`text-sm font-bold ${color}`}>{value ?? '—'}</p>
      </div>
    </div>
  )
}
