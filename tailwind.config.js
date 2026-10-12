/** @type {import('tailwindcss').Config} */
module.exports = {
  darkMode: 'class',
  content: [
    "./templates/**/*.html",
  ],
  theme: {
    extend: {
      colors: {
        zinc: {
          850: '#202024',
          900: '#18181b',
          950: '#09090b',
        }
      }
    },
  },
  plugins: [],
}
