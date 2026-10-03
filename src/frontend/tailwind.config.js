/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        paper: "#F4F2ED",
        surface: "#FCFCFB",
        sunken: "#EEEBE4",
        line: "#E2DED5",
        "line-strong": "#CFCAC0",
        ink: { DEFAULT: "#16181D", 2: "#4E4D49", 3: "#86837B" },
        brand: { DEFAULT: "#1F4D3A", hover: "#173D2D", soft: "#E3EDE7", ink: "#123326" },
        volt: "#C9E86A",
        tariff: { off: "#2A78D6", shoulder: "#1BAF7A", peak: "#EB6834", custom: "#4A3AA7" },
        good: { DEFAULT: "#0CA30C", ink: "#0B6E0B", soft: "#E4F4E2" },
        warn: { DEFAULT: "#FAB219", ink: "#7A5200", soft: "#FDF1D6" },
        serious: { DEFAULT: "#EC835A", ink: "#9A3F17", soft: "#FCE8DE" },
        critical: { DEFAULT: "#D03B3B", ink: "#A52A2A", soft: "#FAE3E1" },
      },
      fontFamily: {
        sans: ['"IBM Plex Sans"', "system-ui", "sans-serif"],
        mono: ['"IBM Plex Mono"', "ui-monospace", "monospace"],
      },
      fontSize: { "2xs": ["0.6875rem", { lineHeight: "1rem" }] },
      borderRadius: { DEFAULT: "6px" },
      boxShadow: { pop: "0 8px 24px -8px rgba(22,24,29,0.18), 0 2px 6px -2px rgba(22,24,29,0.08)" },
      keyframes: {
        pulsebar: { "0%,100%": { opacity: "1" }, "50%": { opacity: "0.55" } },
        slidein: { from: { transform: "translateX(16px)", opacity: "0" }, to: { transform: "none", opacity: "1" } },
      },
      animation: { pulsebar: "pulsebar 2.4s ease-in-out infinite", slidein: "slidein 180ms ease-out" },
    },
  },
  plugins: [],
};
