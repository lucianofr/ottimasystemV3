import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    // 8080 é a porta same-origin do nginx (serviço `frontend`); a API não é exposta no host.
    proxy: { "/api": "http://127.0.0.1:8080" },
  },
});
