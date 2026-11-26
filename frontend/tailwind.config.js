/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        background: {
          primary: '#080F1F',
          secondary: '#101B30',
        },
        accent: {
          primary: '#6366F1',   // Indigo
          secondary: '#22D3EE', // Cyan
        },
        state: {
          success: '#22C55E',
          warning: '#F59E0B',
          error: '#EF4444',
        },
        text: {
          primary: '#F8FAFC',
          secondary: '#94A3B8',
        }
      },
      fontFamily: {
        sans: ['Inter', 'Manrope', 'sans-serif'],
      },
      backgroundImage: {
        'liquid-gradient': 'radial-gradient(ellipse at top, rgba(99, 102, 241, 0.15) 0%, rgba(34, 211, 238, 0.08) 45%, rgba(8, 15, 31, 0) 70%)',
        'glass-card': 'linear-gradient(135deg, rgba(255, 255, 255, 0.05) 0%, rgba(255, 255, 255, 0.01) 100%)',
        'glass-card-hover': 'linear-gradient(135deg, rgba(255, 255, 255, 0.08) 0%, rgba(255, 255, 255, 0.02) 100%)',
      },
      boxShadow: {
        'glass': '0 8px 32px 0 rgba(0, 0, 0, 0.37)',
        'glass-glow': '0 0 25px rgba(99, 102, 241, 0.25)',
        'cyan-glow': '0 0 25px rgba(34, 211, 238, 0.25)',
      },
      backdropBlur: {
        'xs': '2px',
      }
    },
  },
  plugins: [],
}
