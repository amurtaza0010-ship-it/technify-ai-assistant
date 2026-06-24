/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
    "./components/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        brand: {
          50: "#ecfdf5",
          500: "#10a37f",
          600: "#0d8f6e",
          700: "#0a7359",
        },
      },
      boxShadow: {
        widget: "0 8px 30px rgba(0, 0, 0, 0.12)",
      },
    },
  },
  plugins: [],
};
