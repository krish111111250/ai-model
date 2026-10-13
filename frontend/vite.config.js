import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import path from 'node:path'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    // "@/components/..." instead of "../../components/..." - shadcn's CLI
    // writes imports in this form, so the alias has to exist before adding
    // any of its components.
    // import.meta.dirname, not __dirname: this file is ESM, where __dirname
    // does not exist. It only appeared to work because Vite transpiles the
    // config to CJS before running it.
    alias: { '@': path.resolve(import.meta.dirname, './src') },
  },
})
