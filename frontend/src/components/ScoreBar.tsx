// src/components/ScoreBar.tsx
interface ScoreBarProps {
  score: number
  tier: string
  showLabel?: boolean
}

export default function ScoreBar({ score, tier, showLabel = true }: ScoreBarProps) {
  const pct = Math.round(score * 100)

  const fillClass =
    tier === 'BLOCK'
      ? 'score-gradient-block'
      : tier === 'REVIEW'
      ? 'score-gradient-review'
      : 'score-gradient-approve'

  return (
    <div className="flex items-center gap-2">
      <div className="score-bar flex-1 max-w-32">
        <div
          className={`score-bar-fill ${fillClass}`}
          style={{ width: `${pct}%` }}
        />
      </div>
      {showLabel && (
        <span className="text-xs font-mono text-slate-300 w-10 text-right">
          {score.toFixed(3)}
        </span>
      )}
    </div>
  )
}
