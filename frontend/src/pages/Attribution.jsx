import { useApi } from '../hooks/useApi'
import { getAttributionInsights } from '../utils/api'
import { KpiCard } from '../components/cards/KpiCard'
import { CardSkeleton } from '../components/ui/Skeleton'
import { PieChart, Pie, Cell, Tooltip, ResponsiveContainer, BarChart, Bar, XAxis, YAxis, LineChart, Line } from 'recharts'
import { ListFilter, Target, Clock, Zap, TrendingUp, AlertCircle } from 'lucide-react'
import { fmtPercent, fmtNumber } from '../utils/formatters'

const COLORS = ['#8b5cf6', '#3b82f6', '#f97316', '#10b981', '#64748b', '#ef4444', '#14b8a6']

export default function Attribution() {
  const { data, loading } = useApi(getAttributionInsights)

  if (loading) {
    return <div className="p-6"><CardSkeleton /></div>
  }

  const D = data || {}
  const sourceData = D.source_breakdown || []
  const confData = D.confidence_distribution || []
  const detectionMethods = D.detection_methods || []
  const sourceConversionMetrics = D.source_conversion_metrics || []

  return (
    <div className="p-6 space-y-6 animate-slide-up">
      <div className="flex items-center gap-2 mb-2">
        <ListFilter className="text-purple-400" size={20} />
        <h1 className="text-lg font-bold text-white">Attribution Intelligence</h1>
      </div>

      {/* ── Key Metrics Grid ──────────────────────────────────────────── */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <KpiCard loading={false} label="Avg Days to Conversion" value={D.avg_days_to_conversion || '0'} icon={Clock} color="text-blue-400" />
        <KpiCard loading={false} label="Mkt→D2C Conversion Rate" value={fmtPercent(D.marketplace_to_d2c_rate)} icon={TrendingUp} color="text-emerald-400" />
        <KpiCard loading={false} label="Tracked Sources" value={sourceData.length} icon={Target} color="text-purple-400" />
        <KpiCard loading={false} label="High Confidence (>90%)" value={confData.find(c => c.range === '0.9-1.0')?.count || 0} icon={Zap} color="text-emerald-400" />
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <KpiCard loading={false} label="Heuristic Attribution" value={fmtNumber(D.heuristic_attribution_count || D.date_inferred_attribution_count)} icon={Clock} color="text-yellow-400" />
        <KpiCard loading={false} label="OCR Failed" value={fmtNumber(D.ocr_failed_count)} icon={AlertCircle} color="text-red-400" />
        <KpiCard loading={false} label="Unknown Attribution" value={fmtNumber(D.unknown_attribution_count)} icon={AlertCircle} color="text-slate-400" />
        <KpiCard loading={false} label="Avg Source Confidence" value={fmtPercent(D.avg_source_confidence)} icon={Zap} color="text-blue-400" />
      </div>

      {/* ── Charts Row 1 ────────────────────────────────────────────────── */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* Source Breakdown Pie */}
        <div className="glass-card p-5">
          <h3 className="text-sm font-semibold text-slate-300 mb-6">Source Breakdown</h3>
          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie
                  data={sourceData}
                  innerRadius={60}
                  outerRadius={80}
                  paddingAngle={5}
                  dataKey="count"
                  nameKey="source"
                >
                  {sourceData.map((entry, index) => (
                    <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
                  ))}
                </Pie>
                <Tooltip
                  contentStyle={{ backgroundColor: '#1e293b', border: 'none', borderRadius: '8px' }}
                  itemStyle={{ color: '#fff' }}
                />
              </PieChart>
            </ResponsiveContainer>
          </div>
          <div className="flex flex-wrap gap-4 mt-4 justify-center">
            {sourceData.map((entry, index) => (
              <div key={entry.source} className="flex items-center gap-2 text-xs text-muted">
                <div className="w-2 h-2 rounded-full" style={{ backgroundColor: COLORS[index % COLORS.length] }} />
                {entry.source}: {entry.count}
              </div>
            ))}
          </div>
        </div>

        {/* Confidence Distribution Bar */}
        <div className="glass-card p-5">
          <h3 className="text-sm font-semibold text-slate-300 mb-6">OCR Confidence Distribution</h3>
          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={confData}>
                <XAxis dataKey="range" stroke="#475569" fontSize={12} tickLine={false} axisLine={false} />
                <YAxis stroke="#475569" fontSize={12} tickLine={false} axisLine={false} />
                <Tooltip
                  cursor={{ fill: '#334155' }}
                  contentStyle={{ backgroundColor: '#1e293b', border: 'none', borderRadius: '8px' }}
                />
                <Bar dataKey="count" fill="#8b5cf6" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>

      {/* ── Detection Methods ──────────────────────────────────────────── */}
      <div className="glass-card p-5">
        <h3 className="text-sm font-semibold text-slate-300 mb-4">Attribution Methods Used</h3>
        <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
          {detectionMethods.map((method) => (
            <div key={method.method} className="px-3 py-2 rounded-lg bg-surface border border-border">
              <p className="text-xs text-muted mb-1">{method.method}</p>
              <p className="text-lg font-bold text-white">{fmtNumber(method.count)}</p>
            </div>
          ))}
        </div>
      </div>

      {/* ── Source-wise Conversion Metrics ────────────────────────────── */}
      <div className="glass-card p-5">
        <h3 className="text-sm font-semibold text-slate-300 mb-4">Source-wise Conversion Metrics</h3>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border">
                <th className="px-4 py-2 text-left text-muted">Source</th>
                <th className="px-4 py-2 text-right text-muted">Total Marketplace</th>
                <th className="px-4 py-2 text-right text-muted">Converted</th>
                <th className="px-4 py-2 text-right text-muted">Unconverted</th>
                <th className="px-4 py-2 text-right text-muted">Conv. Rate</th>
              </tr>
            </thead>
            <tbody>
              {sourceConversionMetrics.map((metric) => (
                <tr key={metric.source} className="border-b border-border hover:bg-surface">
                  <td className="px-4 py-2 font-medium text-white">{metric.source}</td>
                  <td className="px-4 py-2 text-right text-slate-300">{metric.total_marketplace}</td>
                  <td className="px-4 py-2 text-right text-emerald-400 font-semibold">{metric.converted}</td>
                  <td className="px-4 py-2 text-right text-slate-300">{metric.unconverted}</td>
                  <td className="px-4 py-2 text-right text-emerald-400 font-semibold">{metric.conversion_rate}%</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
