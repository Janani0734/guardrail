import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: { 950: "#0b1220", 900: "#101a2e", 800: "#17233d", 700: "#22314f", 400: "#8a9bb8", 200: "#c9d3e4" },
        paper: { DEFAULT: "#f4f5f7", raised: "#ffffff" },
        line: "#e1e5ec",
        brand: { DEFAULT: "#0f766e", dark: "#0b5a54", soft: "#dff3f0" },
        allow: { fg: "#166534", bg: "#dcf5e4" },
        block: { fg: "#9f1239", bg: "#fde4ea" },
        review: { fg: "#92400e", bg: "#fdf0cf" },
        expired: { fg: "#475569", bg: "#e8ebf0" },
      },
      fontFamily: {
        sans: ["ui-sans-serif", "system-ui", "-apple-system", "Segoe UI", "Roboto", "Helvetica Neue", "Arial", "sans-serif"],
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "Consolas", "monospace"],
      },
    },
  },
  plugins: [],
};

export default config;
