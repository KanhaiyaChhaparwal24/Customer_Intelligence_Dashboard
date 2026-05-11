import { useApi } from '../hooks/useApi'
import { usePolling } from '../hooks/useApi'
import { getKpis, getProducts, getCities, getRevenue, getSizes, getColours, getPayments, getOcrMetrics } from '../utils/api'
import { KpiCard } from '../components/cards/KpiCard'
import { CardSkeleton } from '../components/ui/Skeleton'
import {
  SegmentDonut, RegistrationsChart, RevenueChart,
  TopProducts, TopCities, SizeTrends, ColourTrends, PaymentMethods
} from '../components/charts/Charts'
import {
  Users, ShoppingBag, Store, Zap, TrendingUp,
  DollarSign, RotateCcw, Clock, AlertCircle, CheckCircle,
  Cpu, Copy, Activity, RefreshCw, FileX, Sparkles
} from 'lucide-react'
import { fmtCurrency, fmtPercent, fmtNumber, fmtDate, fmtDuration } from '../utils/formatters'

export default function Overview({ onRefresh }) {
  const { data: kpis, loading: kLoading, reload } = usePolling(getKpis, 30000)
  const { data: ocrMetrics, loading: ocrLoading } = usePolling(getOcrMetrics, 30000)
  const { data: products } = useApi(getProducts)
  const { data: cities }   = useApi(getCities)
  const { data: revenue }  = useApi(getRevenue)
  const { data: sizes }    = useApi(getSizes)
  const { data: colours }  = useApi(getColours)
  const { data: payments } = useApi(getPayments)

  const K = kpis || {}
  const OCR = ocrMetrics || {}

  return (
    <div className="p-6 space-y-6 animate-slide-up">
      {/* ── Main KPI Grid ──────────────────────────────────────────────── */}
      <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-5 gap-4">
        <KpiCard loading={kLoading} label="Marketplace Buyers" value={fmtNumber(K.marketplace_buyers)}   icon={ShoppingBag} color="text-blue-400" />
        <KpiCard loading={kLoading} label="Direct D2C"         value={fmtNumber(K.direct_d2c_customers)} icon={Store}       color="text-orange-400" />
        <KpiCard loading={kLoading} label="Converted"          value={fmtNumber(K.converted_customers)}  icon={Zap}         color="text-purple-400" />
        <KpiCard loading={kLoading} label="Heuristic Attribution" value={fmtNumber(K.heuristic_attribution_count || K.probable_d2c_count)} icon={Store} color="text-emerald-300" />
        <KpiCard loading={kLoading} label="Unknown Source"     value={fmtNumber(K.unknown_attribution_count)} icon={AlertCircle} color="text-slate-400" />
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <KpiCard loading={kLoading} label="Mkt→D2C Rate"       value={fmtPercent(K.marketplace_to_d2c_rate)}  icon={TrendingUp}  color="text-emerald-400" />
        <KpiCard loading={kLoading} label="Total D2C Revenue"  value={fmtCurrency(K.total_d2c_revenue)} icon={DollarSign} color="text-emerald-400" />
        <KpiCard loading={kLoading} label="Avg Order Value"    value={fmtCurrency(K.avg_order_value)} icon={DollarSign}  color="text-emerald-300" />
        <KpiCard loading={kLoading} label="Repeat Customers"   value={fmtNumber(K.repeat_customers)}  icon={RotateCcw}   color="text-purple-300" />
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <KpiCard loading={kLoading} label="Avg Source Confidence" value={fmtPercent(K.avg_source_confidence * 100)} icon={CheckCircle} color="text-blue-400" />
        <KpiCard loading={kLoading} label="OCR Failed %" value={fmtPercent(K.ocr_failed_percentage)} icon={AlertCircle} color="text-red-400" />
        <KpiCard loading={kLoading} label="Date-Inferred %" value={fmtPercent(K.date_inferred_attribution_percentage)} icon={Clock} color="text-yellow-400" />
        <KpiCard loading={kLoading} label="Unknown Attribution %" value={fmtPercent(K.unknown_attribution_percentage)} icon={AlertCircle} color="text-slate-400" />
      </div>

      {/* ── Live Processing Status ───────────────────────────────────────── */}
      <div className="glass-card p-5">
        <h3 className="text-sm font-semibold text-slate-300 mb-4 flex items-center gap-2">
          <Cpu size={15} className="text-converted" />
          Live Processing Status
        </h3>
        <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-7 gap-3">
          {[
            { label: 'Processed Today',   value: K.processed_today,      icon: CheckCircle, color: 'text-emerald-400' },
            { label: 'Pending OCRs',      value: K.pending_ocr,          icon: Clock,       color: 'text-yellow-400'  },
            { label: 'Failed OCRs',       value: K.failed_ocr,           icon: AlertCircle, color: 'text-red-400'     },
            { label: 'Duplicate Invoices',value: K.duplicate_invoices,   icon: Copy,        color: 'text-orange-400'  },
            { label: 'Gemini Calls Today',value: K.gemini_calls_today,   icon: Cpu,         color: 'text-purple-400'  },
            { label: 'Last Sync',         value: fmtDate(K.last_sync_time), icon: Clock,    color: 'text-slate-400'   },
            { label: 'Sync Duration',     value: fmtDuration(K.last_sync_duration), icon: Clock, color: 'text-slate-400' },
          ].map(({ label, value, icon: Icon, color }) => (
            kLoading ? <CardSkeleton key={label} /> :
            <div key={label} className="flex items-center gap-3 px-3 py-2.5 rounded-xl bg-surface border border-border">
              <Icon size={15} className={color} />
              <div>
                <p className="text-[10px] text-muted leading-tight">{label}</p>
                <p className={`text-sm font-bold ${color}`}>{value ?? '—'}</p>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* ── OCR Orchestrator Health ─────────────────────────────────────── */}
      <div className="glass-card p-5 border-blue-900/30">
        <h3 className="text-sm font-semibold text-blue-300 mb-4 flex items-center gap-2">
          <Activity size={15} />
          OCR Orchestrator Health
        </h3>
        <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-8 gap-3">
          {[
            { label: 'Gemini Success',    value: OCR.gemini_success,        icon: CheckCircle, color: 'text-purple-400' },
            { label: 'Gemini Failed',     value: OCR.gemini_failed,         icon: FileX,       color: 'text-red-400' },
            { label: 'Retry Pending',     value: OCR.retry_pending,         icon: RefreshCw,   color: 'text-yellow-400' },
            { label: 'OCR Skipped',       value: OCR.ocr_skipped,           icon: Sparkles,    color: 'text-slate-300' },
            { label: 'Heuristic Attribution', value: OCR.heuristic_attribution, icon: Zap, color: 'text-emerald-400' },
            { label: 'Unknown Attribution', value: OCR.unknown_attribution,  icon: AlertCircle, color: 'text-slate-400' },
            { label: 'Queue Pending',     value: OCR.queue_pending,         icon: Clock,       color: 'text-yellow-400' },
            { label: 'Queue Processing',  value: OCR.queue_processing,      icon: Cpu,         color: 'text-blue-400' },
          ].map(({ label, value, icon: Icon, color }) => (
            ocrLoading ? <CardSkeleton key={label} /> :
            <div key={label} className="flex items-center gap-3 px-3 py-2.5 rounded-xl bg-surface border border-border">
              <Icon size={15} className={color} />
              <div>
                <p className="text-[10px] text-muted leading-tight">{label}</p>
                <p className={`text-sm font-bold ${color}`}>{value ?? '—'}</p>
              </div>
            </div>
          ))}
        </div>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mt-3">
          {[
            { label: 'Gemini Calls Today', value: OCR.gemini_calls_today, icon: Cpu, color: 'text-purple-400' },
            { label: 'Gemini Success Rate', value: OCR.gemini_success_rate ? `${OCR.gemini_success_rate}%` : '0%', icon: TrendingUp, color: 'text-emerald-400' },
            { label: 'Avg Latency', value: OCR.avg_latency_ms ? `${OCR.avg_latency_ms}ms` : '0ms', icon: Clock, color: 'text-slate-300' },
            { label: 'Queue Size', value: OCR.queue_size, icon: Clock, color: 'text-yellow-400' },
          ].map(({ label, value, icon: Icon, color }) => (
            ocrLoading ? <CardSkeleton key={label} /> :
            <div key={label} className="flex items-center gap-3 px-3 py-2.5 rounded-xl bg-surface border border-border">
              <Icon size={15} className={color} />
              <div>
                <p className="text-[10px] text-muted leading-tight">{label}</p>
                <p className={`text-sm font-bold ${color}`}>{value ?? '—'}</p>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* ── Charts Row 1 ────────────────────────────────────────────────── */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <SegmentDonut data={K} />
        <RegistrationsChart data={revenue?.registrations || []} />
        <RevenueChart data={revenue?.monthly || []} />
      </div>

      {/* ── Charts Row 2 ────────────────────────────────────────────────── */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <TopProducts data={products?.data || []} />
        <TopCities   data={cities?.data   || []} />
      </div>

      {/* ── Charts Row 3 ────────────────────────────────────────────────── */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <SizeTrends    data={sizes?.data    || []} />
        <ColourTrends  data={colours?.data  || []} />
        <PaymentMethods data={payments?.data || []} />
      </div>
    </div>
  )
}
