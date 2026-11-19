import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';

// In dev the API runs on :8000 (make dev). Proxying keeps one origin, so no CORS and the same
// relative `/api/v1` base works in dev, in `make preview` and behind Caddy in production.
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, '.', '');
  const target = env.DEV_API_TARGET || 'http://127.0.0.1:8000';
  return {
    plugins: [react()],
    server: {
      host: '127.0.0.1',
      port: 5173,
      proxy: {
        '/api': { target, changeOrigin: false },
        '/media': { target, changeOrigin: false },
      },
    },
    build: { target: 'es2020', sourcemap: false, chunkSizeWarningLimit: 600 },
  };
});
