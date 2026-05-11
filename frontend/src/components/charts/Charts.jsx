import {
  PieChart, Pie, Cell, Tooltip, ResponsiveContainer, Legend,
  BarChart, Bar, XAxis, YAxis, CartesianGrid,
  LineChart, Line, Area, AreaChart,
} from 'recharts'

const TOOLTIP_STYLE = {
  backgroundColor: '#0f172a',
  border: '1px solid #1e293b',
  borderRadius: '12px',
  fontSize: '12px',
  color: '#e2e8f0',
}

// ── Donut: Customer Segmentation ─────────────────────────────────────────────
export function SegmentDonut({ data }) {
  const chartData = [
    { name: 'Converted',     value: data?.converted_customers || 0, color: '#8b5cf6' },
    { name: 'Marketplace Only', value: data?.only_marketplace || 0, color: '#2874f0' },
    { name: 'Direct D2C',    value: data?.direct_d2c_customers || 0, color: '#f97316' },
    { name: 'Heuristic Attribution', value: data?.heuristic_attribution_count || data?.probable_d2c_count || 0, color: '#10b981' },
    { name: 'Unknown',       value: data?.unknown_attribution_count || 0, color: '#64748b' },
  ]
  const total = chartData.reduce((s, c) => s + c.value, 0)

  return (
    <div className="glass-card p-5">
      <h3 className="text-sm font-semibold text-slate-300 mb-4">Customer Segmentation</h3>
      <div className="relative">
        <ResponsiveContainer width="100%" height={220}>
          <PieChart>
            <Pie
              data={chartData} cx="50%" cy="50%"
              innerRadius={60} outerRadius={90}
              paddingAngle={3} dataKey="value"
            >
              {chartData.map((entry, i) => (
                <Cell key={i} fill={entry.color} strokeWidth={0} />
              ))}
            </Pie>
            <Tooltip contentStyle={TOOLTIP_STYLE} />
            <Legend
              wrapperStyle={{ fontSize: '11px', paddingTop: '12px' }}
              formatter={(v, e) => (
                <span style={{ color: '#94a3b8' }}>{v}: <strong style={{ color: '#e2e8f0' }}>{e.payload.value}</strong></span>
              )}
            />
          </PieChart>
        </ResponsiveContainer>
        <div className="absolute inset-0 flex items-center justify-center pointer-events-none" style={{ marginBottom: 40 }}>
          <div className="text-center">
            <p className="text-2xl font-bold text-white">{total}</p>
            <p className="text-xs text-muted">Total</p>
          </div>
        </div>
      </div>
    </div>
  )
}

