/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        bg:        '#020617',
        card:      '#0f172a',
        border:    '#1e293b',
        flipkart:  '#2874f0',
        d2c:       '#f97316',
        converted: '#8b5cf6',
        revenue:   '#10b981',
        muted:     '#64748b',
        surface:   '#0a1628',
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
      },
      boxShadow: {
        glow:    '0 0 20px rgba(139, 92, 246, 0.15)',
        'glow-blue': '0 0 20px rgba(40, 116, 240, 0.15)',
        'glow-green': '0 0 20px rgba(16, 185, 129, 0.15)',
      },
      animation: {
        'fade-in': 'fadeIn 0.3s ease-in-out',
        'slide-up': 'slideUp 0.4s ease-out',
        'pulse-slow': 'pulse 3s infinite',
      },
      keyframes: {
        fadeIn: {
          '0%': { opacity: '0' },
          '100%': { opacity: '1' },
        },
        slideUp: {
          '0%': { opacity: '0', transform: 'translateY(16px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
      },
    },
  },
  plugins: [],
}
