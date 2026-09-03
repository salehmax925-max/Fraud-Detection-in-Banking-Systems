// src/components/ShapChart.tsx
// SHAP waterfall-style bar chart showing top contributing features
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip,
  ReferenceLine, ResponsiveContainer, Cell
} from 'recharts'
import type { ShapFeature } from '../types'

interface ShapChartProps {
  features: ShapFeature[]
}

const CustomTooltip = ({ active, payload }: any) => {
  if (active && payload?.length) {
    const d = payload[0].payload
    return (
      <div className="bg-brand-800 border border-brand-600 rounded-lg p-3 text-xs shadow-card">
        <div className="font-semibold text-white mb-1">{d.feature_name}</div>
        <div className={`font-mono ${d.shap_value > 0 ? 'text-red-400' : 'text-green-400'}`}>
          SHAP: {d.shap_value > 0 ? '+' : ''}{d.shap_value.toFixed(4)}
        </div>
        <div className="text-slate-400 mt-1">
          Value: <span className="font-mono text-slate-300">{d.feature_value.toFixed(4)}</span>
        </div>
        <div className={`mt-1 font-medium ${d.direction === 'increases_risk' ? 'text-red-400' : 'text-green-400'}`}>
          {d.direction === 'increases_risk' ? '↑ Increases fraud risk' : '↓ Decreases fraud risk'}
        </div>
      </div>
    )
  }
  return null
}

export default function ShapChart({ features }: ShapChartProps) {
  if (!features || features.length === 0) {
    return (
      <div className="flex items-center justify-center h-32 text-slate-500 text-sm">
        No SHAP explanations available — SHAP explainer may not be loaded
      </div>
    )
  }

  // Sort by absolute SHAP value
  const data = [...features]
    .sort((a, b) => Math.abs(b.shap_value) - Math.abs(a.shap_value))
    .map(f => ({
      ...f,
      // Friendly feature name
      label: f.feature_name
        .replace('amount_deviation_z', 'Amount Deviation Z')
        .replace('time_of_day_risk', 'Night-time Risk')
        .replace('velocity_change', 'Velocity Change')
        .replace('location_entropy', 'New Device/Region')
        .replace('tx_freq_1h', 'Freq (1h)')
        .replace('tx_freq_24h', 'Freq (24h)')
        .replace(/^(V\d+)$/, (_, v) => v),
    }))

  return (
    <div className="h-64">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart
          data={data}
          layout="vertical"
          margin={{ top: 5, right: 60, left: 20, bottom: 5 }}
        >
          <CartesianGrid strokeDasharray="3 3" stroke="#1a2040" horizontal={false} />
          <XAxis
            type="number"
            tick={{ fill: '#94a3b8', fontSize: 11 }}
            tickLine={false}
            axisLine={{ stroke: '#1a2040' }}
            tickFormatter={(v) => v.toFixed(3)}
          />
          <YAxis
            dataKey="label"
            type="category"
            width={140}
            tick={{ fill: '#94a3b8', fontSize: 11 }}
            tickLine={false}
            axisLine={false}
          />
          <Tooltip content={<CustomTooltip />} />
          <ReferenceLine x={0} stroke="#2d3a6e" strokeWidth={1.5} />
          <Bar dataKey="shap_value" radius={[0, 4, 4, 0]}>
            {data.map((entry, index) => (
              <Cell
                key={`cell-${index}`}
                fill={entry.shap_value > 0 ? '#ef4444' : '#10b981'}
                fillOpacity={0.85}
              />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}
