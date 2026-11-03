import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
// Only this reviewed, synthetic fixture enters the demo artifact. No DB or env input.
import syntheticSnapshot from '../docs/operations/public-snapshot.synthetic.json'

export default defineConfig({
  root: 'readonly',
  base: './',
  publicDir: false,
  plugins: [
    react(),
    {
      name: 'synthetic-public-snapshot',
      generateBundle() {
        this.emitFile({
          type: 'asset',
          fileName: 'snapshot.json',
          source: JSON.stringify(syntheticSnapshot, null, 2) + '\n',
        })
      },
    },
  ],
  build: {
    outDir: '../dist-readonly',
    emptyOutDir: true,
  },
})
