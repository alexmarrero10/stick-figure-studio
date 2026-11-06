import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// `npm run dev` serves the pages at http://localhost:5174 and forwards /api to the site API on 8790.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5174,
    proxy: { "/api": "http://127.0.0.1:8790" },
  },
});
