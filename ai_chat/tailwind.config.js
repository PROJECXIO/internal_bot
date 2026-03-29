/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{vue,js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        brand: {
          DEFAULT: "#41BB93",
          dark: "#2fa07c",
          light: "#e8f8f3",
        },
      },
    },
  },
  plugins: [],
};
