// src/components/TierBadge.tsx
interface TierBadgeProps {
  tier: string
  large?: boolean
}

export default function TierBadge({ tier, large = false }: TierBadgeProps) {
  const base = large
    ? 'font-bold text-sm px-4 py-1.5 rounded-full tracking-wide uppercase'
    : 'font-bold text-xs px-2.5 py-1 rounded-full tracking-wide uppercase'

  const variants: Record<string, string> = {
    BLOCK:   `bg-red-500/10   border border-red-500/25   text-red-400   ${base}`,
    REVIEW:  `bg-amber-500/10 border border-amber-500/25 text-amber-400 ${base}`,
    APPROVE: `bg-emerald-500/10 border border-emerald-500/25 text-emerald-400 ${base}`,
  }

  return (
    <span className={variants[tier] || `bg-white/5 border border-white/10 text-slate-400 ${base}`}>
      {tier}
    </span>
  )
}
