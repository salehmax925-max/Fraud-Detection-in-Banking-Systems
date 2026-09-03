/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        brand: {
          900: '#070b14',
          800: '#0a1020',
          700: '#0d1526',
          600: '#162035',
          500: '#1e2d5a',
          400: '#2a3f80',
          300: '#3b5bdb',
          200: '#7b94e8',
          100: '#b8c9f5',
          50:  '#e8edfb',
        },
        block:   { DEFAULT: '#ef4444', dark: '#991b1b', light: '#fca5a5', bg: '#1a0808' },
        review:  { DEFAULT: '#f59e0b', dark: '#92400e', light: '#fcd34d', bg: '#1a1004' },
        approve: { DEFAULT: '#10b981', dark: '#065f46', light: '#6ee7b7', bg: '#061a10' },
        cyan:    { DEFAULT: '#06b6d4', glow: '#0ea5e9', 400: '#22d3ee', 600: '#0891b2' },
        purple:  { DEFAULT: '#8b5cf6', 400: '#a78bfa' },
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
        mono: ['JetBrains Mono', 'Fira Code', 'Consolas', 'monospace'],
      },
      backgroundImage: {
        'gradient-radial': 'radial-gradient(var(--tw-gradient-stops))',
        'gradient-mesh': 'radial-gradient(ellipse 80% 50% at 20% 0%, rgba(6,182,212,0.06) 0%, transparent 60%), radial-gradient(ellipse 60% 40% at 80% 100%, rgba(59,130,246,0.04) 0%, transparent 60%)',
      },
      boxShadow: {
        'glow-cyan':   '0 0 20px rgba(6, 182, 212, 0.25)',
        'glow-red':    '0 0 20px rgba(239, 68, 68, 0.25)',
        'glow-green':  '0 0 20px rgba(16, 185, 129, 0.25)',
        'glow-yellow': '0 0 20px rgba(245, 158, 11, 0.25)',
        'card':        '0 8px 32px rgba(0,0,0,0.5)',
        'card-lg':     '0 16px 64px rgba(0,0,0,0.6)',
      },
      borderRadius: {
        '2xl': '1rem',
        '3xl': '1.5rem',
      },
      animation: {
        'pulse-slow': 'pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite',
        'slide-up': 'slideUp 0.25s ease-out',
        'fade-in': 'fadeIn 0.2s ease-out',
        'count-up': 'countUp 0.4s ease-out both',
        'pulse-glow': 'pulseGlow 2s ease-in-out infinite',
      },
      keyframes: {
        slideUp: {
          '0%': { transform: 'translateY(12px)', opacity: '0' },
          '100%': { transform: 'translateY(0)', opacity: '1' },
        },
        fadeIn: {
          '0%': { opacity: '0', transform: 'translateY(-4px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
        countUp: {
          '0%': { opacity: '0', transform: 'scale(0.85) translateY(4px)' },
          '100%': { opacity: '1', transform: 'scale(1) translateY(0)' },
        },
        pulseGlow: {
          '0%,100%': { boxShadow: '0 0 8px rgba(6,182,212,0.2)' },
          '50%': { boxShadow: '0 0 24px rgba(6,182,212,0.5)' },
        },
      },
    },
  },
  plugins: [],
}