// ── Bar: Registrations by Month ───────────────────────────────────────────────
export function RegistrationsChart({ data = [] }) {
  return (
    <div className="glass-card p-5">
      <h3 className="text-sm font-semibold text-slate-300 mb-4">Warranty Registrations by Month</h3>
      <ResponsiveContainer width="100%" height={200}>
        <BarChart data={data} margin={{ top: 0, right: 0, left: -20, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
          <XAxis dataKey="month" tick={{ fill: '#64748b', fontSize: 11 }} />
          <YAxis tick={{ fill: '#64748b', fontSize: 11 }} />
          <Tooltip contentStyle={TOOLTIP_STYLE} />
          <Bar dataKey="count" fill="#2874f0" radius={[4, 4, 0, 0]} name="Registrations" />
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}

// ── Area: Revenue by Month ────────────────────────────────────────────────────
export function RevenueChart({ data = [] }) {
  return (
    <div className="glass-card p-5">
      <h3 className="text-sm font-semibold text-slate-300 mb-4">D2C Revenue by Month</h3>
      <ResponsiveContainer width="100%" height={200}>
        <AreaChart data={data} margin={{ top: 0, right: 0, left: -10, bottom: 0 }}>
          <defs>
            <linearGradient id="revenueGrad" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%"  stopColor="#10b981" stopOpacity={0.3} />
              <stop offset="95%" stopColor="#10b981" stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
          <XAxis dataKey="month" tick={{ fill: '#64748b', fontSize: 11 }} />
          <YAxis tick={{ fill: '#64748b', fontSize: 11 }} />
          <Tooltip contentStyle={TOOLTIP_STYLE} formatter={(v) => [`₹${v.toLocaleString('en-IN')}`, 'Revenue']} />
          <Area type="monotone" dataKey="revenue" stroke="#10b981" fill="url(#revenueGrad)" strokeWidth={2} />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  )
}

// ── Horizontal Bar: Top Products ──────────────────────────────────────────────
export function TopProducts({ data = [] }) {
  return (
    <div className="glass-card p-5">
      <h3 className="text-sm font-semibold text-slate-300 mb-4">Top Products</h3>
      <ResponsiveContainer width="100%" height={200}>
        <BarChart data={data.slice(0, 8)} layout="vertical" margin={{ top: 0, right: 10, left: 10, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" horizontal={false} />
          <XAxis type="number" tick={{ fill: '#64748b', fontSize: 11 }} />
          <YAxis type="category" dataKey="product" width={100} tick={{ fill: '#94a3b8', fontSize: 10 }}
            tickFormatter={(v) => v?.length > 14 ? v.slice(0, 14) + '…' : v} />
          <Tooltip contentStyle={TOOLTIP_STYLE} />
          <Bar dataKey="count" fill="#8b5cf6" radius={[0, 4, 4, 0]} name="Count" />
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}

// ── Grouped Bar: Top Cities ───────────────────────────────────────────────────
export function TopCities({ data = [] }) {
  return (
    <div className="glass-card p-5">
      <h3 className="text-sm font-semibold text-slate-300 mb-4">Top Cities</h3>
      <ResponsiveContainer width="100%" height={200}>
        <BarChart data={data.slice(0, 8)} margin={{ top: 0, right: 0, left: -20, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
          <XAxis dataKey="city" tick={{ fill: '#64748b', fontSize: 10 }} />
          <YAxis tick={{ fill: '#64748b', fontSize: 11 }} />
          <Tooltip contentStyle={TOOLTIP_STYLE} />
          <Bar dataKey="marketplace" fill="#2874f0" radius={[4, 4, 0, 0]} name="Marketplace" />
          <Bar dataKey="d2c"      fill="#f97316" radius={[4, 4, 0, 0]} name="D2C" />
          <Legend wrapperStyle={{ fontSize: '11px' }} formatter={(v) => <span style={{ color: '#94a3b8' }}>{v}</span>} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}

// ── Pie: Size Trends ──────────────────────────────────────────────────────────
export function SizeTrends({ data = [] }) {
  const COLORS = ['#2874f0', '#8b5cf6', '#10b981', '#f97316', '#ef4444', '#06b6d4']
  return (
    <div className="glass-card p-5">
      <h3 className="text-sm font-semibold text-slate-300 mb-4">Size Distribution</h3>
      <ResponsiveContainer width="100%" height={200}>
        <PieChart>
          <Pie data={data} dataKey="count" nameKey="size" cx="50%" cy="50%" outerRadius={75} paddingAngle={3}>
            {data.map((_, i) => <Cell key={i} fill={COLORS[i % COLORS.length]} strokeWidth={0} />)}
          </Pie>
          <Tooltip contentStyle={TOOLTIP_STYLE} />
          <Legend wrapperStyle={{ fontSize: '11px' }} formatter={(v) => <span style={{ color: '#94a3b8' }}>{v}</span>} />
        </PieChart>
      </ResponsiveContainer>
    </div>
  )
}

// ── Pie: Colour Trends ────────────────────────────────────────────────────────
export function ColourTrends({ data = [] }) {
  const COLORS = ['#ef4444', '#3b82f6', '#1e293b', '#f97316', '#22c55e', '#a855f7', '#eab308', '#ec4899']
  return (
    <div className="glass-card p-5">
      <h3 className="text-sm font-semibold text-slate-300 mb-4">Colour Distribution</h3>
      <ResponsiveContainer width="100%" height={200}>
        <PieChart>
          <Pie data={data} dataKey="count" nameKey="colour" cx="50%" cy="50%" outerRadius={75} paddingAngle={3}>
            {data.map((_, i) => <Cell key={i} fill={COLORS[i % COLORS.length]} strokeWidth={0} />)}
          </Pie>
          <Tooltip contentStyle={TOOLTIP_STYLE} />
          <Legend wrapperStyle={{ fontSize: '11px' }} formatter={(v) => <span style={{ color: '#94a3b8' }}>{v}</span>} />
        </PieChart>
      </ResponsiveContainer>
    </div>
  )
}

// ── Horizontal Bar: Payment Methods ──────────────────────────────────────────
export function PaymentMethods({ data = [] }) {
  return (
    <div className="glass-card p-5">
      <h3 className="text-sm font-semibold text-slate-300 mb-4">Payment Methods</h3>
      <ResponsiveContainer width="100%" height={200}>
        <BarChart data={data} layout="vertical" margin={{ top: 0, right: 10, left: 10, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" horizontal={false} />
          <XAxis type="number" tick={{ fill: '#64748b', fontSize: 11 }} />
          <YAxis type="category" dataKey="method" width={110} tick={{ fill: '#94a3b8', fontSize: 10 }}
            tickFormatter={(v) => v?.length > 16 ? v.slice(0, 16) + '…' : v} />
          <Tooltip contentStyle={TOOLTIP_STYLE} />
          <Bar dataKey="count" fill="#10b981" radius={[0, 4, 4, 0]} name="Orders" />
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}
